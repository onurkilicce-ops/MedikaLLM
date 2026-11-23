"""Follow-ups from the independent review of the Groq token-budget change.

Pins the paths the review found untested or wrong: a wait is announced only
when the OpenAI client really waits; daily limits by requests (RPD) count as a
daily quota too; the error contract fields; the hook surviving its own bugs;
the agent wiring (guard, hook, provider usage); each safety rule kept as a
whole sentence in the prompt; a realistic patient research turn fitting the
budget even under the fallback estimator; and the honest caps on the
patient-analysis and multi-query paths.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

openai = pytest.importorskip("openai", reason="drives the real OpenAI client")
pytest.importorskip("langchain", reason="agent stack")

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402

from src.agent import langchain_agent, provider_limits, token_budget, tools  # noqa: E402
from src.agent.langchain_agent import build_system_prompt  # noqa: E402
from src.agent.request_guard import RequestGuardMiddleware  # noqa: E402
from src.config import settings  # noqa: E402
from src.drugs import service  # noqa: E402
from src.drugs.models import DrugInteractionDetail, DrugSearchResponse, DrugSearchResult  # noqa: E402
from src.session.stream_errors import LLM_ERROR_CODES, classify_exception  # noqa: E402
from src.users.models import PatientBase  # noqa: E402

URL = "https://llm.invalid/v1/chat/completions"
TPM = ("Rate limit reached for model `m` in organization `org_x` on tokens per minute (TPM): "
       "Limit 8000, Used 6199, Requested 6264. Please try again in 20s.")
RPD = ("Rate limit reached for model `m` in organization `org_x` on requests per day (RPD): "
       "Limit 1000, Used 1000, Requested 1. Please try again in 2m10s.")


def _body(message: str) -> bytes:
    return json.dumps({"error": {"message": message, "code": "rate_limit_exceeded"}}).encode()


def _request(headers=None) -> httpx.Request:
    return httpx.Request("POST", URL, headers=headers or {})


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    provider_limits.reset()
    monkeypatch.setattr(token_budget, "_encoder_state", "unavailable")
    monkeypatch.setattr(token_budget, "RETRY_LOAD_AFTER_SECONDS", float("inf"))
    yield
    provider_limits.reset()
    tools.set_current_patient_id(None)


# ── wait notices only for waits the client really performs ──────────────────

async def test_no_wait_is_announced_on_the_last_attempt():
    notices = []
    provider_limits.set_wait_notifier(notices.append)
    last = str(settings.llm_max_retries)
    response = httpx.Response(429, headers={"retry-after": "20"}, content=_body(TPM),
                              request=_request({"x-stainless-retry-count": last}))
    await provider_limits.on_response(response)
    assert notices == []


async def test_a_body_only_wait_is_handed_to_the_client_and_announced():
    notices = []
    provider_limits.set_wait_notifier(notices.append)
    response = httpx.Response(429, content=_body(TPM), request=_request())
    await provider_limits.on_response(response)
    assert response.headers["retry-after-ms"] == "20000"
    assert [n["retry_after_seconds"] for n in notices] == [20]


async def test_a_requests_per_day_limit_is_a_daily_quota_too():
    response = httpx.Response(429, content=_body(RPD), request=_request())
    await provider_limits.on_response(response)
    assert response.headers["x-should-retry"] == "false"
    assert response.headers[provider_limits.LIMIT_KIND_HEADER] == "rpd"
    err = classify_exception(openai.RateLimitError(message="x", response=response, body=None))
    assert err.code == "llm_daily_quota" and err.retryable is False
    assert err.retry_after_seconds == 130


async def test_the_hook_survives_its_own_failures(monkeypatch):
    def broken(_text):
        raise RuntimeError("parser bug")

    monkeypatch.setattr(provider_limits, "classify_limit_message", broken)
    response = httpx.Response(429, headers={"retry-after": "5"}, content=_body(TPM), request=_request())
    await provider_limits.on_response(response)  # must not raise into the model call


async def test_exhausted_per_minute_retries_end_in_a_retryable_error_with_the_wait():
    calls, notices = [], []
    provider_limits.set_wait_notifier(notices.append)

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": "0.01"}, content=_body(TPM))

    client = openai.AsyncOpenAI(
        api_key="test", base_url="https://llm.invalid/v1", max_retries=settings.llm_max_retries,
        http_client=openai.DefaultAsyncHttpxClient(
            transport=httpx.MockTransport(handler),
            event_hooks={"response": [provider_limits.on_response]},
        ),
    )
    with pytest.raises(openai.RateLimitError) as caught:
        await client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}])
    assert len(calls) == settings.llm_max_retries + 1
    assert len(notices) == settings.llm_max_retries  # nothing promised for the final attempt
    err = classify_exception(caught.value)
    assert err.code == "llm_rate_limited" and err.retryable is True
    assert err.to_event()["retry_after_seconds"] == 1
    assert "llm_daily_quota" in LLM_ERROR_CODES


# ── agent wiring ─────────────────────────────────────────────────────────────

def test_agent_wiring_keeps_the_guard_the_hook_and_provider_usage(monkeypatch):
    captured = {}

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return "agent"

    monkeypatch.setattr(langchain_agent, "create_agent", fake_create_agent)
    monkeypatch.setattr(langchain_agent.token_budget, "warm_up", lambda *a, **k: None)
    assert langchain_agent.create_medical_agent() == "agent"
    guards = [m for m in captured["middleware"] if isinstance(m, RequestGuardMiddleware)]
    assert guards and guards[0].budget_tokens == settings.llm_request_token_budget
    model = captured["model"]
    # Groq reports usage on its last chunk anyway; requesting include_usage
    # makes it send a second copy that LangChain adds up (doubled usage).
    assert model.stream_usage is False
    assert provider_limits.on_response in model.http_async_client.event_hooks["response"]


# ── prompt contract: whole sentences, not fragments ─────────────────────────

@pytest.mark.parametrize("sentence", [
    "NEVER answer from training knowledge, not even with a \"general knowledge\" disclaimer.",
    'NO_RECORD is never "safe".',
    "ERROR means the result is UNKNOWN; never present it as a negative finding.",
    "INCOMPLETE: name the unchecked inputs.",
    "Disclose APPROXIMATE name matches.",
    "NEVER assign MAJOR/MODERATE/MINOR",
    'NEVER use ✅ or "safe" for a missing record.',
    "NEVER call a candidate safe, suitable or equivalent.",
    "Each [N] must be the source that states that specific claim",
    "NEVER give specific dosing unless it comes from the database.",
])
def test_each_safety_rule_stays_a_whole_sentence(sentence):
    assert sentence in langchain_agent.SYSTEM_PROMPT


# ── realistic turns fit even under the fallback estimator ──────────────────

def _article(i: int):
    return SimpleNamespace(
        pmid=str(1000 + i), pmc_id=None, title=f"Metformin and lactic acidosis study {i}",
        journal="Diabetes Care", publication_date="2021-06-01", doi=f"10.1/{i}",
        abstract="Background: metformin-associated lactic acidosis in renal impairment. " * 30,
        authors=["A"], publication_types=["Cohort Study"], confidence_score=74,
        confidence_breakdown={"citations": 60, "fwci": 70, "journal_quality": 80, "recency": 70,
                              "evidence_level": 60, "relevance": 85, "raw_data": {}},
        citation_count=40, citation_source="openalex", fwci=1.3, fwci_source="openalex",
        citation_normalized_percentile=0.8, cite_score=10.0, sjr=3.1, snip=2.0, journal_percentile=95.0,
        relevance_score=0.85, open_access=True, subject_areas=[], query_type="general",
        full_text_available=False, full_text_sections=None,
        get_url=lambda: "https://pubmed.ncbi.nlm.nih.gov/1/", get_doi_url=lambda: "https://doi.org/10.1/1",
    )


class _Req(SimpleNamespace):
    def override(self, **kw):
        return _Req(**{**self.__dict__, **kw})


def test_a_patient_research_turn_fits_under_the_fallback_estimator():
    tools.set_request_id("req-fit")
    tools.set_current_patient_id("p")
    patient = PatientBase(patient_id="p", user_id="u", name="Synthetic Patient",
                          current_medications=["Warfarin", "Metformin", "Lisinopril"], allergies=["Penicillin"])
    records = [
        DrugInteractionDetail(drug1_id=f"DB1{i:03d}", drug1_name=f"Drug{i}", drug2_id="DB00331",
                              drug2_name="Metformin", description="The risk can be increased. " * 3,
                              source_url="https://go.drugbank.com/drugs/DB00331")
        for i in range(15)
    ]
    lines, _ = tools._interaction_record_lines(records, "analyze_patient_medications", lambda _it: {})
    pubmed = tools._build_pubmed_response(["metformin lactic acidosis"], [_article(i) for i in range(5)],
                                          avg_confidence=74.0, max_articles=5)
    messages = [
        SystemMessage(build_system_prompt(is_doctor=True, patient=patient)),
        HumanMessage("Metformin ve laktik asidoz hakkinda 5 makale bulur musun?"),
        AIMessage("", tool_calls=[
            {"name": "analyze_patient_medications", "args": {"additional_drugs": ["Metformin"]}, "id": "a"},
            {"name": "search_pubmed", "args": {"query": "metformin lactic acidosis"}, "id": "b"},
        ]),
        ToolMessage("STATUS: FOUND\n" + "\n".join(lines), tool_call_id="a"),
        ToolMessage(pubmed, tool_call_id="b"),
    ]
    try:
        out = RequestGuardMiddleware(settings.llm_request_token_budget)._prepare(
            _Req(messages=messages, tools=list(tools.ALL_TOOLS), system_message=None))
    finally:
        tools.get_last_search_sources(request_id="req-fit")
    assert all("tool output shortened here" not in str(m.content) for m in out.messages)


# ── honest caps on the other call sites ─────────────────────────────────────

def test_patient_analysis_lists_every_record_and_the_asked_drug_first(monkeypatch):
    def search(request):
        return DrugSearchResponse(success=True, query=request.query, count=1, results=[
            DrugSearchResult(drug_id="DB00945", name="Acetylsalicylic acid", similarity_score=1.0)])

    def rec(a_id, a, b_id, b):
        return DrugInteractionDetail(drug1_id=a_id, drug1_name=a, drug2_id=b_id, drug2_name=b,
                                     description=f"{a} with {b}.", source_url="https://go.drugbank.com/drugs/x")

    records = [rec(f"DB1{i:03d}", f"Old{i}", f"DB2{i:03d}", f"Old{i}b") for i in range(20)]
    records.append(rec("DB1000", "Old0", "DB00945", "Acetylsalicylic acid"))
    response = SimpleNamespace(
        status="found", patient_id="p", medication_matches=[], unresolved_medications=[],
        not_checked_over_limit=[], current_drugs=[], error=None, count=len(records), pairs_checked=40,
        interactions=records, alternatives_note="No automatic alternatives.",
    )
    monkeypatch.setattr(service, "search_drugs", search)
    monkeypatch.setattr(service, "analyze_patient", lambda _request: response)
    tools.set_request_id("req-pa")
    tools.set_current_patient_id("p")
    out = tools.analyze_patient_medications.invoke({"additional_drugs": ["Aspirin"]})
    tools.get_last_search_sources(request_id="req-pa")
    assert "1. **Old0** + **Acetylsalicylic acid**" in out
    assert "Records 16-21 are listed without their DrugBank text" in out
    assert "**Old19** + **Old19b**" in out


def test_multi_query_reports_the_cap_and_search_pubmed_keeps_its_fetch_sizes(monkeypatch):
    monkeypatch.setattr(tools.pubmed_service, "search_pubmed_multi",
                        lambda queries, max_per_query, min_confidence: SimpleNamespace(
                            articles=[_article(i) for i in range(15)], avg_confidence=74.0))
    tools.set_request_id("req-mq")
    out = tools.search_pubmed_multi.invoke({"queries": ["metformin lactic acidosis", "metformin renal"],
                                            "num_articles": 20})
    assert out.count("[Article ") == 10
    assert "NOTE: 20 articles were requested; one answer can show at most 10" in out

    fetched = []

    def single(query, max_results, min_confidence):
        fetched.append(max_results)
        return SimpleNamespace(articles=[_article(i) for i in range(20)], avg_confidence=74.0,
                               filtered_count=0, search_time_ms=1)

    monkeypatch.setattr(tools.pubmed_service, "search_pubmed", single)
    tools.search_pubmed.invoke({"query": "metformin lactic acidosis"})
    tools.search_pubmed.invoke({"query": "metformin lactic acidosis", "num_articles": 20})
    tools.get_last_search_sources(request_id="req-mq")
    assert fetched == [10, 15]  # small over-fetch for the relevance gate, never 20+
