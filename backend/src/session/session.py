from __future__ import annotations
import time
import uuid
from typing import List, Dict, Any
import asyncio
from pydantic import BaseModel
import uuid as _uuid

from ..agent.agent import MedicalAgent
from ..auth.models import UserBase
from ..conversations import service as conv_service
from ..conversations.models import Conversation, Message, ToolExecution
from ..agent.tools import (
    get_last_search_sources,
    get_last_tool_debug,
    peek_search_sources,
    set_request_id,
    set_current_patient_id,
)
from ..agent.langchain_agent import SYSTEM_PROMPT
from ..agent.citations import check_citations
from ..agent import llm_status
from ..agent.token_budget import select_history
from ..config import settings
from .stream_errors import LLM_ERROR_CODES, EmptyAnswerError, classify_exception, make_error

from logging import getLogger
logger = getLogger(__name__)


def _usage_of(message: Any) -> dict | None:
    """Provider-reported token usage of one model call (LangChain usage_metadata)."""
    usage = getattr(message, "usage_metadata", None)
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if input_tokens is None and output_tokens is None:
        return None
    return {"input_tokens": input_tokens or 0, "output_tokens": output_tokens or 0}


def _usage_summary(calls: list[dict]) -> dict:
    """Per-answer token totals: what the turn cost against the provider limits."""
    return {
        "calls": len(calls),
        "input_tokens": sum(c["input_tokens"] for c in calls),
        "output_tokens": sum(c["output_tokens"] for c in calls),
        "per_call": calls,
    }

# section: Models

class AgentResponse(BaseModel):
    # Messages to append to conversation, including final AI response and any intermediate tool calls
    messages: List[Message]
    success: bool
    conversation_id: str
    
    # number of messages (agent and user) in conversation after appending
    # not assigned until after messages are appended to conversation and saved to DB, so optional here
    total_message_count: int | None = None 
    
    debug: Dict[str, Any] = {}
    
    # Convenience accessors - computed from messages
    @property
    def tool_responses(self) -> List[dict]:
        """Get all tool executions from messages."""
        responses = []
        for msg in self.messages:
            if getattr(msg, "tools_used", None):
                for i in range(len(msg.tools_used)):
                    # handle possible length mismatch
                    t_res = msg.tool_results[i] if i < len(getattr(msg, "tool_results", [])) else ""
                    responses.append({
                        "tool_name": msg.tools_used[i],
                        "tool_result": t_res
                    })
        return responses
    
    @property
    def agent_sources(self) -> List[dict]:
        """Get all sources from messages."""
        sources = []
        for msg in self.messages:
            if getattr(msg, "sources", None):
                sources.extend(msg.sources)
        return sources

    @staticmethod
    def from_agent_result(result: dict, conversation_id: str, request_id: str) -> AgentResponse:
        # Extract AI response
        ai_response = (
            result["messages"][-1].content
            if result.get("messages")
            else "No response generated"
        )

        # Check for search sources (use request_id for cross-thread lookup)
        # Returns list of dicts with structured source information
        sources = get_last_search_sources(request_id=request_id)

        # Check for tool debug info
        tool_debug = get_last_tool_debug(request_id=request_id)

        # Collect comprehensive tool execution information
        tool_executions = []
        tools_used = []  # Legacy support
        tool_results = []  # Legacy support

        if result.get("messages"):
            messages = result["messages"]
            for i, msg in enumerate(messages):
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        t_name = tool_call.get("name")
                        t_id = tool_call.get("id")
                        t_args = tool_call.get("args", {})
                        
                        if t_name:
                            tools_used.append(t_name)  # Legacy
                            
                            # Find corresponding tool response
                            tool_result_content = ""
                            tool_error = None
                            for j in range(i + 1, len(messages)):
                                next_msg = messages[j]
                                if hasattr(next_msg, "tool_call_id") and next_msg.tool_call_id == t_id:
                                    tool_result_content = next_msg.content
                                    tool_results.append(tool_result_content)  # Legacy
                                    
                                    # Check if result indicates an error
                                    if "error" in tool_result_content.lower()[:100]:
                                        tool_error = tool_result_content[:500]
                                    break
                            
                            # Create detailed tool execution record
                            tool_exec = ToolExecution(
                                tool_name=t_name,
                                tool_args=t_args,
                                tool_result=tool_result_content,
                                error=tool_error,
                            )
                            tool_executions.append(tool_exec)

        # Create message with structured sources and comprehensive tool info
        assistant_message = Message(
            role="assistant",
            content=ai_response,
            tools_used=tools_used,  # Legacy
            tool_results=tool_results,  # Legacy
            tool_executions=tool_executions,  # New comprehensive tracking
            sources=sources if sources else [],
            debug={"tool_debug": tool_debug} if tool_debug else {},
        )

        return AgentResponse(
            messages=[assistant_message],
            success=True,
            conversation_id=conversation_id,
            debug={"tool_debug": tool_debug} if tool_debug else {},
        )
