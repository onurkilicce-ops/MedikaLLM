"""Provider rate limits: observe them, classify 429s, announce waits.

Groq (reached through the OpenAI-compatible client) answers every request
with ``x-ratelimit-*`` headers and rejects over-budget requests with HTTP 429
whose body names the limit that was hit, e.g. "... on tokens per minute
(TPM): Limit 8000, Used 6199, Requested 6264. Please try again in 33.47s".
The OpenAI client already waits ``retry-after`` seconds and retries when the
wait is at most 60 s, which covers the per-minute buckets. A per-day limit
cannot be waited out inside one chat answer.

``on_response`` is installed as an httpx response hook on the client used by
the chat model (see ``build_async_http_client``):

- every response: the limit headers are recorded for ``/health``;
- per-minute 429: the chat stream being answered (if any) is told how long
  the provider asked to wait, so the UI can show it instead of a silent
  spinner (``set_wait_notifier``);
- per-day 429: the client is told not to retry (``x-should-retry: false``)
  and the response is tagged so the error is reported as ``llm_daily_quota``
  without parsing exception text later.

Only 429 bodies are read; streamed 2xx bodies are never touched. The hook
never raises: observing limits must not break a request.
"""
from __future__ import annotations

import math
import re
import threading
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from logging import getLogger
from typing import Callable

import httpx

logger = getLogger(__name__)

STATUS_EVENT_CODE = "provider_rate_limit_wait"

# Response headers this module adds for downstream classification.
LIMIT_KIND_HEADER = "x-medicallm-limit-kind"
RETRY_AFTER_HEADER = "x-medicallm-retry-after-seconds"

# Limit kinds as Groq names them in 429 messages.
_KIND_PHRASES = (
    ("tpm", "tokens per minute"),
    ("tpd", "tokens per day"),
    ("rpm", "requests per minute"),
    ("rpd", "requests per day"),
)
DAILY_KINDS = frozenset({"tpd", "rpd"})
# The OpenAI client honours retry-after only up to this many seconds.
CLIENT_MAX_HONOURED_WAIT_S = 60

_TRY_AGAIN_RE = re.compile(r"try again in\s+((?:\d+(?:\.\d+)?\s*(?:ms|h|m|s)\s*)+)", re.IGNORECASE)
_DURATION_PART_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|h|m|s)", re.IGNORECASE)
_UNIT_SECONDS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}

# Recorded limit headers -> snapshot keys. Groq: "-requests" refers to the
# daily request budget, "-tokens" to the per-minute token bucket.
_HEADER_KEYS = {
    "x-ratelimit-limit-tokens": "tokens_per_minute_limit",
    "x-ratelimit-remaining-tokens": "tokens_per_minute_remaining",
    "x-ratelimit-reset-tokens": "tokens_per_minute_reset",
    "x-ratelimit-limit-requests": "requests_per_day_limit",
    "x-ratelimit-remaining-requests": "requests_per_day_remaining",
    "x-ratelimit-reset-requests": "requests_per_day_reset",
}

_wait_notifier: ContextVar[Callable[[dict], None] | None] = ContextVar(
    "provider_wait_notifier", default=None
)

_lock = threading.Lock()
_observed: dict = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- parsing -----------------------------------------------------------------

def parse_duration(text: str | None) -> float | None:
    """Parse Groq-style durations such as ``33.47s``, ``1m2.5s`` or ``2h3m``."""
    if not text:
        return None
    parts = _DURATION_PART_RE.findall(str(text))
    if not parts:
        return None
    return sum(float(value) * _UNIT_SECONDS[unit.lower()] for value, unit in parts)


def classify_limit_message(text: str | None) -> str | None:
    """Return ``tpm`` / ``tpd`` / ``rpm`` / ``rpd`` for a 429 message, else None."""
    lowered = (text or "").lower()
    for kind, phrase in _KIND_PHRASES:
        if phrase in lowered:
            return kind
    return None


def retry_after_seconds(headers: httpx.Headers | dict, body_text: str | None) -> float | None:
    """Seconds the provider asked us to wait (``retry-after`` header, else the body)."""
    raw = headers.get("retry-after") if headers is not None else None
    if raw:
        try:
            value = float(raw)
            if value >= 0:
                return value
        except ValueError:
            pass
    match = _TRY_AGAIN_RE.search(body_text or "")
    return parse_duration(match.group(1)) if match else None


# --- observed limits (for /health) ------------------------------------------

def record_headers(headers: httpx.Headers | dict) -> None:
    values = {key: headers.get(name) for name, key in _HEADER_KEYS.items() if headers.get(name)}
    if not values:
        return
    with _lock:
        _observed.update(values)
        _observed["observed_at"] = _now()


def _record_rejection(kind: str | None, seconds: float | None) -> None:
    with _lock:
        _observed["last_rejection"] = {
            "limit": kind or "unknown",
            "retry_after_seconds": None if seconds is None else math.ceil(seconds),
            "at": _now(),
        }


def snapshot() -> dict | None:
    """Last observed provider limits, or None before the first LLM response."""
    with _lock:
        return dict(_observed) if _observed else None


def reset() -> None:  # used by tests
    with _lock:
        _observed.clear()


# --- wait notices --------------------------------------------------------------

def set_wait_notifier(callback: Callable[[dict], None] | None) -> Token:
    """Route rate-limit wait notices of the current context to ``callback``.

    Set it in the task that runs one chat answer; child tasks (LangGraph
    nodes, the model call) inherit it through the copied context.
    """
    return _wait_notifier.set(callback)


def reset_wait_notifier(token: Token) -> None:
    _wait_notifier.reset(token)


def wait_notice(seconds: float, kind: str | None) -> dict:
    return {
        "type": "status",
        "code": STATUS_EVENT_CODE,
        "retry_after_seconds": max(1, math.ceil(seconds)),
        "limit": kind or "unknown",
    }


# --- httpx hook ----------------------------------------------------------------

async def on_response(response: httpx.Response) -> None:
    try:
        record_headers(response.headers)
        if response.status_code != 429:
            return
        await response.aread()  # small JSON body; read only for 429s
        try:
            body_text = response.text
        except Exception:
            body_text = ""
        kind = classify_limit_message(body_text)
        seconds = retry_after_seconds(response.headers, body_text)
        _record_rejection(kind, seconds)
        if kind:
            response.headers[LIMIT_KIND_HEADER] = kind
        if seconds is not None:
            response.headers[RETRY_AFTER_HEADER] = str(math.ceil(seconds))

        if kind in DAILY_KINDS:
            # Waiting is pointless inside one answer: fail now, with a clear code.
            response.headers["x-should-retry"] = "false"
            logger.warning("[PROVIDER LIMITS] Daily %s limit reached; not retrying", kind.upper())
            return

        if seconds is None or seconds > CLIENT_MAX_HONOURED_WAIT_S:
            return  # the client will not wait this long; no promise to the user
        notifier = _wait_notifier.get()
        logger.info(
            "[PROVIDER LIMITS] %s limit reached; client retries in ~%ss",
            (kind or "unknown").upper(), math.ceil(seconds),
        )
        if notifier is not None:
            notifier(wait_notice(seconds, kind))
    except Exception:  # pragma: no cover - observation must never break a call
        logger.debug("[PROVIDER LIMITS] response hook failed", exc_info=True)


def build_async_http_client() -> httpx.AsyncClient:
    """httpx client for the OpenAI SDK with the rate-limit hook installed."""
    from openai import DefaultAsyncHttpxClient

    return DefaultAsyncHttpxClient(event_hooks={"response": [on_response]})
