"""M02-O1-R3 through HTTP -> auth -> service -> SYNTHETIC PostgreSQL -> JSON.

The eight audit examples of D1 (intervening phrase / 'failed to establish'),
D3 (lower-case possessive / framing subject) and D4 (claim in a parenthesis
or after a colon), their positive pairs and combined examples. All texts
SYNTHETIC; every record is named '[SYNTHETIC] Drug A'.
"""
from __future__ import annotations

from .conftest import requires_synthetic_pg
from .test_m02_audit_http_pg import A, B, C, D, E, F, _post, _reasons, _set

pytestmark = requires_synthetic_pg
T = "[SYNTHETIC] "
NAME = "[SYNTHETIC] Drug A"


def test_r3_d1_intervening_phrase_http(synthetic_pg, synthetic_app):
    _set(synthetic_pg, {
        A: (NAME, T + "It is not known whether, after oral administration, Tmax is 2 hours.",
            T + "There is no evidence that, in adults, the half-life is 4 hours."),
        B: (NAME, "", T + "There is no evidence that the half-life, measured in adults, is 4 hours."),
        C: (NAME, "", T + "Studies failed to establish that the half-life is 4 hours."),
        D: (NAME, "", T + "Studies have shown that, in adults, the half-life is 4 hours."),
        E: (NAME, "", T + "No dose adjustment is required as the half-life is 4 hours."),
        F: (NAME, "", T + "The half-life is not less than 4 hours."),
    })
    res = _post(synthetic_app, [A, B, C, D, E, F])

    for drug_id in (A, B, C):  # no clean measurement, no 5x, text + reason kept
        d = res[drug_id]
        assert d["measurements"] == [] and d["derived"] == []
        items = [i for f in d["fields"] for i in f["review_items"]]
        assert items and all(i["quote"].startswith("[SYNTHETIC]") for i in items)
    assert "hypothetical_or_open_question" in _reasons(res[A])
    assert "undetermined_statement" in _reasons(res[A])
    assert res[A]["data_status"] == {"tmax": "unparsed_needs_review", "half_life": "unparsed_needs_review"}
    assert "undetermined_statement" in _reasons(res[B]) and "undetermined_statement" in _reasons(res[C])

    (m,) = res[D]["measurements"]  # positive: governing clause asserts, aside kept as condition
    assert m["review_required"] is False and m["conditions"]["population"] == ["adults"]
    stored = T + "Studies have shown that, in adults, the half-life is 4 hours."
    assert stored[m["source"]["value_start"]:m["source"]["value_end"]] == "4 hours"
    assert res[D]["derived"][0]["status"] == "computed" and res[D]["derived"][0]["hours"]["value"] == 20.0
    (m,) = res[E]["measurements"]
    assert m["review_required"] is False and res[E]["derived"][0]["hours"]["value"] == 20.0
    (m,) = res[F]["measurements"]  # a lower bound, not a negation
    assert m["review_required"] is False and m["hours"]["kind"] == "lower_bound"


def test_r3_d3_lower_case_subject_http(synthetic_pg, synthetic_app):
    _set(synthetic_pg, {
        A: (NAME, "", T + "drug b's half-life is 10 hours."),
        B: (NAME, "", T + "For drug b, the half-life is 10 hours."),
        C: (NAME, "", T + "drug a's half-life is 4 hours."),
        D: (NAME, "", T + "For drug a, the half-life is 4 hours."),
        E: (NAME, "", T + "Drug B's half-life is 10 hours."),
        F: (NAME, "", T + "For Drug A, the half-life is 4 hours."),
    })
    res = _post(synthetic_app, [A, B, C, D, E, F])
    for drug_id in (A, B, E):  # not credited to Drug A, in either letter case
        d = res[drug_id]
        assert d["measurements"] == [] and d["derived"] == []
        assert _reasons(d) & {"subject_unresolved", "subject_not_record_drug"}
    for drug_id in (C, D, F):
        (m,) = res[drug_id]["measurements"]
        assert m["review_required"] is False and m["hours"]["value"] == 4.0
        assert res[drug_id]["derived"][0]["hours"]["value"] == 20.0


def test_r3_d4_parenthesis_and_colon_http(synthetic_pg, synthetic_app):
    refs = [(x, r, f"[SYNTHETIC] ref {r}") for x in (A, B, C, D, E, F) for r in ("A1", "A2")]
    _set(synthetic_pg, {
        A: (NAME, "", T + "The half-life is 4 hours (adverse events are described elsewhere [A2])."),
        B: (NAME, "", T + "The half-life is 4 hours: adverse events are described elsewhere [A2] in the report."),
        C: (NAME, "", T + "The half-life is 4 hours.[A1]"),
        D: (NAME, "", T + "The half-life is 4 hours, in adults.[A1]"),
        E: (NAME, "", T + "The half-life is 4.5 hours.[A1]"),
        F: (NAME, "", T + "The half-life is 4 hours.[A1] Adverse events are described elsewhere.[A2]"),
    }, refs=refs)
    res = _post(synthetic_app, [A, B, C, D, E, F])
    for drug_id in (A, B):
        (m,) = res[drug_id]["measurements"]
        src = m["source"]
        assert src["inline_reference_tokens"] == [] and src["references"] == []
        assert src["nearby_reference_tokens"] == ["A2"] and src["reference_scope"] == "none"
        assert src["stored_reference_attributed"] is False
    for drug_id, value in ((C, 4.0), (D, 4.0), (E, 4.5), (F, 4.0)):
        (m,) = res[drug_id]["measurements"]
        src = m["source"]
        assert m["hours"]["value"] == value
        assert src["reference_scope"] == "sentence_single_value" and src["stored_reference_attributed"] is True
        assert [r["ref_id"] for r in src["references"]] == ["A1"] and "A2" not in src["inline_reference_tokens"]


def test_r3_combined_http(synthetic_pg, synthetic_app):
    _set(synthetic_pg, {
        A: (NAME, "", T + "There is no evidence that, for drug b, the half-life (measured in adults) is 4 hours [A2]."),
        B: (NAME, "", T + "Studies have shown that, for drug a, the half-life is 4 hours "
                          "(adverse events are described elsewhere [A2]).[A1]"),
        C: (NAME, "", T + "drug b's half-life is 10 hours: adverse events are described elsewhere [A2]. "
                          "drug a's half-life is 4 hours.[A1]"),
    }, refs=[(x, r, f"[SYNTHETIC] ref {r}") for x in (A, B, C) for r in ("A1", "A2")])
    res = _post(synthetic_app, [A, B, C])
    assert res[A]["measurements"] == [] and "undetermined_statement" in _reasons(res[A])
    (m,) = res[B]["measurements"]
    assert m["review_required"] is False and res[B]["derived"][0]["hours"]["value"] == 20.0
    assert "A2" not in m["source"]["inline_reference_tokens"] and "A2" in m["source"]["nearby_reference_tokens"]
    assert m["source"]["stored_reference_attributed"] is False  # A1 follows a separate claim
    (m,) = res[C]["measurements"]
    assert m["hours"]["value"] == 4.0 and "subject_unresolved" in _reasons(res[C])
    assert "A2" not in m["source"]["inline_reference_tokens"]
