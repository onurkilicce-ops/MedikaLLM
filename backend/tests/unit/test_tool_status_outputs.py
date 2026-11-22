"""What the LLM sees from the drug tools for each lookup outcome.

The drug service is replaced at its function boundary (name search and the
interaction / food lookups) so every outcome can be produced on demand:
query error, unknown drug, partially resolved list and successful-empty. The
assertions target the regression that mattered: a failed or partial lookup
must never read like "no documented interaction", and heuristic severity
labels must not appear.
"""
from __future__ import annotations

import pytest

pytest.importorskip("langchain", reason="agent tools import langchain")

from src.agent import tools  # noqa: E402
from src.drugs import service  # noqa: E402
from src.drugs.models import (  # noqa: E402
    CheckDrugInteractionResponse,
    DrugFoodInteraction,
    DrugFoodInteractionResult,
    DrugInteractionDetail,
    DrugSearchResponse,
    DrugSearchResult,
    LookupErrorInfo,
    ResolvedDrugRef,
)

KNOWN = {
    "warfarin": ("DB00682", "Warfarin", 1.0),
    "aspirin": ("DB00945", "Acetylsalicylic acid", 1.0),
    "paracetamol": ("DB00316", "Acetaminophen", 1.0),
    "warfarine": ("DB00682", "Warfarin", 0.62),
}


@pytest.fixture
def fake_search(monkeypatch):
    state = {"fail": set()}

    def search(request):
        q = request.query.lower()
        if q in state["fail"]:
            return DrugSearchResponse(success=False, query=request.query, results=[], count=0)
        if q in KNOWN:
            did, name, sim = KNOWN[q]
            return DrugSearchResponse(
                success=True, query=request.query, count=1,
                results=[DrugSearchResult(drug_id=did, name=name, similarity_score=sim)],
            )
        return DrugSearchResponse(success=True, query=request.query, results=[], count=0)

    monkeypatch.setattr(service, "search_drugs", search)
    tools.set_request_id("req-tools")
    return state


def _record():
    return DrugInteractionDetail(
        drug1_id="DB00682", drug1_name="Warfarin", drug2_id="DB00945", drug2_name="Acetylsalicylic acid",
        description="The risk or severity of bleeding can be increased when Acetylsalicylic acid is combined with Warfarin.",
        source_url="https://go.drugbank.com/drugs/DB00682",
    )


def _interactions(monkeypatch, response):
    monkeypatch.setattr(service, "check_drug_interactions", lambda _req: response)


def _run(names):
    return tools.check_drug_interactions.invoke({"drug_names": names})


def test_query_error_is_reported_as_unknown_not_as_no_interaction(fake_search, monkeypatch):
    _interactions(monkeypatch, CheckDrugInteractionResponse(
        status="error", error=LookupErrorInfo(code="database_error", message="x")))
    out = _run(["Warfarin", "Aspirin"])
    assert out.startswith("STATUS: ERROR")
    assert "UNKNOWN" in out
    assert "No DrugBank interaction record" not in out


def test_name_lookup_failure_is_an_error_not_drug_not_found(fake_search, monkeypatch):
    fake_search["fail"].add("aspirin")
    _interactions(monkeypatch, CheckDrugInteractionResponse(status="no_record"))
    out = _run(["Warfarin", "Aspirin"])
    assert out.startswith("STATUS: ERROR")
    assert 'lookup FAILED' in out and '"Aspirin"' in out


def test_unknown_drug_means_nothing_was_checked(fake_search, monkeypatch):
    called = []
    monkeypatch.setattr(service, "check_drug_interactions", lambda req: called.append(req))
    out = _run(["Warfarin", "Xyzzyl"])
    assert out.startswith("STATUS: UNRESOLVED")
    assert '"Xyzzyl"' in out and "NOT checked" in out
    assert called == []  # no pair could be formed, so no query ran


def test_partially_resolved_list_is_incomplete_and_names_the_gap(fake_search, monkeypatch):
    _interactions(monkeypatch, CheckDrugInteractionResponse(
        status="found", interactions=[_record()], count=1,
        checked_drugs=[ResolvedDrugRef(drug_id="DB00682", name="Warfarin"),
                       ResolvedDrugRef(drug_id="DB00945", name="Acetylsalicylic acid")],
        pairs_checked=1, pairs_total=1))
    out = _run(["Warfarin", "Aspirin", "Xyzzyl"])
    assert out.startswith("STATUS: INCOMPLETE")
    assert "were NOT checked" in out and "Xyzzyl" in out
    assert "bleeding" in out  # the documented record is still reported


def test_successful_empty_result_is_no_record_and_not_safe(fake_search, monkeypatch):
    _interactions(monkeypatch, CheckDrugInteractionResponse(
        status="no_record",
        checked_drugs=[ResolvedDrugRef(drug_id="DB00682", name="Warfarin"),
                       ResolvedDrugRef(drug_id="DB00316", name="Acetaminophen")],
        pairs_checked=1, pairs_total=1))
    out = _run(["Warfarin", "Paracetamol"])
    assert out.startswith("STATUS: NO_RECORD")
    assert "NOT evidence that the combination is safe" in out
    # The negative finding is itself citable.
    sources = tools.peek_search_sources("req-tools")
    assert any("no record" in s["title"] for s in sources)


