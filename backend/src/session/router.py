from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio
import json
import time
import uuid

from ..auth.dependencies import get_current_user
from ..auth.models import UserBase
from ..users import service as user_service
from ..conversations import service as conversation_service
from .session import Session
from .session_manager import SessionManager
from ..agent.langchain_agent import build_system_prompt
from ..agent.tools import set_current_user_id, set_current_patient_id
from ..middleware.rate_limiter import limiter, LLM_LIMIT, user_key
from ..config import settings
from ..quota.service import consume_message, get_quota_status
from ..agent import llm_status, provider_limits
from .stream_errors import classify_exception, make_error

from logging import getLogger
logger = getLogger(__name__)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _http_exception_code(exc: HTTPException) -> str:
    """Map the HTTPExceptions raised while preparing a session to error codes."""
    if exc.status_code == 403:
        return "unauthorized_session"
    if exc.status_code == 500 and "agent" in str(exc.detail).lower():
        return "agent_unavailable"
    return "internal_error"

# section: models

class QueryRequest(BaseModel):
    query: str
    session_id: str | None = None
    conversation_id: str
    patient_id: str | None = None


class GenerateTitleRequest(BaseModel):
    conversation_id: str

# section: dependencies and helpers

def _get_or_create_session(request: Request, conversation_id: str, current_user_id: str) -> Session:
    """
    Delegate to SessionManager — get an existing session or create one.
    """
    logger.debug(f"[SESSION MANAGER] _get_or_create_session called for conversation {conversation_id}, user {current_user_id}")
    
    agent = getattr(request.app.state, "medical_agent", None)
    if not agent:
        logger.error("[SESSION MANAGER] Medical agent not found in app state. Cannot create session.")
        raise HTTPException(status_code=500, detail="Agent not available. Cannot create session.")
    
    logger.debug(f"[SESSION MANAGER] Agent found: {type(agent)}")
    
    session: Session = session_manager.get_or_create(conversation_id, agent)
    logger.debug(f"[SESSION MANAGER] Session obtained: {session.session_id}, user_id: {session.user_id}")
    
    # check ownership if session already exists
    if session.user_id != current_user_id:
        logger.warning(f"[SESSION MANAGER] Unauthorized session access attempt: user {current_user_id} trying to access session for user {session.user_id}")
        raise HTTPException(status_code=403, detail="Unauthorized access to session")
    
    logger.debug(f"[SESSION MANAGER] Session ownership verified")
    return session
                                            

# section: router and endpoints

router = APIRouter(prefix="/api/session", tags=["session"])

session_manager = SessionManager(
    max_sessions=settings.max_n_sessions, ttl_seconds=settings.session_ttl_seconds
)


