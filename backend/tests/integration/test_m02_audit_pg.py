"""``scripts/audit_m02_data.py`` on the SYNTHETIC PostgreSQL database.

Checks that the inventory really runs read-only, reports counts only (no text,
no connection details), separates empty / placeholder / text / parsed /
review states and never writes. All timing texts are synthetic.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .conftest import requires_synthetic_pg

pytestmark = requires_synthetic_pg

URL = os.getenv("MEDICALLM_SYNTHETIC_PG_URL", "")
TAG = "[SYNTHETIC TEST RECORD]"
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit_m02_data.py"


def _load():
    spec = importlib.util.spec_from_file_location("audit_m02_data", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def seeded(synthetic_pg):
    from src.db.sql_models import Drug, DrugReference

    texts = {
        "DB00006": (f"{TAG} Tmax is 1 hour after oral dosing.[A800001]", f"{TAG} The half-life is 4-6 hours."),
        "DB00316": ("Not Available", "1000x"),
        "DB00682": (f"{TAG} Peak plasma levels vary.", ""),
        "DB00945": ("", f"{TAG} The half-life of the active metabolite is 20 hours.[A800009]"),
    }
    with Session(synthetic_pg) as s:
        drugs = {d.drug_id: d for d in s.scalars(select(Drug))}
        for drug_id, (absorption, half_life) in texts.items():
            drugs[drug_id].absorption = absorption
            drugs[drug_id].half_life = half_life
        drugs["DB00316"].half_life = (f"{TAG} The half-life is 3 hours. " + "Filler. " * 200)[:1000]
        drugs["DB00006"].metabolism = f"{TAG} Metabolised over 2 hours."
        s.add(DrugReference(drug_pk=drugs["DB00006"].id, ref_type="article", ref_id="A800001",
                            citation=f"{TAG} synthetic"))
        s.commit()
    return synthetic_pg


def test_inventory_counts_and_read_only(seeded):
    mod = _load()
    before = []
    with seeded.connect() as conn:
        before = conn.execute(text("SELECT md5(string_agg(drug_id || coalesce(half_life,'') || "
                                   "coalesce(absorption,''), '|' ORDER BY drug_id)) FROM drugs")).scalar_one()
    report = mod.run(URL, None)
    assert report["status"] == "ok" and report["exit_code"] == 0
    assert report["database"] == {"connected": True, "transaction_read_only": "on"}
    inv = report["inventory"]
    assert inv["drugs_total"] == 6
    hl = inv["fields"]["half_life"]
    assert hl == {"total": 6, "empty": 3, "placeholder": 0, "text_present": 3}
    ab = inv["fields"]["absorption"]
    assert ab == {"total": 6, "empty": 3, "placeholder": 1, "text_present": 2}
    assert inv["half_life_length"]["exactly_stored_max"] == 1
    p_hl = inv["parsed_fields"]["half_life"]
    assert p_hl["field_status"]["parsed"] == 2  # 4-6 h; metabolite value is unflagged too
    assert p_hl["field_status"]["parsed_needs_review"] == 1  # possibly truncated
    p_ab = inv["parsed_fields"]["absorption"]
    assert p_ab["keyword_present"] == 2  # 'Tmax' and 'Peak plasma levels'
    assert p_ab["keyword_present_but_no_measurement"] == 1  # keyword alone is not a usable Tmax
    assert p_ab["measurement_reference_status"] == {"matched": 1}
    assert p_hl["measurement_reference_status"]["unmatched"] == 1  # A800009 has no reference row
    d = inv["derived_five_half_lives"]
    assert d["computed"] == 1 and d["not_computed"] == 2
    assert d["not_computed_reasons"]["metabolite_not_parent"] == 1
    assert inv["count_only_fields_with_duration_expression_not_parsed"]["metabolism"] == 1
    with seeded.connect() as conn:
        after = conn.execute(text("SELECT md5(string_agg(drug_id || coalesce(half_life,'') || "
                                  "coalesce(absorption,''), '|' ORDER BY drug_id)) FROM drugs")).scalar_one()
    assert after == before


def test_report_contains_counts_only(seeded):
    mod = _load()
    import json

    dumped = json.dumps(mod.run(URL, None))
    for leak in ("SYNTHETIC", "half-life is", "127.0.0.1", "synth@", "postgresql", "A800001", "Timing"):
        assert leak not in dumped, leak


def test_unreachable_database_is_exit_1_with_type_only():
    mod = _load()
    report = mod.run("postgresql://synth@127.0.0.1:1/none_synth", None)
    assert report["exit_code"] == 1 and report["status"] == "error"
    assert report["database"]["connected"] is False
    assert report["error"] == "OperationalError"
    assert "127.0.0.1" not in str(report)


def test_refuses_when_read_only_cannot_be_confirmed(seeded, monkeypatch):
    mod = _load()
    from sqlalchemy import create_engine

    def no_read_only_engine(url, sslmode):
        return create_engine(url)  # deliberately without default_transaction_read_only

    monkeypatch.setattr(mod, "_engine", no_read_only_engine)
    called = []
    monkeypatch.setattr(mod, "build_inventory", lambda conn: called.append(1) or {})
    report = mod.run(URL, None)
    assert report["exit_code"] == 1 and report["error"] == "read_only_not_confirmed"
    assert report["database"]["transaction_read_only"] == "off"
    assert called == []