def test_found_record_has_no_heuristic_severity_label(fake_search, monkeypatch):
    _interactions(monkeypatch, CheckDrugInteractionResponse(
        status="found", interactions=[_record()], count=1,
        checked_drugs=[ResolvedDrugRef(drug_id="DB00682", name="Warfarin"),
                       ResolvedDrugRef(drug_id="DB00945", name="Acetylsalicylic acid")],
        pairs_checked=1, pairs_total=1))
    out = _run(["Warfarin", "Aspirin"])
    assert out.startswith("STATUS: FOUND")
    for label in ("[MAJOR]", "[MODERATE]", "[MINOR]", "🔴", "🟠", "🟡", "✅"):
        assert label not in out
    assert "Severity: not rated" in out
    src = tools.peek_search_sources("req-tools")[-1]
    assert src["url"] == "https://go.drugbank.com/drugs/DB00682"
    assert src["metadata"]["severity"] == "not_rated"


def test_approximate_name_match_is_disclosed(fake_search, monkeypatch):
    _interactions(monkeypatch, CheckDrugInteractionResponse(
        status="no_record",
        checked_drugs=[ResolvedDrugRef(drug_id="DB00682", name="Warfarin"),
                       ResolvedDrugRef(drug_id="DB00316", name="Acetaminophen")],
        pairs_checked=1, pairs_total=1))
    out = _run(["Warfarine", "Paracetamol"])
    assert "APPROXIMATE match (similarity 0.62)" in out


@pytest.mark.parametrize(
    "result, expected",
    [
        (DrugFoodInteractionResult(status="error", error=LookupErrorInfo(code="database_error", message="x")),
         "STATUS: ERROR"),
        (DrugFoodInteractionResult(status="no_record", drug=ResolvedDrugRef(drug_id="DB00682", name="Warfarin"),
                                   source_url="https://go.drugbank.com/drugs/DB00682"),
         "STATUS: NO_RECORD"),
        (DrugFoodInteractionResult(status="found", drug=ResolvedDrugRef(drug_id="DB00682", name="Warfarin"),
                                   interactions=[DrugFoodInteraction(interaction="Avoid alcohol.")], count=1,
                                   source_url="https://go.drugbank.com/drugs/DB00682"),
         "STATUS: FOUND"),
    ],
)
def test_food_tool_distinguishes_outcomes(fake_search, monkeypatch, result, expected):
    monkeypatch.setattr(service, "lookup_drug_food_interactions", lambda _id: result)
    out = tools.check_drug_food_interaction.invoke({"drug_name": "Warfarin", "food_items": ["grapefruit"]})
    assert out.startswith(expected)
    if expected == "STATUS: ERROR":
        assert "no food" not in out.lower()
    if expected == "STATUS: FOUND":
        assert "No record mentions: grapefruit" in out


def test_food_tool_unknown_drug_is_unresolved(fake_search):
    out = tools.check_drug_food_interaction.invoke({"drug_name": "Xyzzyl"})
    assert out.startswith("STATUS: UNRESOLVED")


def test_safe_error_response_hides_exception_text():
    out = tools._safe_error_response("checking things", RuntimeError("postgresql://u:secret@h/db"))
    assert out.startswith("STATUS: ERROR")
    assert "secret" not in out and "postgresql" not in out


def test_coverage_counts_unmatched_inputs(fake_search, monkeypatch):
    _interactions(monkeypatch, CheckDrugInteractionResponse(
        status="found", interactions=[_record()], count=1,
        checked_drugs=[ResolvedDrugRef(drug_id="DB00682", name="Warfarin"),
                       ResolvedDrugRef(drug_id="DB00945", name="Acetylsalicylic acid")],
        pairs_checked=1, pairs_total=1))
    out = _run(["Warfarin", "Aspirin", "Xyzzyl"])
    assert "Pairs checked: 1 of 3 requested." in out


def test_patient_tool_without_patient_context_has_a_status(fake_search):
    tools.set_current_patient_id(None)
    out = tools.analyze_patient_medications.invoke({"additional_drugs": []})
    assert out.startswith("STATUS: UNRESOLVED")


def test_long_record_lists_are_capped_honestly(fake_search, monkeypatch):
    """A 10-drug check can return dozens of records; the model sees at most
    15 of them plus an explicit count, the user still gets every record."""
    records = [
        DrugInteractionDetail(
            drug1_id="DB00682", drug1_name="Warfarin", drug2_id=f"DB9{i:04d}", drug2_name=f"Drug{i}",
            description=f"Record {i} text.", source_url="https://go.drugbank.com/drugs/DB00682",
        )
        for i in range(20)
    ]
    _interactions(monkeypatch, CheckDrugInteractionResponse(
        status="found", interactions=records, count=20,
        checked_drugs=[ResolvedDrugRef(drug_id="DB00682", name="Warfarin"),
                       ResolvedDrugRef(drug_id="DB00945", name="Acetylsalicylic acid")],
        pairs_checked=1, pairs_total=1))
    out = _run(["Warfarin", "Aspirin"])
    assert out.startswith("STATUS: FOUND")
    assert "Record 14 text." in out and "Record 15 text." not in out
    assert "5 more documented record(s) are not shown here" in out
    assert out.count("Severity: not rated") == 1
    sources = tools.peek_search_sources("req-tools")
    assert len([s for s in sources if s.get("tool") == "check_drug_interactions"]) >= 20
    footer = out.rsplit("[Sources:", 1)[1]
    assert footer.count("[") == 15  # only refs the model was shown