@router.post("/query")
@limiter.limit(LLM_LIMIT, key_func=user_key)
async def endpoint_query(
    request: Request,
    body: QueryRequest,
    current_user: UserBase = Depends(get_current_user),
):
    """
    Process a user query with the agent. Returns full response.
    """
    logger.info(f"[SESSION QUERY] ========== NEW QUERY REQUEST ==========")
    logger.info(f"[SESSION QUERY] User: {current_user.user_id} ({current_user.email})")
    logger.info(f"[SESSION QUERY] Conversation: {body.conversation_id}")
    logger.info(f"[SESSION QUERY] Patient ID: {body.patient_id}")
    logger.info(f"[SESSION QUERY] Query: {body.query[:200]}...")
    logger.debug(f"[SESSION QUERY] Full query: {body.query}")
    logger.debug(f"[SESSION QUERY] Session ID from body: {body.session_id}")

    # Quota guard — premium users bypass, free tier raises 429 when over the
    # daily limit. Increment is atomic at the DB layer so concurrent requests
    # cannot both squeeze through at the boundary.
    quota_result = consume_message(current_user.user_id)
    logger.debug(
        f"[SESSION QUERY] Quota: premium={quota_result.is_premium}, "
        f"used={quota_result.used_today}, remaining={quota_result.remaining}"
    )

    try:
        logger.debug(f"[SESSION QUERY] Getting or creating session")
        session = _get_or_create_session(request=request, conversation_id=body.conversation_id, current_user_id=current_user.user_id)
        logger.info(f"[SESSION QUERY] Session obtained: {session.session_id}")
        
        # Build dynamic system prompt with role context and optional patient data
        user_id = current_user.user_id
        is_doctor = current_user.is_doctor
        logger.debug(f"[SESSION QUERY] User role - is_doctor: {is_doctor}, is_patient: {current_user.is_patient}")
        
        patient = None
        if body.patient_id:
            logger.info(f"[SESSION QUERY] Loading patient {body.patient_id} for context")
            patient = user_service.get_patient_details(
                patient_id=body.patient_id,
                current_user_id=current_user.user_id,
            )
            if patient:
                logger.debug(f"[SESSION QUERY] Patient loaded: {patient.name}, medications: {len(patient.current_medications)}")
            else:
                logger.warning(f"[SESSION QUERY] Patient {body.patient_id} not found or not authorized")
        
        logger.debug(f"[SESSION QUERY] Building dynamic system prompt")
        dynamic_prompt = build_system_prompt(is_doctor=is_doctor, patient=patient)
        logger.debug(f"[SESSION QUERY] System prompt length: {len(dynamic_prompt)} chars")

        # Seed the user-ID context var so tools can perform user-scoped lookups
        set_current_user_id(user_id)
        logger.debug(f"[SESSION QUERY] Set current_user_id context var: {user_id}")

        # Patient context only for a patient this user may access (the
        # authorization check is get_patient_details above). Previously the
        # raw patient_id was seeded even when that check failed, so the
        # patient tools could read another user's patient record.
        set_current_patient_id(patient.patient_id if patient else None)
        if patient:
            logger.debug(f"[SESSION QUERY] Set current_patient_id context var: {patient.patient_id}")
            # Persist patient-conversation link for consultation history
            conversation_service.set_conversation_patient(body.conversation_id, patient.patient_id)
        
        logger.info(f"[SESSION QUERY] Processing query: {body.query[:50]}...")
        query_start_time = time.time()
        
        result = await session.handle_user_query(
            body.query, system_prompt=dynamic_prompt, current_user=current_user
        )
        
        query_duration = (time.time() - query_start_time) * 1000
        logger.info(f"[SESSION QUERY] Query processed in {query_duration:.2f}ms")
        logger.debug(f"[SESSION QUERY] Result success: {result.success}")
        logger.debug(f"[SESSION QUERY] Result messages: {len(result.messages)}")
        logger.debug(f"[SESSION QUERY] Result sources: {len(result.agent_sources)}")
        logger.debug(f"[SESSION QUERY] Result tools used: {[t['tool_name'] for t in result.tool_responses]}")

        if not result.success:
            logger.error(f"[SESSION QUERY] Agent query failed: {result.debug.get('error')}")
            logger.debug(f"[SESSION QUERY] Full debug info: {result.debug}")
            raise HTTPException(status_code=500, detail=make_error("internal_error").message)

        response = {
            "success": True,
            "conversation_id": body.conversation_id,
            **result.model_dump(),
        }
        logger.info(f"[SESSION QUERY] ========== QUERY COMPLETED SUCCESSFULLY ==========")
        return response
        
    except HTTPException as e:
        logger.error(f"[SESSION QUERY] HTTP error during query processing: {e.status_code} - {e.detail}")
        raise e
    except Exception as e:
        err = classify_exception(e)
        logger.error(f"[SESSION QUERY] Failed to process query (code {err.code}): {str(e)}", exc_info=True)
        # Safe message only — the raw exception may contain provider payloads.
        raise HTTPException(status_code=502 if err.code.startswith("llm_") else 500, detail=err.message)


