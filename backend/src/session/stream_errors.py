"""Map exceptions raised while answering a chat query to safe, typed errors.

The chat stream used to forward ``str(exc)`` to the browser, which leaked
provider payloads (organisation ids, raw HTTP bodies) and gave the user no
stable way to tell a timeout from a bad API key. Every failure is now turned
into a ``StreamError`` with:

- ``code``: a stable machine-readable identifier the frontend localises;
- ``message``: a short English fallback that never contains exception text,
  URLs, credentials or patient data;
- ``retryable``: whether retrying the same question can reasonably succeed.

The full exception (with traceback) is logged server-side together with the
request id, so operators keep the detail while users only see the summary.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

# Codes whose root cause is the LLM provider (used for the /health LLM status).
LLM_ERROR_CODES = frozenset({
    "llm_timeout",
    "llm_unreachable",
    "llm_auth",
    "llm_rate_limited",
    "llm_daily_quota",
    "llm_request_too_large",
    "llm_bad_request",
    "llm_provider_error",
})


class EmptyAnswerError(Exception):
    """The agent finished without producing any answer text."""


@dataclass(frozen=True)
class StreamError:
    code: str
    message: str
    retryable: bool
    # Provider-requested wait (rate limits only); omitted from events when unknown.
    retry_after_seconds: int | None = None

    def to_event(self, request_id: str | None = None) -> dict:
        """SSE payload. ``error`` duplicates ``message`` for older clients."""
        event = {
            "type": "error",
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "error": self.message,
        }
        if self.retry_after_seconds is not None:
            event["retry_after_seconds"] = self.retry_after_seconds
        if request_id:
            event["request_id"] = request_id
        return event


_MESSAGES: dict[str, tuple[str, bool]] = {
    "llm_timeout": ("The language model did not respond in time.", True),
    "llm_unreachable": ("Could not reach the language model provider.", True),
    "llm_auth": (
        "The language model provider rejected the configured credentials.",
        False,
    ),
    "llm_rate_limited": (
        "The language model provider's rate or token limit was reached. "
        "Please wait a moment and retry.",
        True,
    ),
    "llm_daily_quota": (
        "The language model provider's daily usage limit has been reached. "
        "Try again after it resets.",
        False,
    ),
    "llm_request_too_large": (
        "This question needs more context than the language model provider "
        "accepts in one request. Ask about fewer drugs at once or start a new "
        "conversation.",
        False,
    ),
    "llm_bad_request": ("The language model rejected the request.", True),
    "llm_provider_error": ("The language model provider returned an error.", True),
    "agent_step_limit": (
        "The assistant stopped because it exceeded its step limit.",
        False,
    ),
    "database_unavailable": ("The drug database could not be queried.", True),
    "stream_timeout": (
        "The answer took too long and was stopped before completion.",
        True,
    ),
    "empty_response": (
        "The model finished without producing an answer.",
        True,
    ),
    "agent_unavailable": (
        "The assistant is not available because it failed to start.",
        False,
    ),
    "unauthorized_session": ("You do not have access to this conversation.", False),
    "internal_error": ("An unexpected server error occurred.", True),
}


def make_error(code: str, retry_after_seconds: int | None = None) -> StreamError:
    message, retryable = _MESSAGES.get(code, _MESSAGES["internal_error"])
    if code not in _MESSAGES:
        code = "internal_error"
    return StreamError(
        code=code, message=message, retryable=retryable,
        retry_after_seconds=retry_after_seconds,
    )


def _status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _rate_limit_error(exc: BaseException) -> StreamError:
    """Per-day vs per-minute 429, from the tags ``provider_limits`` put on the
    response (never from the exception text)."""
    from ..agent.provider_limits import DAILY_KINDS, LIMIT_KIND_HEADER, RETRY_AFTER_HEADER

    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    kind = headers.get(LIMIT_KIND_HEADER)
    retry_after = None
    raw = headers.get(RETRY_AFTER_HEADER)
    if raw and str(raw).isdigit():
        retry_after = int(raw)
    if kind in DAILY_KINDS:
        return make_error("llm_daily_quota", retry_after_seconds=retry_after)
    return make_error("llm_rate_limited", retry_after_seconds=retry_after)


def classify_exception(exc: BaseException) -> StreamError:
    """Return the safe error for ``exc``. Never echoes its text."""
    if isinstance(exc, EmptyAnswerError):
        return make_error("empty_response")
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return make_error("stream_timeout")

    from ..agent.token_budget import RequestBudgetExceeded

    if isinstance(exc, RequestBudgetExceeded):
        # Caught before the provider was called (see request_guard).
        return make_error("llm_request_too_large")

    # OpenAI-compatible SDK errors (Groq is reached through the OpenAI client).
    try:  # pragma: no branch - import guard only
        import openai
    except Exception:  # pragma: no cover - openai is a hard dependency
        openai = None  # type: ignore[assignment]

    if openai is not None:
        if isinstance(exc, openai.APITimeoutError):
            return make_error("llm_timeout")
        if isinstance(exc, openai.APIConnectionError):
            return make_error("llm_unreachable")
        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return make_error("llm_auth")
        if isinstance(exc, openai.RateLimitError):
            return _rate_limit_error(exc)
        if isinstance(exc, openai.APIStatusError):
            status = _status_code(exc)
            if status == 413:
                return make_error("llm_request_too_large")
            if status in (401, 403):
                return make_error("llm_auth")
            if status == 429:
                return _rate_limit_error(exc)
            if status is not None and 400 <= status < 500:
                return make_error("llm_bad_request")
            return make_error("llm_provider_error")

    # LangGraph recursion guard (agent looped through too many tool calls).
    if type(exc).__name__ == "GraphRecursionError":
        return make_error("agent_step_limit")

    try:
        from sqlalchemy.exc import DBAPIError, OperationalError, TimeoutError as PoolTimeout
    except Exception:  # pragma: no cover
        DBAPIError = OperationalError = PoolTimeout = ()  # type: ignore[assignment]
    if DBAPIError and isinstance(exc, (DBAPIError, OperationalError, PoolTimeout)):
        return make_error("database_unavailable")

    return make_error("internal_error")
