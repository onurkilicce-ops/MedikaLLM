"""Provider rate limits and the per-request token budget.

Groq's free tier allows 8,000 tokens per minute and rejects single requests
above that (413). These tests pin down the behaviour that keeps chat answers
inside those limits without a network or a real LLM:

- 429 parsing: limit kind and the wait the provider asked for;
- the httpx response hook: records limit headers, never reads a 2xx body,
  announces per-minute waits to the chat stream, stops retries on daily
  quotas (checked against the real OpenAI client and its retry loop);
- error classification: daily quota vs per-minute limit vs our own guard;
- history selection by token budget and the per-call request guard;
- the SSE endpoint relays the wait notice; answers report token usage.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

# CI installs only the web-framework test dependencies; skip, don't error.
openai = pytest.importorskip("openai", reason="drives the real OpenAI client and its retry loop")

pytest.importorskip("langchain", reason="request guard uses langchain middleware")

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402

from src.agent import llm_status, provider_limits, tools  # noqa: E402
from src.agent import token_budget  # noqa: E402
from src.agent.request_guard import RequestGuardMiddleware, drop_history_to_fit  # noqa: E402
from src.agent.token_budget import RequestBudgetExceeded, select_history  # noqa: E402
from src.conversations.models import Conversation, Message  # noqa: E402
from src.session import session as session_mod  # noqa: E402
from src.session.session import Session  # noqa: E402
from src.session.stream_errors import classify_exception  # noqa: E402

_URL = "https://llm.invalid/v1/chat/completions"
_TPM_MSG = (
    "Rate limit reached for model `openai/gpt-oss-20b` in organization `org_x` service tier "
    "`on_demand` on tokens per minute (TPM): Limit 8000, Used 6199, Requested 6264. "
    "Please try again in 33.4725s."
)
_TPD_MSG = (
    "Rate limit reached for model `openai/gpt-oss-20b` in organization `org_x` service tier "
    "`on_demand` on tokens per day (TPD): Limit 200000, Used 199000, Requested 6264. "
    "Please try again in 7m12.5s."
)


def _error_body(message: str) -> bytes:
    return json.dumps({"error": {"message": message, "type": "tokens", "code": "rate_limit_exceeded"}}).encode()


def _completion() -> dict:
    return {
        "id": "c1", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@pytest.fixture(autouse=True)
def _clean_limits(monkeypatch):
    provider_limits.reset()
    # Deterministic estimates: the character-based fallback, whatever state a
    # background tokenizer warm-up in another test left behind.
    monkeypatch.setattr(token_budget, "_encoder_state", "unavailable")
    monkeypatch.setattr(token_budget, "RETRY_LOAD_AFTER_SECONDS", float("inf"))
    yield
    provider_limits.reset()


# ── parsing ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text, seconds",
    [("33.4725s", 33.4725), ("1m2.5s", 62.5), ("2h3m", 7380.0), ("250ms", 0.25), ("", None), (None, None)],
)
def test_parse_duration(text, seconds):
    assert provider_limits.parse_duration(text) == (pytest.approx(seconds) if seconds is not None else None)


@pytest.mark.parametrize(
    "message, kind",
    [
        (_TPM_MSG, "tpm"),
        (_TPD_MSG, "tpd"),
        ("... on requests per minute (RPM): Limit 30 ...", "rpm"),
        ("... on requests per day (RPD): Limit 1000 ...", "rpd"),
        ("something else", None),
    ],
)
def test_classify_limit_message(message, kind):
    assert provider_limits.classify_limit_message(message) == kind


def test_retry_after_prefers_header_then_body():
    assert provider_limits.retry_after_seconds({"retry-after": "34"}, _TPM_MSG) == 34
    assert provider_limits.retry_after_seconds({}, _TPM_MSG) == pytest.approx(33.4725)
    assert provider_limits.retry_after_seconds({}, "no hint") is None


# ── response hook ────────────────────────────────────────────────────────────

async def test_hook_records_headers_without_reading_a_streamed_2xx_body():
    response = httpx.Response(
        200,
        headers={"x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-tokens": "1433",
                 "x-ratelimit-remaining-requests": "999"},
        stream=httpx.ByteStream(b"data: {}\n\n"),
        request=httpx.Request("POST", _URL),
    )
    await provider_limits.on_response(response)
    assert response.is_stream_consumed is False
    snap = provider_limits.snapshot()
    assert snap["tokens_per_minute_limit"] == "8000"
    assert snap["tokens_per_minute_remaining"] == "1433"
    assert snap["requests_per_day_remaining"] == "999"


async def test_per_minute_429_is_announced_to_the_stream_and_tagged():
    notices = []
    provider_limits.set_wait_notifier(notices.append)
    response = httpx.Response(429, headers={"retry-after": "34"}, content=_error_body(_TPM_MSG),
                              request=httpx.Request("POST", _URL))
    await provider_limits.on_response(response)
    assert notices == [{"type": "status", "code": "provider_rate_limit_wait",
                        "retry_after_seconds": 34, "limit": "tpm"}]
    assert response.headers[provider_limits.LIMIT_KIND_HEADER] == "tpm"
    assert "x-should-retry" not in response.headers
    assert provider_limits.snapshot()["last_rejection"]["limit"] == "tpm"


async def test_daily_429_stops_retries_and_is_not_announced_as_a_wait():
    notices = []
    provider_limits.set_wait_notifier(notices.append)
    response = httpx.Response(429, headers={"retry-after": "433"}, content=_error_body(_TPD_MSG),
                              request=httpx.Request("POST", _URL))
    await provider_limits.on_response(response)
    assert notices == []
    assert response.headers["x-should-retry"] == "false"
    assert response.headers[provider_limits.LIMIT_KIND_HEADER] == "tpd"
    assert response.headers[provider_limits.RETRY_AFTER_HEADER] == "433"


async def test_wait_longer_than_the_client_honours_is_not_promised():
    notices = []
    provider_limits.set_wait_notifier(notices.append)
    response = httpx.Response(429, headers={"retry-after": "90"}, content=_error_body(_TPM_MSG),
                              request=httpx.Request("POST", _URL))
    await provider_limits.on_response(response)
    assert notices == []


async def test_hook_never_raises_on_an_odd_429():
    response = httpx.Response(429, content=b"\xff\xfe not json", request=httpx.Request("POST", _URL))
    await provider_limits.on_response(response)  # must not raise


def _client(handler, max_retries=2):
    http_client = openai.DefaultAsyncHttpxClient(
        transport=httpx.MockTransport(handler),
        event_hooks={"response": [provider_limits.on_response]},
    )
    return openai.AsyncOpenAI(api_key="test", base_url="https://llm.invalid/v1",
                              http_client=http_client, max_retries=max_retries)


async def test_real_client_daily_quota_fails_after_one_request_as_llm_daily_quota():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={"retry-after": "433"}, content=_error_body(_TPD_MSG))

    with pytest.raises(openai.RateLimitError) as caught:
        await _client(handler).chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}])
    assert len(requests) == 1  # no pointless retries against a daily limit
    err = classify_exception(caught.value)
    assert err.code == "llm_daily_quota"
    assert err.retryable is False
    event = err.to_event("req-1")
    assert event["retry_after_seconds"] == 433
    assert "org_" not in json.dumps(event)


async def test_real_client_waits_out_a_per_minute_limit_and_announces_it():
    notices = []
    provider_limits.set_wait_notifier(notices.append)
    responses = [
        httpx.Response(429, headers={"retry-after": "0.01"}, content=_error_body(_TPM_MSG)),
        httpx.Response(200, json=_completion()),
    ]

    def handler(_request):
        return responses.pop(0)

    result = await _client(handler).chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}])
    assert result.choices[0].message.content == "ok"
    assert [n["code"] for n in notices] == ["provider_rate_limit_wait"]


def test_untagged_429_stays_a_retryable_rate_limit():
    resp = httpx.Response(429, request=httpx.Request("POST", _URL), json={"error": {"message": "slow down"}})
    err = classify_exception(openai.RateLimitError(message="x", response=resp, body=None))
    assert err.code == "llm_rate_limited"
    assert err.retryable is True
    assert "retry_after_seconds" not in err.to_event()


def test_request_guard_refusal_is_reported_as_request_too_large():
    err = classify_exception(RequestBudgetExceeded(9100, 7000))
    assert err.code == "llm_request_too_large"
    assert "9100" not in err.message


# ── history by token budget ──────────────────────────────────────────────────

def _msg(role, words):
    return {"role": role, "content": " ".join(["word"] * words)}


def test_history_always_keeps_the_current_question():
    current = {"role": "user", "content": "current question"}
    assert select_history([_msg("user", 500), _msg("assistant", 500), current], 0, 40) == [current]
    assert select_history([current], 1000, 40) == [current]


def test_history_keeps_a_contiguous_recent_window_within_budget():
    msgs = [_msg("user", 10), _msg("assistant", 400), _msg("user", 10), _msg("assistant", 60),
            {"role": "user", "content": "now"}]
    kept = select_history(msgs, token_budget=200, max_messages=40)
    # newest earlier pair fits; the 400-word answer does not, so selection stops there
    assert kept == msgs[2:]


def test_history_shortens_the_newest_answer_when_nothing_else_fits():
    long_answer = {"role": "assistant", "content": "x " * 3000}
    kept = select_history([_msg("user", 5), long_answer, {"role": "user", "content": "follow-up?"}],
                          token_budget=300, max_messages=40)
    assert len(kept) == 2
    assert kept[0]["content"].endswith(token_budget.SHORTENED_MARKER)
    assert token_budget.estimate_message_tokens(kept[0]) <= 300


def test_history_respects_the_turn_cap():
    msgs = [_msg("user", 1), _msg("assistant", 1)] * 5 + [{"role": "user", "content": "now"}]
    assert len(select_history(msgs, token_budget=10_000, max_messages=4)) == 4


def test_session_history_uses_the_token_budget(monkeypatch):
    monkeypatch.setattr(session_mod.settings, "chat_history_token_budget", 50)
    s = Session.__new__(Session)
    now = datetime.now().isoformat()
    s.conversation = Conversation(conversation_id="c", user_id="u", created_at=now, updated_at=now)
    s.conversation.messages = [
        Message(role="user", content="old question " * 50),
        Message(role="assistant", content="old answer " * 200),
        Message(role="user", content="short q"),
        Message(role="assistant", content="short a"),
        Message(role="user", content="current"),
    ]
    history = s.get_message_history()
    assert [m["content"] for m in history] == ["short q", "short a", "current"]


# ── request guard middleware ────────────────────────────────────────────────

class _Req(SimpleNamespace):
    def override(self, **kw):
        return _Req(**{**self.__dict__, **kw})


def _tool(name, desc_words=5):
    return {"type": "function", "function": {"name": name, "description": "w " * desc_words,
                                              "parameters": {"type": "object", "properties": {}}}}


def _guard_request(messages, tool_names=("get_drug_info", "analyze_patient_medications")):
    return _Req(messages=messages, tools=[_tool(n) for n in tool_names], system_message=None)


def test_guard_hides_patient_tool_without_patient_context():
    tools.set_current_patient_id(None)
    req = RequestGuardMiddleware(7000)._prepare(_guard_request([HumanMessage("hi")]))
    assert [t["function"]["name"] for t in req.tools] == ["get_drug_info"]
    tools.set_current_patient_id("patient-1")
    try:
        req = RequestGuardMiddleware(7000)._prepare(_guard_request([HumanMessage("hi")]))
        assert [t["function"]["name"] for t in req.tools] == ["get_drug_info", "analyze_patient_medications"]
    finally:
        tools.set_current_patient_id(None)


def test_guard_drops_oldest_history_but_keeps_this_turn():
    system = SystemMessage("rules " * 50)
    old_q, old_a = HumanMessage("old " * 400), AIMessage("answer " * 400)
    current = HumanMessage("current question")
    call = AIMessage("", tool_calls=[{"name": "get_drug_info", "args": {"drug_name": "warfarin"}, "id": "t1"}])
    result = ToolMessage("STATUS: FOUND " + "data " * 300, tool_call_id="t1")
    messages = [system, old_q, old_a, current, call, result]
    kept, total = drop_history_to_fit(messages, fixed_tokens=0, budget_tokens=700)
    assert kept == [system, current, call, result]
    assert total <= 700
    # A looser budget drops only what is needed, oldest first.
    kept, _ = drop_history_to_fit(messages, fixed_tokens=0, budget_tokens=1600)
    assert kept == [system, old_a, current, call, result]


def test_guard_refuses_a_call_that_cannot_fit_before_calling_the_provider():
    called = []
    guard = RequestGuardMiddleware(200)
    req = _guard_request([HumanMessage("q"), ToolMessage("x " * 2000, tool_call_id="t1")])
    with pytest.raises(RequestBudgetExceeded):
        guard.wrap_model_call(req, lambda r: called.append(r))
    assert called == []


async def test_guard_passes_a_fitting_call_through_unchanged():
    guard = RequestGuardMiddleware(7000)
    tools.set_current_patient_id(None)
    seen = []

    async def handler(request):
        seen.append(request)
        return "response"

    msgs = [SystemMessage("rules"), HumanMessage("hello")]
    assert await guard.awrap_model_call(_guard_request(msgs, ("get_drug_info",)), handler) == "response"
    assert seen[0].messages == msgs


def test_guard_shortens_this_turns_largest_tool_result_with_a_marker():
    guard = RequestGuardMiddleware(1000)
    tools.set_current_patient_id(None)
    msgs = [SystemMessage("rules"), HumanMessage("question"),
            AIMessage("", tool_calls=[{"name": "search_pubmed", "args": {"query": "q"}, "id": "t1"}]),
            ToolMessage("STATUS: FOUND\n" + "line of results\n" * 400, tool_call_id="t1")]
    req = guard._prepare(_guard_request(msgs, ("get_drug_info",)))
    shortened = req.messages[-1].content
    assert shortened.startswith("STATUS: FOUND")
    assert "tool output shortened here" in shortened
    assert token_budget.estimate_messages_tokens(req.messages) + token_budget.estimate_tools_tokens(req.tools) <= 1000
    assert msgs[-1].content.count("line of results") == 400  # the agent state itself is untouched


def test_guard_tells_the_model_when_history_was_left_out():
    guard = RequestGuardMiddleware(800)
    tools.set_current_patient_id(None)
    msgs = [SystemMessage("rules"), HumanMessage("old " * 900), AIMessage("answer " * 300), HumanMessage("now?")]
    req = guard._prepare(_guard_request(msgs, ("get_drug_info",)))
    assert "earlier conversation message(s) were left out" in req.messages[0].content
    assert req.messages[-1].content == "now?"
    assert msgs[0].content == "rules"  # only the outgoing request carries the note


def test_fallback_estimate_is_calibrated_and_reload_retries_are_rate_limited(monkeypatch):
    assert token_budget.estimate_text_tokens("x" * 360) == 100
    calls = []
    monkeypatch.setattr(token_budget, "_load_encoder", lambda: calls.append(1))
    monkeypatch.setattr(token_budget, "RETRY_LOAD_AFTER_SECONDS", 600.0)
    monkeypatch.setattr(token_budget, "_encoder_failed_at", time.monotonic())
    token_budget.warm_up(blocking=True)
    assert calls == []  # too soon after a failed load
    monkeypatch.setattr(token_budget, "_encoder_failed_at", time.monotonic() - 601)
    token_budget.warm_up(blocking=True)
    assert calls == [1]


# ── session usage summary and the SSE wait notice ───────────────────────────

class _Chunk:
    def __init__(self, text):
        self.content = text


async def test_answer_reports_provider_token_usage(monkeypatch):
    saved = []
    monkeypatch.setattr(session_mod.conv_service, "add_message",
                        lambda _cid, m: (saved.append(m) or True, len(saved)))
    llm_status.reset()

    def model_end(inp, out):
        return {"event": "on_chat_model_end",
                "data": {"output": SimpleNamespace(usage_metadata={"input_tokens": inp, "output_tokens": out})}}

    async def astream_events(*_a, **_k):
        yield model_end(3100, 60)
        yield {"event": "on_chat_model_start"}
        yield {"event": "on_chat_model_stream", "data": {"chunk": _Chunk("Answer.")}}
        yield model_end(4300, 500)

    s = Session.__new__(Session)
    s.session_id, s.conversation_id, s.user_id = "s", "c", "u"
    s.agent = SimpleNamespace(langchain_agent=SimpleNamespace(astream_events=astream_events))
    now = datetime.now().isoformat()
    s.conversation = Conversation(conversation_id="c", user_id="u", created_at=now, updated_at=now)

    events = [e async for e in s.handle_user_query_streamed("q", system_prompt="sys", request_id="r")]
    done = events[-1]
    assert done["type"] == "done"
    assert done["llm_usage"]["calls"] == 2
    assert done["llm_usage"]["input_tokens"] == 7400
    assert done["llm_usage"]["output_tokens"] == 560
    assistant = [m for m in saved if m.role == "assistant"][0]
    assert assistant.debug["llm_usage"]["calls"] == 2


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from src.auth.dependencies import get_current_user
    from src.main import app
    from src.session import router as router_mod

    monkeypatch.setattr(router_mod, "consume_message", lambda _uid: SimpleNamespace(
        is_premium=True, used_today=0, remaining=99))
    monkeypatch.setattr(router_mod, "set_current_user_id", lambda _uid: None)
    # The endpoint is rate limited per client; tests share one in-memory bucket.
    monkeypatch.setattr(router_mod.limiter, "enabled", False)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        user_id="user-1", email="x@example.invalid", is_doctor=True, is_patient=False)

    def install(fake_stream):
        fake_session = SimpleNamespace(session_id="s", handle_user_query_streamed=fake_stream)
        monkeypatch.setattr(router_mod, "_get_or_create_session", lambda **_kw: fake_session)
        return TestClient(app)

    yield install
    app.dependency_overrides.pop(get_current_user, None)


def test_endpoint_relays_the_rate_limit_wait_notice(client):
    async def waits_then_answers(*_a, **_k):
        # What the response hook does while the model call waits on a 429:
        notifier = provider_limits._wait_notifier.get()
        assert notifier is not None, "router must install a notifier for this answer"
        notifier(provider_limits.wait_notice(12.2, "tpm"))
        yield {"type": "content", "content": "Hi"}
        yield {"type": "done", "final_content": "Hi", "sources": [], "tool_executions": [],
               "execution_time_ms": 1.0, "debug": None, "citation_check": None, "persisted": True}

    with client(waits_then_answers).stream("POST", "/api/session/query-stream",
                                           json={"query": "q", "conversation_id": "c"}) as res:
        assert res.status_code == 200
        raw = "".join(res.iter_text())
    events = [json.loads(line[6:]) for line in raw.split("\n") if line.startswith("data: ")]
    status = [e for e in events if e["type"] == "status"]
    assert len(status) == 1
    assert status[0]["code"] == "provider_rate_limit_wait"
    assert status[0]["retry_after_seconds"] == 13
    assert status[0]["request_id"]
    assert events[-1]["type"] == "done"
    assert events.index(status[0]) < events.index(events[-1])
