"""M02-O1-R4 through HTTP -> auth -> service -> SYNTHETIC PostgreSQL -> JSON.

D3: a named subject must survive salt/condition cleaning; D4: a statement
after a dash is not the value's source. Each request also carries a second
record '[SYNTHETIC] Drug B' with empty timing fields. All texts SYNTHETIC.
"""
from __future__ import annotations

from .conftest import requires_synthetic_pg
from .test_m02_audit_http_pg import A, B, C, D, E, F, _post, _reasons, _set

pytestmark = requires_synthetic_pg
T = "[SYNTHETIC] "
NAME = "[SYNTHETIC] Drug A"
EMPTY_B = ("[SYNTHETIC] Drug B", "", "")


def test_r4_d3_subject_survives_cleaning_http(synthetic_pg, synthetic_app):
    _set(synthetic_pg, {
        A: (NAME, "", T + "The half-life of magnesium sulfate is 10 hours."),
        B: EMPTY_B,
        C: (NAME, "", T + "For drug b in overdose, the half-life is 10 hours."),
        D: (NAME, "", T + "For drug a in overdose, the half-life is 4 hours."),
        E: (NAME, "", T + "For drug a hydrochloride, the half-life is 4 hours."),
        F: ("[SYNTHETIC] magnesium sulfate", "", T + "The half-life of magnesium sulfate is 4 hours."),
    })
    res = _post(synthetic_app, [A, B, C, D, E, F])
    for drug_id in (A, C):  # no clean value, no 5x under the wrong drug; text and reason kept
        d = res[drug_id]
        assert d["measurements"] == [] and d["derived"] == []
        assert "subject_unresolved" in _reasons(d)
        items = [i for f in d["fields"] for i in f["review_items"]]
        assert items and all(i["quote"].startswith("[SYNTHETIC]") for i in items)
    assert res[B]["measurements"] == [] and res[B]["data_status"]["half_life"] == "empty"
    for drug_id in (D, E, F):
        (m,) = res[drug_id]["measurements"]
        assert m["review_required"] is False and m["hours"]["value"] == 4.0
        assert res[drug_id]["derived"][0]["status"] == "computed"
        assert res[drug_id]["derived"][0]["hours"]["value"] == 20.0


def test_r4_d4_dash_reference_http(synthetic_pg, synthetic_app):
    refs = [(x, r, f"[SYNTHETIC] ref {r}") for x in (A, C, D, E, F) for r in ("A1", "A2")]
    _set(synthetic_pg, {
        A: (NAME, "", T + "The half-life is 4 hours — adverse events are described elsewhere [A2]."),
        B: EMPTY_B,
        C: (NAME, "", T + "The half-life is 4 hours.[A1]"),
        D: (NAME, "", T + "The half-life is 4 hours [A1] (adverse events are described elsewhere [A2])."),
        E: (NAME, "", T + "The half-life is 4 hours (in adults) [A1]."),
        F: (NAME, "", T + "The half-life is 4 hours [A1] — adverse events are described elsewhere [A2]."),
    }, refs=refs)
    res = _post(synthetic_app, [A, B, C, D, E, F])
    (m,) = res[A]["measurements"]
    src = m["source"]
    assert src["inline_reference_tokens"] == [] and src["references"] == []
    assert src["nearby_reference_tokens"] == ["A2"] and src["reference_scope"] == "none"
    assert src["stored_reference_attributed"] is False
    for drug_id, scope in ((C, "sentence_single_value"), (D, "value_window"), (E, "value_window"),
                           (F, "value_window")):
        (m,) = res[drug_id]["measurements"]
        src = m["source"]
        assert src["inline_reference_tokens"] == ["A1"] and [r["ref_id"] for r in src["references"]] == ["A1"]
        assert src["reference_scope"] == scope and src["stored_reference_attributed"] is True
        assert "A2" not in src["inline_reference_tokens"]
