"""Keep every model call inside the provider's per-request token budget.

Runs as LangChain agent middleware around each model call of a turn:

1. hides ``analyze_patient_medications`` when no patient context is active —
   without a patient it can only answer UNRESOLVED, and its schema is sent
   (and counted against the provider limit) on every call;
2. estimates the call (messages + tool schemas, see token_budget); above
   ``budget_tokens`` it drops earlier conversation history, oldest first —
   never the system prompt, the current question or this turn's tool calls
   and results — and tells the model in the system message that it did;
3. if that is not enough, shortens this turn's largest tool result(s) from
   the end, keeping their beginning (the STATUS line comes first) and adding
   an explicit marker, down to a floor of TOOL_RESULT_FLOOR_TOKENS each;
4. if the call still does not fit, raises ``RequestBudgetExceeded`` before
   anything is sent, instead of a request the provider rejects with 413.
   The chat stream reports it as ``llm_request_too_large``.

Only the request sent to the model is changed; the conversation state, the
recorded tool executions and the sources shown to the user are not.
"""
from __future__ import annotations

from logging import getLogger
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from .token_budget import (
    RequestBudgetExceeded,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_text_tokens,
    estimate_tools_tokens,
    estimator_name,
    truncate_to_tokens,
)
from .tools import get_current_patient_id

logger = getLogger(__name__)

# Tools that only work with an active (authorized) patient context.
PATIENT_ONLY_TOOLS = frozenset({"analyze_patient_medications"})

# A tool result is never shortened below this (keeps STATUS and the first items).
TOOL_RESULT_FLOOR_TOKENS = 300
TOOL_RESULT_MARKER = (
    "\n[… tool output shortened here to fit the language model provider's per-request "
    "limit; the rest is not shown to you — do not state anything about it; tell the user "
    "the answer is based on part of the results.]"
)


def _history_note(count: int) -> str:
    return (
        f"\n\n[Note: {count} earlier conversation message(s) were left out of this request "
        "to fit the provider limit; if the question refers to them, say you no longer have "
        "that context.]"
    )


def _tool_name(tool: Any) -> str | None:
    name = getattr(tool, "name", None)
    if name:
        return name
    if isinstance(tool, dict):
        return tool.get("name") or (tool.get("function") or {}).get("name")
    return None


def _last_human_index(messages: list) -> int | None:
    return max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=None)


def drop_history_to_fit(messages: list, fixed_tokens: int, budget_tokens: int) -> tuple[list, int]:
    """Drop earlier-turn messages (oldest first) until the call fits.

    Droppable: everything after a leading system message and before the
    last human message (the current question). Returns the kept messages and
    the new estimate (``fixed_tokens`` included).
    """
    kept = list(messages)
    total = fixed_tokens + estimate_messages_tokens(kept)
    last_human = _last_human_index(kept)
    if last_human is None:
        return kept, total
    first = 1 if kept and isinstance(kept[0], SystemMessage) else 0
    droppable = last_human - first
    while droppable > 0 and total > budget_tokens:
        removed = kept.pop(first)
        total -= estimate_message_tokens(removed)
        droppable -= 1
    return kept, total


def shrink_tool_results_to_fit(messages: list, total: int, budget_tokens: int) -> tuple[list, int, int]:
    """Shorten this turn's largest tool results until the call fits.

    Returns (messages, new estimate, number of results shortened). Each result
    keeps its beginning and gets TOOL_RESULT_MARKER; none goes below
    TOOL_RESULT_FLOOR_TOKENS.
    """
    out = list(messages)
    last_human = _last_human_index(out)
    start = (last_human + 1) if last_human is not None else 0
    marker_tokens = estimate_text_tokens(TOOL_RESULT_MARKER)
    shortened: set[int] = set()
    while total > budget_tokens:
        candidates = [
            (estimate_text_tokens(str(m.content)), i)
            for i, m in enumerate(out)
            if i >= start and isinstance(m, ToolMessage) and i not in shortened
        ]
        candidates = [(t, i) for t, i in candidates if t > TOOL_RESULT_FLOOR_TOKENS + marker_tokens]
        if not candidates:
            break
        tokens, idx = max(candidates)
        # 8 tokens of slack: cutting and re-joining can shift a token boundary.
        target = max(TOOL_RESULT_FLOOR_TOKENS, tokens - (total - budget_tokens) - marker_tokens - 8)
        before = estimate_message_tokens(out[idx])
        text = truncate_to_tokens(str(out[idx].content), target)
        cut = text.rfind("\n")
        if cut > len(text) // 2:  # end on a whole line when that keeps most of the text
            text = text[:cut]
        out[idx] = out[idx].model_copy(update={"content": text.rstrip() + TOOL_RESULT_MARKER})
        total += estimate_message_tokens(out[idx]) - before
        shortened.add(idx)
    return out, total, len(shortened)


class RequestGuardMiddleware(AgentMiddleware):
    """See module docstring."""

    def __init__(self, budget_tokens: int):
        super().__init__()
        self.budget_tokens = budget_tokens

    def _prepare(self, request: Any) -> Any:
        tools = list(request.tools or [])
        if get_current_patient_id() is None:
            tools = [t for t in tools if _tool_name(t) not in PATIENT_ONLY_TOOLS]

        fixed = estimate_tools_tokens(tools)
        if getattr(request, "system_message", None) is not None:
            fixed += estimate_message_tokens(request.system_message)
        messages = list(request.messages)
        total = fixed + estimate_messages_tokens(messages)

        if total > self.budget_tokens:
            before = len(messages)
            messages, total = drop_history_to_fit(messages, fixed, self.budget_tokens)
            dropped = before - len(messages)
            if dropped and messages and isinstance(messages[0], SystemMessage):
                note = _history_note(dropped)
                messages[0] = messages[0].model_copy(update={"content": f"{messages[0].content}{note}"})
                total += estimate_text_tokens(note)
            if dropped:
                logger.info(
                    "[REQUEST GUARD] Left out %d earlier message(s) (estimate %d / %d tokens, %s)",
                    dropped, total, self.budget_tokens, estimator_name(),
                )
        if total > self.budget_tokens:
            messages, total, shortened = shrink_tool_results_to_fit(messages, total, self.budget_tokens)
            if shortened:
                logger.info(
                    "[REQUEST GUARD] Shortened %d tool result(s) (estimate %d / %d tokens, %s)",
                    shortened, total, self.budget_tokens, estimator_name(),
                )
        if total > self.budget_tokens:
            logger.warning(
                "[REQUEST GUARD] Model call not sent: estimate %d > budget %d tokens (%s)",
                total, self.budget_tokens, estimator_name(),
            )
            raise RequestBudgetExceeded(total, self.budget_tokens)
        return request.override(tools=tools, messages=messages)

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return handler(self._prepare(request))

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return await handler(self._prepare(request))
