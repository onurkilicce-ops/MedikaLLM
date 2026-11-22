"""Drug service failure paths at the database boundary.

``get_session`` is replaced so the database is unreachable or a query fails
mid-way. Before this change the interaction check returned
``interactions=[], count=0, overall_severity=None`` — identical to a
successful query with no records. The success paths run against a real
(synthetic) PostgreSQL in tests/integration/test_drug_status_pg.py.
"""
from __future__ import annotations

import pytest

from src.drugs import service
from src.drugs.models import CheckDrugInteractionRequest


class _BrokenSession:
    def query(self, *_a, **_k):
        raise RuntimeError("connection reset by peer postgresql://u:secret@h/db")

    def close(self):
        pass


def _unreachable():
    raise RuntimeError("could not connect to server")


@pytest.mark.parametrize("factory", [_unreachable, lambda: _BrokenSession()])
def test_interaction_check_failure_is_status_error(monkeypatch, factory):
    monkeypatch.setattr(service, "get_session", factory)
    res = service.check_drug_interactions(CheckDrugInteractionRequest(drug_ids=["DB00682", "DB00945"]))
    assert res.status == "error"
    assert res.error is not None and res.error.code == "database_error"
    assert "secret" not in res.error.message
    assert res.interactions == [] and res.overall_severity is None
    assert res.pairs_total == 1 and res.pairs_checked == 0


@pytest.mark.parametrize("factory", [_unreachable, lambda: _BrokenSession()])
def test_food_lookup_failure_is_status_error(monkeypatch, factory):
    monkeypatch.setattr(service, "get_session", factory)
    res = service.lookup_drug_food_interactions("DB00682")
    assert res.status == "error"
    # The legacy list accessor still returns a list (no crash for old callers).
    assert service.check_drug_food_interactions("DB00682") == []


def test_alternatives_failure_is_status_error(monkeypatch):
    monkeypatch.setattr(service, "get_session", _unreachable)
    res = service.find_alternative_candidates(["DB00945"], "DB00682")
    assert res.status == "error" and res.candidates == []


def test_overdose_check_failure_is_status_error(monkeypatch):
    monkeypatch.setattr(service, "get_session", _unreachable)
    res = service.check_overdose_risk(["DB00682", "DB00945"])
    assert res.status == "error" and res.has_risk is False


def test_analyze_patient_failure_is_status_error(monkeypatch):
    from src.drugs.models import AnalyzePatientRequest

    monkeypatch.setattr(service, "get_session", _unreachable)
    res = service.analyze_patient(AnalyzePatientRequest(patient_id="p1"))
    assert res.status == "error"
    assert res.safe_alternatives == []