# section

class Session:
    """
    Session class for managing conversation state and agent interactions.
    Uses LangChain's message format and LangGraph state management.
    """
    def __init__(
        self,
        conversation_id: str,
        user_id: str,
        agent: MedicalAgent,
    ):
        self.session_id = str(uuid.uuid4())
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.agent: MedicalAgent = agent

        # Load conversation from database
        self.conversation: Conversation | None = conv_service.get_conversation(conversation_id)

        if not self.conversation:
            self.conversation = conv_service.create_conversation(
                user_id=user_id, title=settings.default_conversation_title
            )

    def get_message_history(self) -> list:
        """
        Get conversation history in LangChain message format.

        The last message is the current question and is always included.
        Earlier messages are added newest first within
        ``chat_history_token_budget`` (estimated tokens) and at most
        ``max_history_turns`` user+assistant pairs: every model call of a turn
        re-sends them, and the provider limits tokens per request and per
        minute (see agent/token_budget.py).
        """
        if not self.conversation:
            return []

        messages = []
        for msg in self.conversation.messages:
            if msg.role == "user":
                messages.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                messages.append({"role": "assistant", "content": msg.content})

        return select_history(
            messages,
            token_budget=settings.chat_history_token_budget,
            max_messages=settings.max_history_turns * 2,
        )

    async def handle_user_query(self, query: str, system_prompt: str = SYSTEM_PROMPT, current_user: UserBase | None = None) -> AgentResponse:
        """
        Process a user query through the agent.

        Args:
            query: The user's question.
            system_prompt: Optional dynamic system prompt. When supplied it
                replaces the default SYSTEM_PROMPT for this single invocation,
                enabling role-aware and patient-context responses.
            patient_id: Optional patient ID for patient-scoped operations.
        """
        try:
            logger.debug(f"[SESSION] handle_user_query called for session {self.session_id}")
            logger.debug(f"[SESSION] Query length: {len(query)} chars, first 100 chars: {query[:100]}")

            # Generate a unique request ID for cross-thread source/debug propagation
            request_id = _uuid.uuid4().hex
            set_request_id(request_id)
            logger.debug(f"[SESSION] Request ID: {request_id}")
    

            if not self.conversation:
                m = f"No conversation found for session {self.session_id} with conversation ID {self.conversation_id}"
                logger.error(m)
                raise ValueError(m)

            is_first_message = len(self.conversation.messages) == 0 if self.conversation else False
            logger.debug(f"[SESSION] Is first message: {is_first_message}, current message count: {len(self.conversation.messages)}")

            # Deduplication check
            should_append = True
            if self.conversation.messages:
                last_msg = self.conversation.messages[-1]
                logger.debug(f"[SESSION] Last message role: {last_msg.role}")
                if last_msg.role == "user":
                    if last_msg.content == query:
                        # exact same query already in history
                        should_append = False
                        logger.warning(f"[SESSION] Duplicate query detected, skipping append")
                    else:
                        logger.warning("Last user message differs from current query. Possible out-of-order messages or conversation state mismatch.")
                        self.conversation.messages.append(Message(role="system",
                            content="Last conversation message was from user but no agent response was generated. answer previous query also if necessary."
                        ))

            if should_append:
                logger.debug(f"[SESSION] Appending user message to conversation")
                user_message = Message(role="user", content=query)
                self.conversation.messages.append(user_message)
                conv_service.add_message(self.conversation.conversation_id, user_message)
            else:
                logger.debug(f"[SESSION] Skipping message append (duplicate)")

            message_history = self.get_message_history()
            logger.debug(f"[SESSION] Message history length: {len(message_history)} messages")
            message_history = [{"role": "system", "content": system_prompt}] + message_history
            logger.debug(f"[SESSION] System prompt length: {len(system_prompt)} chars")

            # Track execution time for debugging
            start_time = time.time()
            logger.info(f"[SESSION] Starting agent invocation at {start_time}")
            
            # Invoke agent with multi-tool reasoning enabled.
            # The recursion_limit allows the agent to chain multiple tools
            # together. We use `ainvoke` (async) so the agent's I/O does not
            # block the FastAPI event loop while it waits on the LLM or its
            # tools (audit A1). Previously this called the synchronous
            # `invoke` from inside `async def`, freezing the entire process
            # for every concurrent request.
            logger.info(f"[SESSION] Invoking agent (async) with recursion_limit=50")
            logger.debug(f"[SESSION] Agent type: {type(self.agent)}")

            result = await self.agent.ainvoke(
                {"messages": message_history}, # type: ignore
                config={"recursion_limit": 50},
            )
            
            execution_time_ms = (time.time() - start_time) * 1000
            logger.info(f"[SESSION] Agent invocation completed in {execution_time_ms:.2f}ms")
            logger.debug(f"[SESSION] Result keys: {result.keys() if isinstance(result, dict) else 'not a dict'}")
            
            agent_response = AgentResponse.from_agent_result(
                result,
                conversation_id=self.conversation_id,
                request_id=request_id,
            )
            # An empty answer is a failure, not a reply: never persist it.
            if not any((m.content or "").strip() for m in agent_response.messages):
                raise EmptyAnswerError()
            logger.debug(f"[SESSION] AgentResponse created with {len(agent_response.messages)} messages")
            logger.debug(f"[SESSION] Tools used: {agent_response.tool_responses}")
            logger.debug(f"[SESSION] Sources count: {len(agent_response.agent_sources)}")
            
            # Add execution timing to debug info
            if agent_response.debug:
                agent_response.debug["execution_time_ms"] = execution_time_ms
            else:
                agent_response.debug = {"execution_time_ms": execution_time_ms}
            
            logger.debug(f"[SESSION] Extending conversation with {len(agent_response.messages)} messages")
            self.conversation.messages.extend(agent_response.messages)
            s, count = conv_service.add_messages(self.conversation.conversation_id, agent_response.messages)
            if not s:
                m = f"Failed to save agent response messages to conversation {self.conversation_id}"
                logger.error(m)
                raise ValueError(m)

            logger.info(f"[SESSION] Saved {len(agent_response.messages)} messages, total count: {count}")
            agent_response.total_message_count = count

            # Note: Title generation is now handled by the frontend calling /api/session/generate-title
            # This avoids race conditions from multiple concurrent title generation calls

            logger.info(f"[SESSION] Query processing completed successfully")
            llm_status.record_success()
            return agent_response

        except Exception as e:
            logger.error(f"[SESSION] Error processing query: {str(e)}", exc_info=True)
            code = classify_exception(e).code
            if code in LLM_ERROR_CODES or code == "empty_response":
                llm_status.record_failure(code)
            raise e


    async def handle_user_query_streamed(
        self,
        query: str,
        system_prompt: str = SYSTEM_PROMPT,
        current_user: UserBase | None = None,
        request_id: str | None = None,
    ):
        """
        Process a user query through the agent with streaming support.

        Yields dict events: ``content``, ``tool_start``, ``tool_end``,
        ``sources`` (sources collected so far, sent after each tool) and exactly
        one terminal event:

        - ``done``  — the answer is non-empty and has been persisted;
        - ``error`` — safe ``code``/``message``/``retryable`` (see
          stream_errors). Nothing is persisted for the assistant turn, so a
          partial or empty answer is never stored as a reply.
        """
        request_id = request_id or _uuid.uuid4().hex
        try:
            logger.debug(f"[SESSION STREAM] handle_user_query_streamed called for session {self.session_id}")
            logger.debug(f"[SESSION STREAM] Query length: {len(query)} chars")

            # Unique request ID for cross-thread source/debug propagation
            set_request_id(request_id)
            logger.debug(f"[SESSION STREAM] Request ID: {request_id}")

            if not self.conversation:
                m = f"No conversation found for session {self.session_id} with conversation ID {self.conversation_id}"
                logger.error(m)
                raise ValueError(m)

            is_first_message = len(self.conversation.messages) == 0 if self.conversation else False
            logger.debug(f"[SESSION STREAM] Is first message: {is_first_message}, current message count: {len(self.conversation.messages)}")

            # Deduplication check
            should_append = True
            if self.conversation.messages:
                last_msg = self.conversation.messages[-1]
                if last_msg.role == "user" and last_msg.content == query:
                    should_append = False
                    logger.warning(f"[SESSION STREAM] Duplicate query detected, skipping append")

            user_saved = True
            if should_append:
                logger.debug(f"[SESSION STREAM] Appending user message to conversation")
                user_message = Message(role="user", content=query)
                self.conversation.messages.append(user_message)
                user_saved, _ = conv_service.add_message(self.conversation.conversation_id, user_message)
                if not user_saved:
                    logger.error(f"[SESSION STREAM] Could not persist user message (request {request_id})")

            message_history = self.get_message_history()
            logger.debug(f"[SESSION STREAM] Message history length: {len(message_history)} messages")
            message_history = [{"role": "system", "content": system_prompt}] + message_history

            # Track execution time
            start_time = time.time()
            logger.info(f"[SESSION STREAM] Starting agent streaming invocation")
            
            # Track tool executions. Calls are keyed by run_id: the model may
            # issue several tool calls in parallel, so "the current tool" is
            # ambiguous (the previous single-slot tracker lost the start time
            # and then crashed formatting None as a float).
            tool_executions = []
            running_tools: dict = {}
            sources_sent = 0  # number of sources already forwarded to the client

            # Stream from agent. `full_response` is everything streamed (shown
            # live); `answer_text` is the text of the LAST model call only.
            # Text a model emits next to a tool call ("Let me check DrugBank")
            # is not an answer, so the empty-answer check, the persisted
            # message and the citation check use `answer_text`.
            full_response = ""
            answer_text = ""
            llm_calls: list[dict] = []  # provider-reported usage per model call
            async for event in self.agent.langchain_agent.astream_events(
                {"messages": message_history},
                config={"recursion_limit": 50},
                version="v2"
            ):
                kind = event.get("event")

                if kind == "on_chat_model_start":
                    answer_text = ""

                elif kind == "on_chat_model_end":
                    usage = _usage_of(event.get("data", {}).get("output"))
                    if usage:
                        llm_calls.append(usage)

                # Stream token-by-token from the LLM
                elif kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk", {})
                    chunk_text = getattr(chunk, "content", "") or ""
                    if isinstance(chunk_text, list):  # content-block format
                        chunk_text = "".join(
                            b.get("text", "") for b in chunk_text
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                    if isinstance(chunk_text, str) and chunk_text:
                        full_response += chunk_text
                        answer_text += chunk_text
                        yield {"type": "content", "content": chunk_text}

                # Log tool calls
                elif kind == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    tool_input = event.get("data", {}).get("input", {})
                    running_tools[event.get("run_id")] = {
                        "tool_name": tool_name,
                        "tool_args": tool_input,
                        "start_time": time.time(),
                    }
                    logger.debug(f"[SESSION STREAM] Tool started: {tool_name} with args: {tool_input}")
                    yield {
                        "type": "tool_start",
                        "tool_name": tool_name,
                        "tool_args": tool_input,
                    }

                elif kind == "on_tool_end":
                    tool_name = event.get("name", "unknown")
                    tool_output = event.get("data", {}).get("output", "")
                    call = running_tools.pop(event.get("run_id"), {})
                    execution_time_ms = None
                    if call.get("start_time"):
                        execution_time_ms = (time.time() - call["start_time"]) * 1000
                    logger.debug(f"[SESSION STREAM] Tool completed: {tool_name} in {execution_time_ms}ms")

                    # Tool output may be a ToolMessage; its text is in .content
                    output_text = getattr(tool_output, "content", tool_output)
                    output_text = output_text if isinstance(output_text, str) else str(output_text)
                    first_line = output_text.lstrip().split("\n", 1)[0]
                    tool_error = first_line if first_line.startswith("STATUS: ERROR") else None

                    tool_exec = ToolExecution(
                        tool_name=tool_name,
                        tool_args=call.get("tool_args", {}),
                        tool_result=output_text,
                        execution_time_ms=execution_time_ms,
                        error=tool_error,
                    )
                    tool_executions.append(tool_exec)

                    yield {
                        "type": "tool_end",
                        "tool_name": tool_name,
                        "execution_time_ms": execution_time_ms,
                    }

                    # Forward sources registered by this tool so citations in
                    # the streamed text resolve before the answer completes.
                    collected = peek_search_sources(request_id)
                    if len(collected) > sources_sent:
                        yield {"type": "sources", "sources": collected[sources_sent:]}
                        sources_sent = len(collected)

            execution_time_ms = (time.time() - start_time) * 1000
            llm_usage = _usage_summary(llm_calls)
            logger.info(
                f"[SESSION STREAM] Agent streaming completed in {execution_time_ms:.2f}ms; "
                f"LLM calls={llm_usage['calls']} input_tokens={llm_usage['input_tokens']} "
                f"output_tokens={llm_usage['output_tokens']} (request {request_id})"
            )

            # Get sources and tool debug info
            sources = get_last_search_sources(request_id=request_id)
            tool_debug = get_last_tool_debug(request_id=request_id)

            if not answer_text.strip():
                # The final model call produced no answer (e.g. only tool calls,
                # an empty completion, or text only before a tool call).
                # Report it; do not store an empty or preamble-only reply.
                logger.warning(f"[SESSION STREAM] Empty answer (request {request_id}); nothing saved")
                llm_status.record_failure("empty_response")
                yield make_error("empty_response").to_event(request_id)
                return

            citation_check = check_citations(answer_text, sources or [])
            if citation_check["unknown_refs"]:
                logger.warning(
                    f"[SESSION STREAM] Answer cites refs without a source: {citation_check['unknown_refs']} "
                    f"(request {request_id})"
                )

            # Create assistant message with comprehensive tool execution data
            debug_payload = {
                "execution_time_ms": execution_time_ms,
                "citation_check": citation_check,
                "llm_usage": llm_usage,
            }
            if tool_debug:
                debug_payload["tool_debug"] = tool_debug
            assistant_message = Message(
                role="assistant",
                content=answer_text,
                tool_executions=tool_executions,
                sources=sources if sources else [],
                debug=debug_payload,
            )

            # Save to conversation
            self.conversation.messages.append(assistant_message)
            assistant_saved, _count = conv_service.add_message(self.conversation.conversation_id, assistant_message)
            persisted = bool(assistant_saved and user_saved)
            if persisted:
                logger.info(f"[SESSION STREAM] Saved assistant message to conversation")
            else:
                logger.error(f"[SESSION STREAM] Could not persist assistant message (request {request_id})")
            llm_status.record_success()

            # Note: Title generation is now handled by the frontend calling /api/session/generate-title
            # This avoids race conditions from multiple concurrent title generation calls

            yield {
                "type": "done",
                "sources": sources,
                "tool_executions": [t.model_dump() for t in tool_executions],
                "final_content": answer_text,
                "execution_time_ms": execution_time_ms,
                "debug": tool_debug,
                "citation_check": citation_check,
                "llm_usage": llm_usage,
                "persisted": bool(persisted),
                "request_id": request_id,
            }

        except Exception as e:
            err = classify_exception(e)
            logger.error(
                f"[SESSION STREAM] Error processing streamed query (request {request_id}, code {err.code}): {e}",
                exc_info=True,
            )
            if err.code in LLM_ERROR_CODES:
                llm_status.record_failure(err.code)
            # Drop anything collected for this request; the turn failed.
            get_last_search_sources(request_id=request_id)
            get_last_tool_debug(request_id=request_id)
            yield err.to_event(request_id)
        
    async def generate_title(self, current_user: UserBase | None, save: bool = True) -> str:
        """
        Generate a concise title for a conversation based on the most recent
        user + assistant exchange.

        Audit A8: this used to invoke the full medical agent (with its tool
        belt). The LLM occasionally fired a tool call for the title prompt,
        which was wasteful and could even leak partial citation text into the
        title. We now call the plain chat model directly with a tightly
        scoped prompt and no tools.
        """
        if not self.conversation:
            return settings.default_conversation_title

        recent_messages = self.conversation.messages[-2:]  # Last user+assistant pair
        if not recent_messages:
            return settings.default_conversation_title

        content_for_title = "\n".join(
            f"{msg.role}: {msg.content[:400]}" for msg in recent_messages
        )
        
        logger.info(f"[GENERATE TITLE] Content for title generation:\n{content_for_title}")

        user_role = "doctor" if (current_user and current_user.is_doctor) else "user"

        title_prompt = (
            f"Based on the following conversation between a {user_role} and "
            "an AI assistant, generate a concise and descriptive title "
            "(3-5 words) capturing the main topic or question.\n\n"
            "IMPORTANT: Write the title in the SAME LANGUAGE the user is "
            "writing in. If the user writes in Turkish, the title must be "
            "Turkish. If the user writes in English, the title must be "
            "English. Match the language exactly.\n\n"
            "Reply with ONLY the title text, no quotes, no preamble, no explanation.\n\n"
            f"{content_for_title}\n\nTitle:"
        )

        # Build a minimal chat model with no tool belt (so it can't call a
        # tool while we're trying to summarise). Lazy-import to keep this
        # method self-contained and avoid circular imports at module load.
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr

        title_model = ChatOpenAI(
            model=settings.llm_model_id,
            api_key=SecretStr(settings.llm_api_key),
            base_url=settings.llm_base_url,
            temperature=0.0,
            max_completion_tokens=128,  # Increased from 64 to allow longer titles
            streaming=False,
        )

        try:
            response = await title_model.ainvoke([HumanMessage(content=title_prompt)])
            raw = getattr(response, "content", "") or ""
            logger.info(f"[GENERATE TITLE] Raw LLM response: '{raw}'")
            lines = str(raw).strip().strip("\"'`").splitlines()
            generated_title = lines[0][:80] if lines else ""
        except Exception as e:
            logger.warning(f"Title generation failed: {e}")
            return settings.default_conversation_title

        if not generated_title:
            generated_title = settings.default_conversation_title

        logger.info(f"Generated title: {generated_title}")
        if save:
            self.conversation.title = generated_title
            conv_service.update_conversation_title(self.conversation.conversation_id, generated_title)
        return generated_title