"""Token estimates for staying inside the provider's per-request budget.

Groq's free tier allows 8,000 tokens per minute for openai/gpt-oss-20b and
rejects a single request above that with HTTP 413. Every model call re-sends
the system prompt, the tool schemas and the conversation so far, so the
request size has to be controlled before the call, not discovered after it.

Estimates use tiktoken's ``o200k_base`` encoding (the gpt-oss tokenizer
family). Groq counts its own rendering of the request, in which tool schemas
are more compact than JSON: for the original prompt the estimate was 6,659
against 6,200 counted (2026-11-18), so estimates err on the safe side. tiktoken may need to download its encoding file once; that never
happens on the request path: ``warm_up()`` loads it in a background thread
and, until it is ready (or if it cannot be loaded), a conservative
character-based estimate is used instead.
"""
from __future__ import annotations

import json
import math
import threading
import time
from logging import getLogger
from typing import Any, Iterable

logger = getLogger(__name__)

# Fallback when tiktoken is not loaded: o200k_base averages ~4.2 characters
# per token on English prompt text and ~3.7 on Turkish; 3.6 stays on the safe
# side for both without refusing ordinary requests (chars/3 overestimated the
# fixed prompt + tool schemas by ~40%).
FALLBACK_CHARS_PER_TOKEN = 3.6
# Role/formatting tokens the chat template adds around each message.
MESSAGE_OVERHEAD_TOKENS = 4
SHORTENED_MARKER = "\n[… earlier message shortened to fit the provider limit]"
# After a failed tokenizer load (e.g. the one-time encoding download had no
# network), try again in the background at most this often.
RETRY_LOAD_AFTER_SECONDS = 600.0

_encoder: Any = None
_encoder_state = "not_loaded"  # not_loaded | loading | ready | unavailable
_encoder_failed_at = 0.0
_encoder_lock = threading.Lock()
_encoder_attempt_done = threading.Event()  # set when a load attempt finishes
_tool_cache: dict[tuple, int] = {}


class RequestBudgetExceeded(Exception):
    """A model call would exceed the per-request token budget even after
    dropping earlier conversation history. Raised before calling the provider."""

    def __init__(self, estimated_tokens: int, budget_tokens: int):
        super().__init__(f"estimated {estimated_tokens} tokens > budget {budget_tokens}")
        self.estimated_tokens = estimated_tokens
        self.budget_tokens = budget_tokens


def _load_encoder() -> None:
    global _encoder, _encoder_state, _encoder_failed_at
    try:
        import tiktoken

        enc = tiktoken.get_encoding("o200k_base")
        with _encoder_lock:
            _encoder, _encoder_state = enc, "ready"
    except Exception as exc:  # offline first run, missing package, ...
        with _encoder_lock:
            _encoder_state, _encoder_failed_at = "unavailable", time.monotonic()
        logger.warning(
            "[TOKEN BUDGET] tiktoken encoding unavailable (%s); using a "
            "conservative character-based estimate, retrying later", type(exc).__name__,
        )
    finally:
        _encoder_attempt_done.set()


def warm_up(blocking: bool = False) -> None:
    """Load the tokenizer (in the background unless ``blocking``).

    A no-op once loaded or while loading; after a failure it tries again only
    when RETRY_LOAD_AFTER_SECONDS have passed.
    """
    global _encoder_state
    with _encoder_lock:
        state = _encoder_state
        if state == "ready":
            return
        if state == "unavailable" and time.monotonic() - _encoder_failed_at < RETRY_LOAD_AFTER_SECONDS:
            return
        if state != "loading":
            _encoder_state = "loading"
            _encoder_attempt_done.clear()
    if state == "loading":
        if blocking:  # a background load is in progress: wait for its outcome
            _encoder_attempt_done.wait(timeout=30)
        return
    if blocking:
        _load_encoder()
    else:
        threading.Thread(target=_load_encoder, name="tiktoken-warmup", daemon=True).start()


def estimator_name() -> str:
    return "tiktoken:o200k_base" if _encoder_state == "ready" else f"chars/{FALLBACK_CHARS_PER_TOKEN}"


