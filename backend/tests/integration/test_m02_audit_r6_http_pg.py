"""M02-O1-R6 through HTTP -> auth -> service -> SYNTHETIC PostgreSQL -> JSON.

D3: digit-led names and amount-prefixed names; D4-A: statement before a dash;
D4-B: a token right after a value kept whole. Every request carries a second
record '[SYNTHETIC] Drug B' with empty timing fields. All texts SYNTHETIC;
'5-zoralen' is an invented name.
"""
from __future__ import annotations

import pytest

from .conftest import requires_synthetic_pg
from .test_m02_audit_http_pg import A, B, C, D, E, F, _post, _reasons, _set

pytestmark = requires_synthetic_pg
T = "[SYNTHETIC] "
NAME = "[SYNTHETIC] Drug A"
EMPTY_B = ("[SYNTHETIC] Drug B", "", "")


def test_r6_d3_amount_and_digit_led_names_http(synthetic_pg, synthetic_app):
    _set(synthetic_pg, {
        A: (NAME, "", T + "The half-life of 5-zoralen is 10 hours."),
        B: EMPTY_B,
        C: (NAME, "", T + "For 5-zoralen, the half-life is 10 hours."),
        D: (NAME, "", T + "For 10 mg drug b, the half-life is 10 hours."),
        E: ("[SYNTHETIC] 5-zoralen", "", T + "The half-life of 5-zoralen is 4 hours."),
        F: (NAME, "", T + "For 10 mg drug a, the half-life is 4 hours."),
    })
    res = _post(synthetic_app, [A, B, C, D, E, F])
    for drug_id in (A, C, D):
        d = res[drug_id]
        assert d["measurements"] == [] and d["derived"] == []
        assert "subject_unresolved" in _reasons(d)
        items = [i for f in d["fields"] for i in f["review_items"]]
        assert items and all(i["quote"].startswith("[SYNTHETIC]") for i in items)
    assert res[B]["data_status"]["half_life"] == "empty"
    for drug_id in (E, F):
        (m,) = res[drug_id]["measurements"]
        assert m["review_required"] is False and m["hours"]["value"] == 4.0
        assert res[drug_id]["derived"][0]["status"] == "computed"
        assert res[drug_id]["derived"][0]["hours"]["value"] == 20.0


@pytest.mark.parametrize("dash", [" - ", " – ", " — ", " -- "])
def test_r6_d4_dash_before_value_and_split_token_http(synthetic_pg, synthetic_app, dash):
    refs = [(x, r, f"[SYNTHETIC] ref {r}") for x in (A, C, D) for r in ("A1", "A2")]
    d4b = T + f"The half-life is 4 hours [A1]{dash}10 hours after dosing, rash was observed [A2]."
    _set(synthetic_pg, {
        A: (NAME, "", T + f"Rash was observed [A2]{dash}4 hours is the half-life [A1]."),
        B: EMPTY_B,
        C: (NAME, "", d4b),
        D: (NAME, "", T + "The half-life is 4 hours - 6 hours [A1]."),
    }, refs=refs)
    res = _post(synthetic_app, [A, B, C, D])
    for drug_id in (A, C):
        (m,) = res[drug_id]["measurements"]
        src = m["source"]
        assert src["inline_reference_tokens"] == ["A1"] and [r["ref_id"] for r in src["references"]] == ["A1"]
        assert src["nearby_reference_tokens"] == ["A2"] and src["reference_scope"] == "value_window"
        assert src["stored_reference_attributed"] is True
    (m,) = res[C]["measurements"]  # offsets of the source text are unchanged
    assert d4b[m["source"]["value_start"]:m["source"]["value_end"]] == "4 hours"
    assert "duration_not_identified_as_half_life" in _reasons(res[C])
    (m,) = res[D]["measurements"]  # a real range keeps its source
    assert m["hours"]["kind"] == "range" and m["source"]["inline_reference_tokens"] == ["A1"]
