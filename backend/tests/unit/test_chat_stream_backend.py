"""Backend chat stream: terminal events, persistence and the SSE endpoint.

The agent is replaced by a scripted ``astream_events`` generator and the
conversation store by an in-memory recorder, so these tests exercise the real
``Session.handle_user_query_streamed`` and the real ``/api/session/query-stream``
endpoint without a database or LLM.

Guarantees checked:
- a normal answer ends with ``done`` and is persisted;
- an empty answer, a provider failure (also after partial text) and a timeout
  end with a safe ``error`` event and persist NO assistant message;
- parallel tool calls do not crash the stream;
- sources are forwarded while streaming;
- the endpoint always emits exactly one terminal event and heartbeats.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

# CI installs only the web-framework test dependencies; skip, don't error.
openai = pytest.importorskip("openai", reason="exercises the real openai exception classes")

pytest.importorskip("langchain", reason="session module imports the agent stack")

from src.agent import llm_status, tools  # noqa: E402
from src.conversations.models import Conversation, Message  # noqa: E402
from src.session import session as session_mod  # noqa: E402
from src.session.session import Session  # noqa: E402


class _Chunk:
    def __init__(self, text):
        self.content = text


def _stream(*events):
    """Build a fake LangGraph agent whose astream_events yields `events`.

    An event may be a dict (yielded), an Exception (raised) or a callable
    (executed — used to register sources like a tool would).
    """

    async def astream_events(*_args, **_kwargs):
        for ev in events:
            if isinstance(ev, BaseException):
                raise ev
            if callable(ev):
                ev()
                continue
            yield ev

    return SimpleNamespace(langchain_agent=SimpleNamespace(astream_events=astream_events))


def _content(text):
    return {"event": "on_chat_model_stream", "data": {"chunk": _Chunk(text)}}


def _tool_start(name, run_id):
    return {"event": "on_tool_start", "name": name, "run_id": run_id, "data": {"input": {"x": 1}}}


def _tool_end(name, run_id, output="STATUS: FOUND\n..."):
    return {"event": "on_tool_end", "name": name, "run_id": run_id, "data": {"output": output}}


@pytest.fixture
def saved(monkeypatch):
    """Record conversation writes instead of hitting the database."""
    calls: list[Message] = []

    def add_message(_conversation_id, message):
        calls.append(message)
        return True, len(calls)

    monkeypatch.setattr(session_mod.conv_service, "add_message", add_message)
    llm_status.reset()
    return calls


def _session(agent) -> Session:
    s = Session.__new__(Session)
    s.session_id = "sess-1"
    s.conversation_id = "conv-1"
    s.user_id = "user-1"
    s.agent = agent
    now = datetime.now().isoformat()
    s.conversation = Conversation(conversation_id="conv-1", user_id="user-1", created_at=now, updated_at=now)
    return s


async def _collect(session: Session, query="Warfarin + aspirin?"):
    return [ev async for ev in session.handle_user_query_streamed(query, system_prompt="sys", request_id="req-test")]


def _assistant_saves(saved):
    return [m for m in saved if m.role == "assistant"]


async def test_normal_answer_ends_with_done_and_is_persisted(saved):
    def register_source():
        tools._store_sources([{"ref": "REF1", "title": "Interaction record"}], tool_name="check_drug_interactions")

    agent = _stream(
        _tool_start("check_drug_interactions", "r1"),
        register_source,
        _tool_end("check_drug_interactions", "r1"),
        _content("A documented interaction exists [1]."),
    )
    tools.set_request_id("req-test")
    events = await _collect(_session(agent))
    types = [e["type"] for e in events]
    assert types[-1] == "done"
    assert "sources" in types and types.index("sources") < types.index("done")
    done = events[-1]
    assert done["final_content"] == "A documented interaction exists [1]."
    assert done["citation_check"]["unknown_refs"] == []
    assert done["persisted"] is True
    assert len(_assistant_saves(saved)) == 1
    assert llm_status.snapshot()["last_call"] == "succeeded"


async def test_empty_answer_is_an_error_and_not_persisted(saved):
    events = await _collect(_session(_stream(_tool_start("get_drug_info", "r1"), _tool_end("get_drug_info", "r1"))))
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "empty_response"
    assert all(e["type"] != "done" for e in events)
    assert _assistant_saves(saved) == []


async def test_provider_failure_after_partial_text_is_safe_error_without_persisting(saved):
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    failure = openai.AuthenticationError(
        message="Invalid API Key gsk_secret org_123",
        response=httpx.Response(401, request=req),
        body={"error": {"message": "Invalid API Key gsk_secret"}},
    )
    events = await _collect(_session(_stream(_content("Warfarin increases"), failure)))
    err = events[-1]
    assert err["type"] == "error"
    assert err["code"] == "llm_auth"
    assert err["retryable"] is False
    serialized = json.dumps(err)
    assert "gsk_" not in serialized and "org_" not in serialized
    assert _assistant_saves(saved) == []
    assert llm_status.snapshot() == {
        "last_call": "failed",
        "last_call_at": llm_status.snapshot()["last_call_at"],
        "last_error_code": "llm_auth",
    }


async def test_parallel_tool_calls_do_not_crash_the_stream(saved):
    agent = _stream(
        _tool_start("get_drug_info", "a"),
        _tool_start("check_drug_food_interaction", "b"),
        _tool_end("get_drug_info", "a"),
        _tool_end("check_drug_food_interaction", "b"),
        _content("Answer."),
    )
    events = await _collect(_session(agent))
    assert events[-1]["type"] == "done"
    executions = events[-1]["tool_executions"]
    assert {t["tool_name"] for t in executions} == {"get_drug_info", "check_drug_food_interaction"}
    assert all(t["execution_time_ms"] is not None for t in executions)


async def test_tool_error_status_is_recorded_on_the_execution(saved):
    agent = _stream(
        _tool_start("check_drug_interactions", "r1"),
        _tool_end("check_drug_interactions", "r1", output="STATUS: ERROR\nThe lookup FAILED"),
        _content("The interaction check could not be completed."),
    )
    events = await _collect(_session(agent))
    assert events[-1]["tool_executions"][0]["error"].startswith("STATUS: ERROR")


# ── SSE endpoint ─────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from src.auth.dependencies import get_current_user
    from src.main import app
    from src.session import router as router_mod

    monkeypatch.setattr(router_mod, "consume_message", lambda _uid: SimpleNamespace(
        is_premium=True, used_today=0, remaining=99))
    monkeypatch.setattr(router_mod, "set_current_user_id", lambda _uid: None)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        user_id="user-1", email="x@example.invalid", is_doctor=True, is_patient=False)
    holder: dict = {}

    def install(fake_stream, **settings_overrides):
        fake_session = SimpleNamespace(session_id="s", handle_user_query_streamed=fake_stream)
        monkeypatch.setattr(router_mod, "_get_or_create_session", lambda **_kw: fake_session)
        for key, value in settings_overrides.items():
            monkeypatch.setattr(router_mod.settings, key, value)
        holder["client"] = TestClient(app)
        return holder["client"]

    yield install
    app.dependency_overrides.pop(get_current_user, None)


def _post(client):
    with client.stream("POST", "/api/session/query-stream",
                       json={"query": "q", "conversation_id": "c"}) as res:
        assert res.status_code == 200
        return "".join(res.iter_text())


def _events(raw: str):
    return [json.loads(line[6:]) for line in raw.split("\n") if line.startswith("data: ")]


def test_endpoint_relays_done_once(client):
    async def fake(*_a, **_k):
        yield {"type": "content", "content": "Hi"}
        yield {"type": "done", "final_content": "Hi", "sources": [], "tool_executions": [],
               "execution_time_ms": 1.0, "debug": None, "citation_check": None, "persisted": True}

    events = _events(_post(client(fake)))
    terminal = [e for e in events if e["type"] in ("done", "error")]
    assert [e["type"] for e in terminal] == ["done"]
    assert terminal[0]["request_id"]


def test_endpoint_sends_heartbeats_and_times_out_with_error(client):
    async def hang(*_a, **_k):
        yield {"type": "content", "content": "partial"}
        await asyncio.sleep(30)
        yield {"type": "done", "final_content": "never"}

    raw = _post(client(hang, chat_stream_timeout_seconds=0.6, chat_stream_heartbeat_seconds=0.1))
    assert ": keep-alive" in raw
    events = _events(raw)
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "stream_timeout"
    assert all(e["type"] != "done" for e in events)


def test_endpoint_reports_missing_terminal_event(client):
    async def silent_end(*_a, **_k):
        yield {"type": "content", "content": "partial"}

    events = _events(_post(client(silent_end)))
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "internal_error"


def test_endpoint_never_leaks_exception_text(client):
    async def boom(*_a, **_k):
        raise RuntimeError("password=hunter2 at postgresql://u:p@db")
        yield  # pragma: no cover

    raw = _post(client(boom))
    assert "hunter2" not in raw and "postgresql://" not in raw
    assert _events(raw)[-1]["code"] == "internal_error"


# ── review follow-ups ───────────────────────────────────────────────────────

def _model_start():
    return {"event": "on_chat_model_start", "data": {}}


async def test_text_before_a_tool_call_alone_is_not_an_answer(saved):
    agent = _stream(
        _model_start(), _content("Let me check DrugBank for that."),
        _tool_start("check_drug_interactions", "r1"), _tool_end("check_drug_interactions", "r1"),
        _model_start(),  # final model call produces nothing
    )
    events = await _collect(_session(agent))
    assert events[-1]["type"] == "error" and events[-1]["code"] == "empty_response"
    assert _assistant_saves(saved) == []


async def test_saved_answer_is_the_final_model_call_only(saved):
    agent = _stream(
        _model_start(), _content("Let me check DrugBank."),
        _tool_start("check_drug_interactions", "r1"), _tool_end("check_drug_interactions", "r1"),
        _model_start(), _content("A documented record exists [1]."),
    )
    events = await _collect(_session(agent))
    assert events[-1]["final_content"] == "A documented record exists [1]."
    assert _assistant_saves(saved)[0].content == "A documented record exists [1]."


async def test_failed_user_message_save_is_reported_as_not_persisted(monkeypatch, saved):
    calls = []

    def add_message(_cid, message):
        calls.append(message.role)
        return (message.role != "user"), len(calls)

    monkeypatch.setattr(session_mod.conv_service, "add_message", add_message)
    events = await _collect(_session(_stream(_content("Answer."))))
    assert events[-1]["type"] == "done" and events[-1]["persisted"] is False


def test_endpoint_sends_exactly_one_terminal_event_even_if_the_deadline_passes_after_done(client):
    async def done_then_linger(*_a, **_k):
        yield {"type": "done", "final_content": "Hi", "sources": [], "tool_executions": [],
               "execution_time_ms": 1.0, "debug": None, "citation_check": None, "persisted": True}
        await asyncio.sleep(5)

    raw = _post(client(done_then_linger, chat_stream_timeout_seconds=0.3, chat_stream_heartbeat_seconds=0.1))
    terminal = [e["type"] for e in _events(raw) if e["type"] in ("done", "error")]
    assert terminal == ["done"]


def test_unauthorized_patient_id_never_reaches_the_tools(client, monkeypatch):
    from src.session import router as router_mod

    seen = []
    monkeypatch.setattr(router_mod, "set_current_patient_id", lambda pid: seen.append(pid))
    monkeypatch.setattr(router_mod.user_service, "get_patient_details", lambda **_kw: None)
    linked = []
    monkeypatch.setattr(router_mod.conversation_service, "set_conversation_patient",
                        lambda *a: linked.append(a))

    async def answer(*_a, **_k):
        yield {"type": "done", "final_content": "Hi", "sources": [], "tool_executions": [],
               "execution_time_ms": 1.0, "debug": None, "citation_check": None, "persisted": True}

    c = client(answer)
    with c.stream("POST", "/api/session/query-stream",
                  json={"query": "q", "conversation_id": "c", "patient_id": "someone-elses-patient"}) as res:
        "".join(res.iter_text())
    assert seen == [None]
    assert linked == []