def estimate_text_tokens(text: str | None) -> int:
    if not text:
        return 0
    if _encoder_state == "unavailable":
        warm_up()  # rate-limited background retry
    if _encoder_state == "ready" and _encoder is not None:
        try:
            return len(_encoder.encode(text, disallowed_special=()))
        except Exception:
            pass
    return math.ceil(len(text) / FALLBACK_CHARS_PER_TOKEN)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """The beginning of ``text`` within about ``max_tokens`` (no marker added)."""
    if max_tokens <= 0 or not text:
        return ""
    if _encoder_state == "ready" and _encoder is not None:
        try:
            ids = _encoder.encode(text, disallowed_special=())
            return text if len(ids) <= max_tokens else _encoder.decode(ids[:max_tokens])
        except Exception:
            pass
    max_chars = int(max_tokens * FALLBACK_CHARS_PER_TOKEN)
    return text if len(text) <= max_chars else text[:max_chars]


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content blocks
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
        return "".join(parts)
    return "" if content is None else str(content)


def estimate_message_tokens(message: Any) -> int:
    """Estimate one chat message (dict or LangChain message, incl. tool calls)."""
    if isinstance(message, dict):
        content = message.get("content")
        tool_calls = message.get("tool_calls") or []
    else:
        content = getattr(message, "content", "")
        tool_calls = getattr(message, "tool_calls", None) or []
    tokens = MESSAGE_OVERHEAD_TOKENS + estimate_text_tokens(_content_text(content))
    if tool_calls:
        slim = [
            {"name": c.get("name"), "args": c.get("args")} if isinstance(c, dict) else str(c)
            for c in tool_calls
        ]
        tokens += estimate_text_tokens(json.dumps(slim, ensure_ascii=False, default=str))
    return tokens


def estimate_messages_tokens(messages: Iterable[Any]) -> int:
    return sum(estimate_message_tokens(m) for m in messages)


def estimate_tool_tokens(tool: Any) -> int:
    """Estimate one tool's schema as sent to the API.

    Tool objects are long-lived singletons, so their estimate is cached per
    object (and per estimator); plain dict schemas are estimated each time.
    """
    key = None if isinstance(tool, dict) else (id(tool), estimator_name())
    if key is not None and key in _tool_cache:
        return _tool_cache[key]
    try:
        from langchain_core.utils.function_calling import convert_to_openai_tool

        schema = tool if isinstance(tool, dict) else convert_to_openai_tool(tool)
        tokens = estimate_text_tokens(json.dumps(schema, ensure_ascii=False))
    except Exception:
        tokens = estimate_text_tokens(str(getattr(tool, "description", "") or tool))
    if key is not None:
        _tool_cache[key] = tokens
    return tokens


def estimate_tools_tokens(tools: Iterable[Any]) -> int:
    return sum(estimate_tool_tokens(t) for t in tools)


def shorten_text(text: str, max_tokens: int) -> str | None:
    """Beginning of ``text`` within ``max_tokens`` plus a visible marker."""
    # 2 tokens of slack: cutting and re-joining can shift a token boundary.
    budget = max_tokens - estimate_text_tokens(SHORTENED_MARKER) - 2
    if budget < 40:
        return None
    if _encoder_state == "ready" and _encoder is not None:
        try:
            ids = _encoder.encode(text, disallowed_special=())
            if len(ids) <= max_tokens:
                return text
            return _encoder.decode(ids[:budget]).rstrip() + SHORTENED_MARKER
        except Exception:
            pass
    max_chars = int(budget * FALLBACK_CHARS_PER_TOKEN)
    if len(text) <= int(max_tokens * FALLBACK_CHARS_PER_TOKEN):
        return text
    return text[:max_chars].rstrip() + SHORTENED_MARKER


def select_history(messages: list[dict], token_budget: int, max_messages: int) -> list[dict]:
    """Conversation history for the next model call.

    ``messages`` ends with the current user question, which is always kept.
    Earlier messages are added newest first while they fit ``token_budget``
    (estimated tokens) and ``max_messages``; the first one that does not fit
    stops the selection, so the history stays a contiguous recent window.
    If not even the newest earlier message fits, its beginning is kept with
    an explicit marker: a follow-up question most likely refers to it.
    """
    if not messages:
        return []
    current, earlier = messages[-1], messages[:-1]
    if max_messages <= 1 or token_budget <= 0:
        return [current]
    earlier = earlier[-(max_messages - 1):]
    kept: list[dict] = []
    left = token_budget
    for message in reversed(earlier):
        cost = estimate_message_tokens(message)
        if cost <= left:
            kept.append(message)
            left -= cost
            continue
        if not kept:
            shortened = shorten_text(_content_text(message.get("content")), left - MESSAGE_OVERHEAD_TOKENS)
            if shortened:
                kept.append({**message, "content": shortened})
        break
    kept.reverse()
    return kept + [current]
