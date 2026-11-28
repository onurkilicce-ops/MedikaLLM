"""M02-O1-R5 through HTTP -> auth -> service -> SYNTHETIC PostgreSQL -> JSON.

The six audit examples (D3-A condition next to a name, D3-B partial salt
name, D4 numbered statement after a dash) and their positive pairs. Every
request carries a second record '[SYNTHETIC] Drug B' with empty timing
fields. All texts SYNTHETIC.
"""
from __future__ import annotations

from .conftest import requires_synthetic_pg
from .test_m02_audit_http_pg import A, B, C, D, E, F, _post, _reasons, _set

pytestmark = requires_synthetic_pg
T = "[SYNTHETIC] "
NAME = "[SYNTHETIC] Drug A"
EMPTY_B = ("[SYNTHETIC] Drug B", "", "")


def _no_measurement(drug, reason="subject_unresolved"):
    assert drug["measurements"] == [] and drug["derived"] == []
    assert reason in _reasons(drug)
    items = [i for f in drug["fields"] for i in f["review_items"]]
    assert items and all(i["quote"].startswith("[SYNTHETIC]") for i in items)


def _clean_4h(drug):
    (m,) = drug["measurements"]
    assert m["review_required"] is False and m["hours"]["value"] == 4.0
    assert drug["derived"][0]["status"] == "computed" and drug["derived"][0]["hours"]["value"] == 20.0


def test_r5_d3a_condition_next_to_a_name_http(synthetic_pg, synthetic_app):
    _set(synthetic_pg, {
        A: (NAME, "", T + "For drug b monotherapy, the half-life is 10 hours."),
        B: EMPTY_B,
        C: (NAME, "", T + "In overdose of drug b in adults, the half-life is 10 hours."),
        D: (NAME, "", T + "For drug a monotherapy, the half-life is 4 hours."),
        E: (NAME, "", T + "In overdose of drug a in adults, the half-life is 4 hours."),
        F: (NAME, "", T + "For oral administration, the half-life is 4 hours."),
    })
    res = _post(synthetic_app, [A, B, C, D, E, F])
    _no_measurement(res[A])
    _no_measurement(res[C])
    assert res[B]["data_status"]["half_life"] == "empty"
    for drug_id in (D, E, F):
        _clean_4h(res[drug_id])


def test_r5_d3b_partial_salt_name_http(synthetic_pg, synthetic_app):
    _set(synthetic_pg, {
        A: ("[SYNTHETIC] magnesium sulfate", "", T + "The half-life of magnesium is 10 hours."),
        B: EMPTY_B,
        C: ("[SYNTHETIC] magnesium", "", T + "The half-life of magnesium sulfate is 10 hours."),
        D: ("[SYNTHETIC] magnesium sulfate", "", T + "The half-life of magnesium sulfate is 4 hours."),
        E: (NAME, "", T + "For drug a hydrochloride, the half-life is 4 hours."),
        F: ("[SYNTHETIC] sodium chloride", "", T + "The half-life of magnesium sulfate is 10 hours."),
    })
    res = _post(synthetic_app, [A, B, C, D, E, F])
    for drug_id in (A, C, F):
        _no_measurement(res[drug_id])
    for drug_id in (D, E):
        _clean_4h(res[drug_id])


def test_r5_d4_numbered_statement_after_dash_http(synthetic_pg, synthetic_app):
    refs = [(x, r, f"[SYNTHETIC] ref {r}") for x in (A, C, D, E, F) for r in ("A1", "A2")]
    _set(synthetic_pg, {
        A: (NAME, "", T + "The half-life is 4 hours - 10 patients developed rash [A2]."),
        B: EMPTY_B,
        C: (NAME, "", T + "The half-life is 4 hours – 10 patients developed rash [A2]."),
        D: (NAME, "", T + "The half-life is 4 hours [A1] — in adults — adverse events are described "
                          "elsewhere [A2]."),
        E: (NAME, "", T + "The half-life is 4 hours — in adults [A1] — adverse events are described "
                          "elsewhere [A2]."),
        F: (NAME, "", T + "The half-life is 4 hours - 6 hours [A1]."),
    }, refs=refs)
    res = _post(synthetic_app, [A, B, C, D, E, F])
    for drug_id in (A, C):
        (m,) = res[drug_id]["measurements"]
        src = m["source"]
        assert src["inline_reference_tokens"] == [] and src["references"] == []
        assert src["nearby_reference_tokens"] == ["A2"] and src["reference_scope"] == "none"
        assert src["stored_reference_attributed"] is False
    for drug_id in (D, E):
        (m,) = res[drug_id]["measurements"]
        src = m["source"]
        assert src["inline_reference_tokens"] == ["A1"] and [r["ref_id"] for r in src["references"]] == ["A1"]
        assert src["nearby_reference_tokens"] == ["A2"] and src["reference_scope"] == "value_window"
        assert src["stored_reference_attributed"] is True
    (m,) = res[F]["measurements"]  # a range keeps its source
    assert m["hours"]["kind"] == "range" and m["hours"]["lower"] == 4.0 and m["hours"]["upper"] == 6.0
    assert m["source"]["inline_reference_tokens"] == ["A1"]
