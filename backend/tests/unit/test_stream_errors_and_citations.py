"""Safe error mapping for the chat stream and citation cross-checking.

These run against the real openai / sqlalchemy exception classes, so a
library upgrade that changes the hierarchy breaks the test instead of
silently turning an auth failure into a generic error.
"""
import asyncio

import httpx
import openai
import pytest
from sqlalchemy.exc import OperationalError

from src.agent.citations import check_citations, cited_numbers
from src.session.stream_errors import classify_exception, make_error

_REQ = httpx.Request("POST", "https://llm.invalid/v1/chat/completions")

SECRET_BITS = ["gsk_", "org_", "postgresql://", "password", "Traceback"]


def _status_error(cls, status, body):
    resp = httpx.Response(status, request=_REQ, json=body)
    return cls(message=str(body), response=resp, body=body)


@pytest.mark.parametrize(
    "exc, code, retryable",
    [
        (openai.APITimeoutError(request=_REQ), "llm_timeout", True),
        (openai.APIConnectionError(request=_REQ), "llm_unreachable", True),
        (
            _status_error(openai.AuthenticationError, 401,
                          {"error": {"message": "Invalid API Key gsk_abc", "code": "invalid_api_key"}}),
            "llm_auth",
            False,
        ),
        (
            _status_error(openai.RateLimitError, 429, {"error": {"message": "rate limit org_123"}}),
            "llm_rate_limited",
            True,
        ),
        (
            _status_error(openai.APIStatusError, 413,
                          {"error": {"message": "Request too large for model in organization org_123 (TPM)"}}),
            "llm_request_too_large",
            False,
        ),
        (
            _status_error(openai.BadRequestError, 400, {"error": {"message": "tool_use_failed"}}),
            "llm_bad_request",
            True,
        ),
        (
            _status_error(openai.InternalServerError, 503, {"error": {"message": "upstream"}}),
            "llm_provider_error",
            True,
        ),
        (asyncio.TimeoutError(), "stream_timeout", True),
        (
            OperationalError("SELECT 1", {}, Exception("could not connect to postgresql://u:password@db/x")),
            "database_unavailable",
            True,
        ),
        (RuntimeError("boom at /srv/app/secret.py password=hunter2"), "internal_error", True),
    ],
)
def test_classify_exception_maps_to_safe_codes(exc, code, retryable):
    err = classify_exception(exc)
    assert err.code == code
    assert err.retryable is retryable
    # The user-facing message never echoes exception text.
    for bit in SECRET_BITS + ["hunter2", "tool_use_failed", "upstream"]:
        assert bit not in err.message


def test_error_event_keeps_legacy_error_key_and_request_id():
    event = make_error("llm_timeout").to_event(request_id="req-1")
    assert event["type"] == "error"
    assert event["code"] == "llm_timeout"
    assert event["error"] == event["message"]
    assert event["request_id"] == "req-1"


def test_unknown_code_falls_back_to_internal_error():
    assert make_error("does_not_exist").code == "internal_error"


def test_recursion_limit_is_reported_as_step_limit():
    class GraphRecursionError(Exception):
        pass

    assert classify_exception(GraphRecursionError("Recursion limit of 50 reached")).code == "agent_step_limit"


# ── citations ────────────────────────────────────────────────────────────────

SOURCES = [{"ref": "REF1"}, {"ref": "REF2"}, {"ref": "REF5"}]


def test_cited_numbers_handles_all_citation_forms_in_order():
    text = "A [2]. B [1, 5]. C [REF2]. D 【5】. E [1][2]."
    assert cited_numbers(text) == [2, 1, 5]


def test_check_citations_flags_numbers_without_a_source():
    result = check_citations("Claim [1]. Invented claim [7].", SOURCES)
    assert result["cited_refs"] == [1, 7]
    assert result["unknown_refs"] == [7]
    assert result["uncited_answer_with_sources"] is False


def test_check_citations_flags_answer_that_cites_nothing_despite_sources():
    result = check_citations("Warfarin is fine with aspirin.", SOURCES)
    assert result["unknown_refs"] == []
    assert result["uncited_answer_with_sources"] is True


def test_check_citations_greeting_without_sources_is_clean():
    result = check_citations("Hello! How can I help?", [])
    assert result == {
        "cited_refs": [],
        "unknown_refs": [],
        "available_ref_count": 0,
        "uncited_answer_with_sources": False,
        "uncited_lines": 0,
    }


def test_uncited_lines_flags_advice_added_without_a_citation():
    # Shape of a real gpt-oss-20b answer seen in the live check: the cited
    # record only says the anticoagulant effect may increase; the bleeding /
    # INR advice was added without a source and only a trailing "[1]" line.
    answer = (
        "**Warfarin** and **aspirin** have a documented interaction.\n"
        "**Clinical implication**\n"
        "- Co-administration can raise the risk of bleeding.\n"
        "- Monitoring of INR and clinical vigilance are advised when both are used.\n"
        "[1] DrugBank interaction table."
    )
    result = check_citations(answer, [{"ref": "REF1"}])
    assert result["unknown_refs"] == []
    assert result["uncited_answer_with_sources"] is False
    assert result["uncited_lines"] == 3


def test_uncited_lines_zero_when_every_statement_is_cited():
    answer = (
        "Acetylsalicylic acid may increase the anticoagulant activities of Warfarin [1].\n"
        "### Source\n"
        "Severity is not rated by the source [1]."
    )
    assert check_citations(answer, [{"ref": "REF1"}])["uncited_lines"] == 0
