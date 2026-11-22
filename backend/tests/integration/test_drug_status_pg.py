"""Drug lookup statuses against a real PostgreSQL with a SYNTHETIC dataset.

Runs only when MEDICALLM_SYNTHETIC_PG_URL points at a database whose name
ends in "_synth" (it is dropped and re-seeded). Example:

    MEDICALLM_SYNTHETIC_PG_URL=postgresql://synth@127.0.0.1:55432/medicallm_synth

Covers, with real SQL (trigram name search, pair lookups, category joins):
found / no_record / unresolved / incomplete / error for drug-drug and food
lookups, the alternative-candidate filter, the REST endpoint and the agent
tool text. No application data is touched.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

URL = os.getenv("MEDICALLM_SYNTHETIC_PG_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="MEDICALLM_SYNTHETIC_PG_URL not set")

W, A, P, C, ACENO, BIVAL = "DB00682", "DB00945", "DB00316", "DB01211", "DB01418", "DB00006"


@pytest.fixture(scope="module")
def synthetic_db():
    from src.db import sql_client

    from .synthetic_data import reset_and_seed

    reset_and_seed(URL)
    engine = create_engine(URL)
    saved = (sql_client._engine, sql_client._SessionLocal)
    sql_client._engine = engine
    sql_client._SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    yield engine
    sql_client._engine, sql_client._SessionLocal = saved
    engine.dispose()


@pytest.fixture
def broken_db(monkeypatch):
    """A session factory pointing at a closed port: a real connection error."""
    from src.db import sql_client

    engine = create_engine("postgresql://synth@127.0.0.1:1/none_synth", connect_args={"connect_timeout": 2})
    monkeypatch.setattr(sql_client, "_SessionLocal", sessionmaker(bind=engine))
    yield
    engine.dispose()


def _check(ids):
    from src.drugs import service
    from src.drugs.models import CheckDrugInteractionRequest

    return service.check_drug_interactions(CheckDrugInteractionRequest(drug_ids=ids))


def test_found_record_has_no_severity_and_a_source(synthetic_db):
    res = _check([W, A])
    assert res.status == "found"
    assert res.count == 1 and res.pairs_checked == 1 and res.pairs_total == 1
    rec = res.interactions[0]
    assert rec.severity is None and rec.severity_status == "not_rated"
    assert rec.source_url == f"https://go.drugbank.com/drugs/{W}"
    assert res.overall_severity is None


def test_record_stored_on_the_other_drug_is_found_with_its_owner_url(synthetic_db):
    res = _check([W, C])
    assert res.status == "found"
    assert res.interactions[0].source_url == f"https://go.drugbank.com/drugs/{C}"


def test_negated_wording_is_not_turned_into_a_contraindication(synthetic_db):
    res = _check([P, C])
    assert res.status == "found"
    assert res.interactions[0].severity is None  # old scorer: 1.0 "Contraindicated"


def test_checked_pair_without_record_is_no_record(synthetic_db):
    res = _check([W, P])
    assert res.status == "no_record" and res.count == 0 and res.pairs_checked == 1


def test_unknown_ids_are_unresolved_not_empty_success(synthetic_db):
    res = _check(["DB99998", "DB99999"])
    assert res.status == "unresolved"
    assert res.unresolved_drug_ids == ["DB99998", "DB99999"]
    assert res.pairs_checked == 0


def test_partially_resolved_list_is_incomplete_and_lists_the_gap(synthetic_db):
    res = _check([W, A, "DB99999"])
    assert res.status == "incomplete"
    assert res.unresolved_drug_ids == ["DB99999"]
    assert res.count == 1 and res.pairs_checked == 1 and res.pairs_total == 3


def test_database_failure_is_error(broken_db):
    res = _check([W, A])
    assert res.status == "error" and res.error.code == "database_error"


def test_food_lookup_statuses(synthetic_db):
    from src.drugs import service

    assert service.lookup_drug_food_interactions(W).status == "found"
    assert service.lookup_drug_food_interactions(P).status == "no_record"
    assert service.lookup_drug_food_interactions("DB99999").status == "unresolved"


def test_alternatives_exclude_candidates_with_any_interaction_record(synthetic_db):
    from src.drugs import service

    res = service.find_alternative_candidates([A], W)
    names = [c.new_drug_name for c in res.candidates]
    assert "Acenocoumarol" not in names  # has a record with aspirin
    assert "Bivalirudin" in names
    assert res.excluded_with_interaction_record == 1
    assert all("Unverified" in c.reason for c in res.candidates)

    partial = service.find_alternative_candidates([A, "DB99999"], W)
    assert partial.status == "incomplete" and partial.unresolved_current_drug_ids == ["DB99999"]


def test_rest_endpoint_exposes_status(synthetic_db):
    from fastapi.testclient import TestClient

    from src.auth.dependencies import get_current_user_id
    from src.main import app

    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    try:
        client = TestClient(app)
        body = client.post("/api/drugs/interactions", json={"drug_ids": [W, A, "DB99999"]}).json()
        assert body["status"] == "incomplete"
        assert body["unresolved_drug_ids"] == ["DB99999"]
        assert body["interactions"][0]["severity_status"] == "not_rated"
        pair = client.get(f"/api/drugs/interaction/{W}/{P}").json()
        assert pair["status"] == "no_record"
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)


def test_agent_tool_text_with_real_name_resolution(synthetic_db):
    pytest.importorskip("langchain")
    from src.agent import tools

    tools.set_request_id("req-pg")
    out = tools.check_drug_interactions.invoke({"drug_names": ["Coumadin", "Aspirin", "Xyzzyl"]})
    assert out.startswith("STATUS: INCOMPLETE")
    assert '"Coumadin" → Warfarin (DB00682) [exact name/brand/synonym match]' in out
    assert '"Xyzzyl"' in out and "bleeding" in out
    out2 = tools.check_drug_interactions.invoke({"drug_names": ["Warfarin", "Paracetamol"]})
    assert out2.startswith("STATUS: NO_RECORD")


# ── review follow-ups ───────────────────────────────────────────────────────

def test_same_drug_twice_is_a_duplicate_risk_not_unresolved(synthetic_db):
    from src.drugs import service

    res = service.check_overdose_risk([P, P])
    assert res.status == "found" and res.has_risk
    assert res.risks[0].drug1_id == res.risks[0].drug2_id == P


def test_tools_report_two_names_of_one_drug_as_the_same_drug(synthetic_db):
    pytest.importorskip("langchain")
    from src.agent import tools

    tools.set_request_id("req-dup")
    out = tools.check_drug_interactions.invoke({"drug_names": ["Paracetamol", "Acetaminophen"]})
    assert out.startswith("STATUS: FOUND")
    assert "SAME DRUG" in out and "duplicate therapy" in out
    over = tools.check_for_overdose_interaction.invoke({"drug_names": ["Paracetamol", "Acetaminophen"]})
    assert over.startswith("STATUS: FOUND")
    assert "CRITICAL" not in over and "🔴" not in over


def test_combination_product_name_is_partial_not_exact(synthetic_db):
    pytest.importorskip("langchain")
    from src.agent import tools
    from src.drugs import service
    from src.drugs.models import DrugSearchRequest

    hit = service.search_drugs(DrugSearchRequest(query="Synthocomb Forte", limit=1)).results[0]
    assert (hit.drug_id, hit.match_type) == (P, "mixture")
    tools.set_request_id("req-mix")
    out = tools.check_drug_interactions.invoke({"drug_names": ["Synthocomb Forte", "Clarithromycin"]})
    assert out.startswith("STATUS: INCOMPLETE")
    assert "COMBINATION-PRODUCT" in out


def test_analyze_patient_discloses_matches_and_gaps(synthetic_db):
    from src.drugs import service
    from src.drugs.models import AnalyzePatientRequest

    from .synthetic_data import PATIENT_ID

    res = service.analyze_patient(AnalyzePatientRequest(patient_id=PATIENT_ID))
    assert res.status == "incomplete"
    assert res.unresolved_medications == ["Xyzzyl"]
    kinds = {m.input: m.match_type for m in res.medication_matches}
    assert kinds["Coumadin"] == "brand" and kinds["Synthocomb Forte"] == "mixture"
    assert res.count == 1  # warfarin–aspirin synthetic record
    assert res.safe_alternatives == []


def test_alternatives_never_propose_a_current_medication(synthetic_db):
    from src.drugs import service

    res = service.find_alternative_candidates([BIVAL], W)
    assert "Bivalirudin" not in [c.new_drug_name for c in res.candidates]
    none_checked = service.find_alternative_candidates([], W)
    assert all("Not checked against any current medication" in c.reason for c in none_checked.candidates)
