"""PubMed tool output stays inside the provider budget, honestly.

Before: every article carried a six-line metrics table, the full abstract and
any open-access full-text sections, and the default was 10 articles — one
search result alone could exceed Groq's 8,000-token request limit. Now each
article is compact; what is left out stays in the article's source entry and
the text says so. The synthesis rules travel with the results.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("langchain", reason="agent tools import langchain")

from src.agent import token_budget, tools  # noqa: E402

LONG_ABSTRACT = ("Background: metformin and lactic acidosis. " * 60).strip()
FULL_TEXT = {"methods": "M " * 2000, "results": "R " * 2000, "discussion": "D " * 2000}


def _article(i: int, relevance: float = 0.9):
    return SimpleNamespace(
        pmid=f"{1000 + i}", pmc_id=None, title=f"Article {i} on metformin", journal="J Clin Test",
        publication_date="2022-01-01", doi=f"10.1/{i}", abstract=LONG_ABSTRACT,
        authors=["A B"], publication_types=["Meta-Analysis"], confidence_score=80,
        confidence_breakdown={"citations": 60, "fwci": 70, "journal_quality": 55, "recency": 90,
                              "evidence_level": 85, "relevance": 88, "raw_data": {}},
        citation_count=12, citation_source="openalex", fwci=1.4, fwci_source="openalex",
        citation_normalized_percentile=0.8, cite_score=5.0, sjr=1.2, snip=1.1, journal_percentile=80.0,
        relevance_score=relevance, open_access=True, subject_areas=[], query_type="general",
        full_text_available=True, full_text_sections=FULL_TEXT,
        get_url=lambda i=i: f"https://pubmed.ncbi.nlm.nih.gov/{1000 + i}/",
        get_doi_url=lambda i=i: f"https://doi.org/10.1/{i}",
    )


@pytest.fixture(autouse=True)
def _request():
    tools.set_request_id("req-pubmed")
    yield
    tools.get_last_search_sources(request_id="req-pubmed")


def test_ten_articles_fit_well_inside_one_request():
    out = tools._build_pubmed_response(["metformin lactic acidosis"], [_article(i) for i in range(12)],
                                       avg_confidence=80.0, max_articles=10, requested=10)
    assert out.count("[Article ") == 10
    # Compact: far below the 8,000-token request limit together with the prompt
    # (~3,000 tokens). Measured with the real tokenizer when it is available.
    token_budget.warm_up(blocking=True)
    if token_budget.estimator_name() != "tiktoken:o200k_base":
        pytest.skip("tiktoken o200k_base encoding not available offline")
    assert token_budget.estimate_text_tokens(out) < 4000
    assert "QUALITY METRICS" not in out
    assert "M M M" not in out  # full-text sections are not inlined


def test_left_out_content_is_announced_and_kept_in_sources():
    out = tools._build_pubmed_response(["q"], [_article(1)], avg_confidence=80.0, max_articles=5)
    assert "abstract shortened; full abstract in source [" in out
    assert "Open-access full text (Europe PMC) is attached to source [" in out
    sources = tools.peek_search_sources("req-pubmed")
    assert sources[-1]["abstract"] == LONG_ABSTRACT
    assert sources[-1]["full_text_sections"] == FULL_TEXT


def test_synthesis_rules_travel_with_the_results():
    out = tools._build_pubmed_response(["q"], [_article(1)], avg_confidence=80.0, max_articles=5)
    head = out.split("[Article ", 1)[0]
    assert "HOW TO USE THESE RESULTS" in head
    for rule in ("LOW RELEVANCE", "side by side", "Near-duplicates", "no more articles than the user asked"):
        assert rule in head


def test_more_articles_than_the_cap_are_reported_not_silently_dropped():
    out = tools._build_pubmed_response(["q"], [_article(i) for i in range(15)], avg_confidence=80.0,
                                       max_articles=10, requested=20)
    assert out.count("[Article ") == 10
    assert "20 articles were requested; at most 10" in out


def test_search_pubmed_caps_and_defaults(monkeypatch):
    seen = {}

    def fake_search(query, max_results, min_confidence):
        seen["max_results"] = max_results
        return SimpleNamespace(articles=[_article(i) for i in range(20)], avg_confidence=80.0,
                               filtered_count=0, search_time_ms=1)

    monkeypatch.setattr(tools.pubmed_service, "search_pubmed", fake_search)
    default_out = tools.search_pubmed.invoke({"query": "metformin lactic acidosis"})
    assert default_out.count("[Article ") == tools._PUBMED_DEFAULT_ARTICLES
    many_out = tools.search_pubmed.invoke({"query": "metformin lactic acidosis", "num_articles": 20})
    assert many_out.count("[Article ") == tools._PUBMED_MAX_ARTICLES
    assert "20 articles were requested" in many_out