@router.post("/query-stream")
@limiter.limit(LLM_LIMIT, key_func=user_key)
async def endpoint_query_stream(
    request: Request,
    body: QueryRequest,
    current_user: UserBase = Depends(get_current_user),
):
    """
    Process a user query with the agent. Returns SSE streaming response with real-time token streaming.

    Stream contract (each event is one ``data: <json>`` block):
      thinking | content | tool_start | tool_end | sources   (progress)
      status — progress: {code: "provider_rate_limit_wait", retry_after_seconds,
               limit, request_id}; the provider asked the client to wait
               before it retries (per-minute limit); clients may ignore it
      done   — terminal: complete, non-empty, persisted answer
      error  — terminal: {code, message, retryable, request_id}; safe text only
    SSE comment lines (``: keep-alive``) are sent at least every
    ``chat_stream_heartbeat_seconds`` while waiting, and the whole answer is
    bounded by ``chat_stream_timeout_seconds``. Every stream that starts ends
    with exactly one terminal event unless the client disconnects.
    """
    logger.info(f"[SESSION QUERY STREAM] ========== NEW STREAMING QUERY REQUEST ==========")
    logger.info(f"[SESSION QUERY STREAM] User: {current_user.user_id} ({current_user.email})")
    logger.info(f"[SESSION QUERY STREAM] Conversation: {body.conversation_id}")
    logger.info(f"[SESSION QUERY STREAM] Patient ID: {body.patient_id}")
    logger.info(f"[SESSION QUERY STREAM] Query: {body.query[:200]}...")

    # Quota guard runs BEFORE the StreamingResponse is constructed so a 429
    # is delivered as a normal JSON error (not as an SSE chunk). This keeps
    # the frontend's existing `response.ok` check working unchanged.
    quota_result = consume_message(current_user.user_id)
    logger.debug(
        f"[SESSION QUERY STREAM] Quota: premium={quota_result.is_premium}, "
        f"used={quota_result.used_today}, remaining={quota_result.remaining}"
    )

    async def generate():
        request_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue()
        end_marker = object()
        producer: asyncio.Task | None = None
        try:
            logger.debug(f"[SESSION QUERY STREAM] Getting or creating session")
            session = _get_or_create_session(request=request, conversation_id=body.conversation_id, current_user_id=current_user.user_id)
            logger.info(f"[SESSION QUERY STREAM] Session obtained: {session.session_id}")
            
            # Build dynamic system prompt with role context and optional patient data
            user_id = current_user.user_id
            is_doctor = current_user.is_doctor
            logger.debug(f"[SESSION QUERY STREAM] User role - is_doctor: {is_doctor}, is_patient: {current_user.is_patient}")
            
            patient = None
            if body.patient_id:
                logger.info(f"[SESSION QUERY STREAM] Loading patient {body.patient_id} for context")
                patient = user_service.get_patient_details(
                    patient_id=body.patient_id,
                    current_user_id=current_user.user_id,
                )
                if patient:
                    logger.debug(f"[SESSION QUERY STREAM] Patient loaded: {patient.name}, medications: {len(patient.current_medications)}")
                else:
                    logger.warning(f"[SESSION QUERY STREAM] Patient {body.patient_id} not found or not authorized")
            
            logger.debug(f"[SESSION QUERY STREAM] Building dynamic system prompt")
            dynamic_prompt = build_system_prompt(is_doctor=is_doctor, patient=patient)
            logger.debug(f"[SESSION QUERY STREAM] System prompt length: {len(dynamic_prompt)} chars")

            # Seed the user-ID context var so tools can perform user-scoped lookups
            set_current_user_id(user_id)
            logger.debug(f"[SESSION QUERY STREAM] Set current_user_id context var: {user_id}")

            # Patient context only for a patient this user may access (the
            # authorization check is get_patient_details above). Previously the
            # raw patient_id was seeded even when that check failed, so the
            # patient tools could read another user's patient record.
            set_current_patient_id(patient.patient_id if patient else None)
            if patient:
                logger.debug(f"[SESSION QUERY STREAM] Set current_patient_id context var: {patient.patient_id}")
                # Persist patient-conversation link for consultation history
                conversation_service.set_conversation_patient(body.conversation_id, patient.patient_id)
            
            logger.info(f"[SESSION QUERY STREAM] Processing query with streaming (request {request_id})...")

            # Send initial thinking step
            yield _sse({'type': 'thinking', 'step': 'Processing your query...'})

            # The agent runs in its own task and hands events over a queue, so
            # this generator can send heartbeats while a tool or the LLM is
            # busy and can stop the turn when the overall deadline passes.
            # The task copies this context, so the user/patient context vars
            # set above are visible to the tools.
            async def produce():
                # Rate-limit waits happen inside the model call, while the
                # session generator is blocked; the notice goes straight to
                # the queue. Set here, it is inherited by the agent's tasks.
                provider_limits.set_wait_notifier(
                    lambda notice: queue.put_nowait({**notice, "request_id": request_id})
                )
                try:
                    async for event in session.handle_user_query_streamed(
                        body.query,
                        system_prompt=dynamic_prompt,
                        current_user=current_user,
                        request_id=request_id,
                    ):
                        await queue.put(event)
                except Exception as exc:  # session converts its own errors; last resort
                    logger.error(f"[SESSION QUERY STREAM] Producer failed (request {request_id}): {exc}", exc_info=True)
                    await queue.put(classify_exception(exc).to_event(request_id))
                finally:
                    await queue.put(end_marker)

            producer = asyncio.create_task(produce())
            loop = asyncio.get_running_loop()
            deadline = loop.time() + settings.chat_stream_timeout_seconds
            terminal_sent = False

            while not terminal_sent:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    # A completed answer may already be queued: deliver it
                    # rather than reporting a timeout for a saved answer.
                    late_done = None
                    while not queue.empty():
                        queued = queue.get_nowait()
                        if queued is not end_marker and queued.get("type") in ("done", "error"):
                            late_done = queued
                    if late_done is not None:
                        event = late_done
                    else:
                        logger.error(f"[SESSION QUERY STREAM] Overall timeout reached (request {request_id})")
                        llm_status.record_failure("stream_timeout")
                        yield _sse(make_error("stream_timeout").to_event(request_id))
                        terminal_sent = True
                        break
                else:
                    try:
                        event = await asyncio.wait_for(
                            queue.get(),
                            timeout=min(settings.chat_stream_heartbeat_seconds, remaining),
                        )
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue

                if event is end_marker:
                    break
                event_type = event.get("type")

                if event_type == "content":
                    yield _sse(event)

                elif event_type == "tool_start":
                    tool_name = event.get("tool_name", "unknown")
                    tool_args = event.get("tool_args", {})
                    yield _sse({'type': 'thinking', 'step': f'Using {tool_name}...'})
                    yield _sse({'type': 'tool_start', 'tool_name': tool_name, 'tool_args': tool_args})

                elif event_type == "tool_end":
                    tool_name = event.get("tool_name", "unknown")
                    execution_time_ms = event.get("execution_time_ms")
                    logger.debug(f"[SESSION QUERY STREAM] Tool {tool_name} completed in {execution_time_ms}ms")
                    yield _sse({'type': 'tool_end', 'tool_name': tool_name, 'execution_time_ms': execution_time_ms})

                elif event_type == "sources":
                    yield _sse({'type': 'sources', 'sources': event.get('sources', [])})

                elif event_type == "status":
                    yield _sse({
                        'type': 'status',
                        'code': event.get('code'),
                        'retry_after_seconds': event.get('retry_after_seconds'),
                        'limit': event.get('limit'),
                        'request_id': request_id,
                    })

                elif event_type == "done":
                    execution_time = event.get("execution_time_ms", 0) or 0
                    logger.info(f"[SESSION QUERY STREAM] Streaming completed in {execution_time:.2f}ms")
                    yield _sse({
                        'type': 'done',
                        'sources': event.get("sources", []),
                        'tool_executions': event.get("tool_executions", []),
                        'final_content': event.get("final_content", ""),
                        'execution_time_ms': execution_time,
                        'debug': event.get("debug", {}),
                        'citation_check': event.get("citation_check"),
                        'llm_usage': event.get("llm_usage"),
                        'persisted': event.get("persisted", True),
                        'request_id': request_id,
                    })
                    terminal_sent = True

                elif event_type == "error":
                    logger.error(
                        f"[SESSION QUERY STREAM] Stream error (request {request_id}): code={event.get('code')}"
                    )
                    yield _sse(event)
                    terminal_sent = True
                    break

            if not terminal_sent:
                # The producer ended without done/error: never leave the client guessing.
                logger.error(f"[SESSION QUERY STREAM] Stream ended without a terminal event (request {request_id})")
                yield _sse(make_error("internal_error").to_event(request_id))
            else:
                logger.info(f"[SESSION QUERY STREAM] ========== STREAMING QUERY FINISHED (request {request_id}) ==========")

        except HTTPException as e:
            logger.error(f"[SESSION QUERY STREAM] HTTP error during query processing: {e.status_code} - {e.detail}")
            yield _sse(make_error(_http_exception_code(e)).to_event(request_id))
        except Exception as e:
            err = classify_exception(e)
            logger.error(f"[SESSION QUERY STREAM] Failed to process query (request {request_id}, code {err.code}): {e}", exc_info=True)
            yield _sse(err.to_event(request_id))
        finally:
            # Client disconnect, timeout or error: stop the agent so a late
            # answer is not persisted after the user already saw a failure.
            if producer is not None and not producer.done():
                producer.cancel()
                try:
                    await producer
                except BaseException:
                    pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@router.get("/quota")
