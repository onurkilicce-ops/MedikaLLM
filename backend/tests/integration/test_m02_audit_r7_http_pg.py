"""M02-O1-R7 through HTTP -> auth -> service -> SYNTHETIC PostgreSQL -> JSON.

The four D3 findings ('20% drug b', '2.5mg drug b' in a 'For ...,' frame and
in 'half-life of ...') and their record-drug pairs. Every request carries a
second record '[SYNTHETIC] Drug B' with empty timing fields. All SYNTHETIC.
"""
from __future__ import annotations

from .conftest import requires_synthetic_pg
from .test_m02_audit_http_pg import A, B, C, D, E, F, _post, _reasons, _set

pytestmark = requires_synthetic_pg
T = "[SYNTHETIC] "
NAME = "[SYNTHETIC] Drug A"
EMPTY_B = ("[SYNTHETIC] Drug B", "", "")
FINDINGS = ["For 20% drug b, the half-life is 10 hours.", "The half-life of 20% drug b is 10 hours.",
            "For 2.5mg drug b, the half-life is 10 hours.", "The half-life of 2.5mg drug b is 10 hours."]


def test_r7_findings_http(synthetic_pg, synthetic_app):
    ids = [A, C, D, E]
    rows = {i: (NAME, "", T + t) for i, t in zip(ids, FINDINGS)}
    rows[B] = EMPTY_B
    _set(synthetic_pg, rows)
    res = _post(synthetic_app, [A, B, C, D, E])
    for drug_id, text in zip(ids, FINDINGS):
        d = res[drug_id]
        assert d["measurements"] == [] and d["derived"] == []
        assert "subject_unresolved" in _reasons(d)
        (item,) = [i for f in d["fields"] for i in f["review_items"]]
        assert item["quote"] == T + text and item["reason"] == "subject_unresolved"
    assert res[B]["data_status"]["half_life"] == "empty"


def test_r7_record_pairs_http(synthetic_pg, synthetic_app):
    texts = ["For 20% drug a, the half-life is 4 hours.", "The half-life of 20% drug a is 4 hours.",
             "For 2.5mg drug a, the half-life is 4 hours.", "The half-life of 2.5mg drug a is 4 hours.",
             "For 10mg drug a, the half-life is 4 hours."]
    ids = [A, C, D, E, F]
    rows = {i: (NAME, "", T + t) for i, t in zip(ids, texts)}
    rows[B] = EMPTY_B
    _set(synthetic_pg, rows)
    res = _post(synthetic_app, [A, B, C, D, E, F])
    for drug_id, text in zip(ids, texts):
        (m,) = res[drug_id]["measurements"]
        assert m["review_required"] is False and m["hours"]["value"] == 4.0
        stored = T + text
        assert stored[m["source"]["value_start"]:m["source"]["value_end"]] == "4 hours"
        assert res[drug_id]["derived"][0]["status"] == "computed"
        assert res[drug_id]["derived"][0]["hours"]["value"] == 20.0
