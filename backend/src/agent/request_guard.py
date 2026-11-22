"""Keep every model call inside the provider's per-request token budget.

Runs as LangChain agent middleware around each model call of a turn:

1. hides ``analyze_patient_medications`` when no patient context is active —
   without a patient it can only answer UNRESOLVED, and its schema is sent
   (and counted against the provider limit) on every call;
2. estimates the call (messages + tool schemas, see token_budget); above
   ``budget_tokens`` it drops earlier conversation history, oldest first —
   never the system prompt, the current question or this turn's tool calls
   and results;
3. if the call still does not fit, raises ``RequestBudgetExceeded`` before
   anything is sent, instead of a request the provider rejects with 413.
   The chat stream reports it as ``llm_request_too_large``.
"""
from __future__ import annotations

from logging import getLogger
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage

from .token_budget import (
    RequestBudgetExceeded,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tools_tokens,
    estimator_name,
)
from .tools import get_current_patient_id

logger = getLogger(__name__)

# Tools that only work with an active (authorized) patient context.
PATIENT_ONLY_TOOLS = frozenset({"analyze_patient_medications"})


def _tool_name(tool: Any) -> str | None:
    name = getattr(tool, "name", None)
    if name:
        return name
    if isinstance(tool, dict):
        return tool.get("name") or (tool.get("function") or {}).get("name")
    return None


def drop_history_to_fit(messages: list, fixed_tokens: int, budget_tokens: int) -> tuple[list, int]:
    """Drop earlier-turn messages (oldest first) until the call fits.

    Droppable: everything after a leading system message and before the
    last human message (the current question). Returns the kept messages and
    the new estimate (``fixed_tokens`` included).
    """
    kept = list(messages)
    total = fixed_tokens + estimate_messages_tokens(kept)
    last_human = max((i for i, m in enumerate(kept) if isinstance(m, HumanMessage)), default=None)
    if last_human is None:
        return kept, total
    first = 1 if kept and isinstance(kept[0], SystemMessage) else 0
    droppable = last_human - first
    while droppable > 0 and total > budget_tokens:
        removed = kept.pop(first)
        total -= estimate_message_tokens(removed)
        droppable -= 1
    return kept, total


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
            logger.info(
                "[REQUEST GUARD] Dropped %d earlier message(s) to fit the budget "
                "(estimate %d / %d tokens, %s)",
                before - len(messages), total, self.budget_tokens, estimator_name(),
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