async def endpoint_quota_status(
    current_user: UserBase = Depends(get_current_user),
):
    """Read-only snapshot of the user's daily quota state. Used by the UI
    to show the remaining-message badge. Does NOT increment the counter."""
    result = get_quota_status(current_user.user_id)
    return {
        "is_premium": result.is_premium,
        "used_today": result.used_today,
        "daily_limit": result.daily_limit,
        "remaining": result.remaining,
    }


@router.post("/generate-title")
async def endpoint_generate_title(
        request: Request,
        body: GenerateTitleRequest,
        current_user: UserBase = Depends(get_current_user),
    ):
    """
    Generate a concise title for a conversation based on last user + agent messages.
    Falls back to DB-loaded messages when the session is no longer in memory.
    """
    logger.info(f"[GENERATE TITLE] Request for conversation {body.conversation_id} from user {current_user.user_id}")
    try:
        session = session_manager.get(conversation_id=body.conversation_id)

        if session:
            # Fast path: session is in memory
            if not session.user_id == current_user.user_id:
                logger.warning(f"Unauthorized title generation attempt: user {current_user.user_id} trying to access session for user {session.user_id}")
                raise HTTPException(status_code=403, detail="Unauthorized access to session")
            logger.info(f"[GENERATE TITLE] Generating title for conversation {body.conversation_id}")
            title = await session.generate_title(current_user)
        else:
            # Fallback: session evicted from TTL cache — load conversation from DB
            logger.info(f"[GENERATE TITLE] Session not in cache, loading from DB for {body.conversation_id}")
            from ..conversations import service as conv_svc
            from langchain_core.messages import HumanMessage
            from langchain_openai import ChatOpenAI
            from pydantic import SecretStr
            from ..config import settings as _settings

            conv = conv_svc.get_conversation(body.conversation_id)
            if not conv:
                raise HTTPException(status_code=404, detail="Conversation not found")
            if conv.user_id != current_user.user_id:
                raise HTTPException(status_code=403, detail="Unauthorized access to conversation")

            recent = conv.messages[-2:]
            if not recent:
                return {"success": True, "title": _settings.default_conversation_title}

            content_for_title = "\n".join(
                f"{m.role}: {m.content[:400]}" for m in recent
            )
            
            logger.info(f"[GENERATE TITLE] Content for title generation:\n{content_for_title}")
            
            user_role = "doctor" if current_user.is_doctor else "user"
            
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
            title_model = ChatOpenAI(
                model=_settings.llm_model_id,
                api_key=SecretStr(_settings.llm_api_key),
                base_url=_settings.llm_base_url,
                temperature=0.0,
                max_completion_tokens=128,  # Increased from 64 to allow longer titles
                streaming=False,
            )
            try:
                resp = await title_model.ainvoke([HumanMessage(content=title_prompt)])
                raw = getattr(resp, "content", "") or ""
                logger.debug(f"[GENERATE TITLE] Raw LLM response: {raw}")
                lines = str(raw).strip().strip("\"'`").splitlines()
                title = lines[0][:80] if lines else ""
            except Exception as e:
                logger.warning(f"[GENERATE TITLE] LLM call failed (DB fallback): {e}")
                title = ""

            if not title:
                title = _settings.default_conversation_title
            conv_svc.update_conversation_title(body.conversation_id, title)

        logger.info(f"[GENERATE TITLE] Generated title: {title}")
        return {"success": True, "title": title}
    except HTTPException as e:
        logger.error(f"HTTP error during title generation: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"Failed to generate title: {str(e)}", exc_info=True)
        # Safe message only (the exception may carry provider payloads).
        raise HTTPException(status_code=500, detail=classify_exception(e).message)
