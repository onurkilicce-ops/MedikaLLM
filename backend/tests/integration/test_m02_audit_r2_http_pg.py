"""M02-O1-R2 through HTTP -> auth -> service -> SYNTHETIC PostgreSQL -> JSON.

Checks the drug/measurement identity, review reasons, conditions, quote and
offsets, attributed/nearby reference lists and the derived object for the
re-audit findings D1-D4 (and that D5 stays as fixed). All texts SYNTHETIC.
"""
from __future__ import annotations

import pytest

from .conftest import requires_synthetic_pg
from .test_m02_audit_http_pg import A, B, C, D, E, F, _post, _reasons, _set

pytestmark = requires_synthetic_pg
T = "[SYNTHETIC] "
NAME = "[SYNTHETIC] Drug A"


def test_r2_d1_d2_d3_http(synthetic_pg, synthetic_app):
    _set(synthetic_pg, {
        A: (NAME, T + "It has not been established that Tmax is 2 hours.",
            T + "There is no evidence that the half-life is 4 hours."),
        B: (NAME, "", T + "It is not known whether the half-life is 4 hours."),
        C: (NAME, "", T + "In dogs, elimination was studied. The half-life is 4 hours."),
        D: (NAME, "", T + "The half-life of drug b is 10 hours."),
        E: (NAME, "", T + "drug b has a half-life of 10 hours. The half-life of drug a is 4 hours."),
        F: (NAME, "", T + "No dose adjustment is required as the half-life is 4 hours."),
    })
    res = _post(synthetic_app, [A, B, C, D, E, F])

    for drug_id in (A, B):  # D1: not measurements, text kept as review items
        d = res[drug_id]
        assert d["measurements"] == [] and d["derived"] == []
        items = [i for f in d["fields"] for i in f["review_items"]]
        assert items and all(i["quote"].startswith("[SYNTHETIC]") for i in items)
    assert "undetermined_statement" in _reasons(res[A])
    assert "hypothetical_or_open_question" in _reasons(res[B])

    (m,) = res[C]["measurements"]  # D2: species scope sentence flags the value
    assert m["measurement_id"] == f"{C}:half_life:1"
    assert {"field_context_unattributed", "non_human_context_in_field"} <= set(m["review_reasons"])
    assert res[C]["derived"][0]["status"] == "not_computed" and res[C]["derived"][0]["hours"] is None

    assert res[D]["measurements"] == [] and "subject_unresolved" in _reasons(res[D])  # D3
    (m,) = res[E]["measurements"]  # D3: other subject dropped, record drug kept
    assert m["hours"]["value"] == 4.0 and m["review_required"] is False
    stored = T + "drug b has a half-life of 10 hours. The half-life of drug a is 4 hours."
    assert stored[m["source"]["value_start"]:m["source"]["value_end"]] == "4 hours"
    assert m["source"]["quote"] == "The half-life of drug a is 4 hours."
    assert res[E]["derived"][0]["hours"]["value"] == 20.0

    (m,) = res[F]["measurements"]  # D1 positive: the negation belongs to another claim
    assert m["review_required"] is False and res[F]["derived"][0]["hours"]["value"] == 20.0


def test_r2_d4_and_d5_http(synthetic_pg, synthetic_app):
    _set(synthetic_pg, {
        A: (NAME, "", T + "The half-life is 4 hours, while adverse events are described elsewhere [A2] in the report."),
        B: (NAME, "", T + "The half-life is 4 hours [A1], while adverse events are described elsewhere [A2] "
                          "in the report."),
        C: (NAME, "", T + "Adverse events are described elsewhere [A2], and the half-life is 4 hours."),
        D: (NAME, "", T + "The half-life is 4 hours.[A1]"),
        E: (NAME, "", T + "The elimination half-life is 4 ± 1 hours."),
    }, refs=[(d, r, f"[SYNTHETIC] ref {r}") for d in (A, B, C, D) for r in ("A1", "A2")])
    res = _post(synthetic_app, [A, B, C, D, E])
    for drug_id in (A, C):
        (m,) = res[drug_id]["measurements"]
        src = m["source"]
        assert src["inline_reference_tokens"] == [] and src["references"] == []
        assert src["nearby_reference_tokens"] == ["A2"] and src["stored_reference_attributed"] is False
    (m,) = res[B]["measurements"]
    src = m["source"]
    assert src["inline_reference_tokens"] == ["A1"] and [r["ref_id"] for r in src["references"]] == ["A1"]
    assert src["nearby_reference_tokens"] == ["A2"]
    assert src["reference_scope"] == "value_window" and src["stored_reference_attributed"] is True
    (m,) = res[D]["measurements"]
    assert m["source"]["reference_scope"] == "sentence_single_value"
    assert [r["ref_id"] for r in m["source"]["references"]] == ["A1"]
    (d,) = res[E]["derived"]  # D5 unchanged
    assert d["hours"]["value"] == 20.0 and d["dispersion"]["value_hours"] == 5.0
