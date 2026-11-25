"""M02-O1-D1: audit findings D1-D6 checked through HTTP -> auth -> service ->
SYNTHETIC PostgreSQL -> response.

Uses the shared throw-away ``*_synth`` database (``synthetic_pg`` /
``synthetic_app`` fixtures, unchanged); each test re-seeds it and then writes
SYNTHETIC timing text onto the already-seeded drug ids. Nothing here is drug
data; the texts are audit evidence.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .conftest import requires_synthetic_pg
from .synthetic_data import ACCOUNTS

pytestmark = requires_synthetic_pg

URL = "/api/timing/compare"
A, B, C, D, E, F = "DB00006", "DB00316", "DB00682", "DB00945", "DB01211", "DB01418"
DOCTOR = ACCOUNTS["doctor_assigned"][0]


def _auth():
    from src.config import settings

    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    return {"Authorization": "Bearer " + jwt.encode({"userId": DOCTOR, "exp": exp}, settings.jwt_secret,
                                                    algorithm="HS256")}


def _set(engine, texts, refs=()):
    """texts: {drug_id: (name, absorption, half_life)}; refs: (drug_id, ref_id, citation)."""
    from src.db.sql_models import Drug, DrugReference

    with Session(engine) as s:
        drugs = {d.drug_id: d for d in s.scalars(select(Drug).where(Drug.drug_id.in_(list(texts) + [r[0] for r in refs])))}
        for drug_id, (name, absorption, half_life) in texts.items():
            d = drugs[drug_id]
            d.name, d.name_lower, d.absorption, d.half_life = name, name.lower(), absorption, half_life
        for drug_id, ref_id, citation in refs:
            s.add(DrugReference(drug_pk=drugs[drug_id].id, ref_type="article", ref_id=ref_id, citation=citation))
        s.commit()


def _post(client, ids):
    r = client.post(URL, json={"drug_ids": ids}, headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_version"] == "m02-timing-compare/2" and body["parser_version"] == "m02-text-parser/5"
    assert body["timing_advice"]["status"] == "not_evaluated" and body["timing_advice"]["advice"] == []
    return {d["requested_id"]: d for d in body["drugs"]}


def _reasons(drug):
    return {i["reason"] for f in drug["fields"] for i in f["review_items"]} | {
        x for m in drug["measurements"] for x in m["review_reasons"]}


def test_d1_d2_d3_http(synthetic_pg, synthetic_app):
    T = "[SYNTHETIC] "
    _set(synthetic_pg, {
        A: ("[SYNTHETIC] Drug A", T + "Tmax was not 2 hours.", T + "The half-life is not 4 hours."),
        B: ("[SYNTHETIC] Drug B1", "", T + "The half-life is 4 hours in patients without renal impairment."),
        C: ("[SYNTHETIC] Drug C1", "", T + "These measurements were obtained in dogs. The elimination half-life is 4 hours."),
        D: ("[SYNTHETIC] Drug A", "", T + "Unlike Drug B, which has a half-life of 10 hours, the half-life of "
                                       "Drug A has not been established."),
        E: ("[SYNTHETIC] Drug E1", T + "Tmax is 2 hours.", T + "In burn patients, the elimination half-life is 4 hours."),
        F: ("[SYNTHETIC] Drug A", "", T + "The half-life of Drug B is 10 hours. The half-life of Drug A is 6 hours."),
    })
    res = _post(synthetic_app, [A, B, C, D, E, F])

    a = res[A]  # D1: negated values are not measurements
    assert a["measurements"] == [] and a["derived"] == []
    assert a["data_status"] == {"tmax": "unparsed_needs_review", "half_life": "unparsed_needs_review"}
    assert "negated_value" in _reasons(a)

    b = res[B]  # D1: negated condition keeps its meaning, flagged, no 5x
    (m,) = b["measurements"]
    assert m["conditions"]["population"] == ["without renal impairment"]
    assert m["review_required"] is True and "negated_condition" in m["review_reasons"]
    assert b["derived"][0]["status"] == "not_computed" and b["derived"][0]["hours"] is None

    c = res[C]  # D2: species stated in another sentence
    (m,) = c["measurements"]
    assert m["review_required"] is True
    assert {"field_context_unattributed", "non_human_context_in_field"} <= set(m["review_reasons"])
    assert c["derived"][0]["status"] == "not_computed"

    d = res[D]  # D3: the compared drug's 10 h is not Drug A's measurement
    assert d["measurements"] == [] and d["derived"] == []
    assert _reasons(d) & {"subject_unresolved_comparison", "undetermined_statement"}

    e = res[E]  # D2 positive: group named in the same clause is carried; plain Tmax stays clean
    (tm, hm) = e["measurements"]
    assert tm["measure_type"] == "tmax" and tm["review_required"] is False
    assert hm["conditions"]["population"] == ["burn patients"] and hm["review_required"] is False
    assert e["derived"][0]["status"] == "computed" and e["derived"][0]["hours"]["value"] == 20.0

    f = res[F]  # D3: named other subject refused, record drug's own value kept
    (m,) = f["measurements"]
    assert m["hours"]["value"] == 6.0 and m["review_required"] is False
    assert "subject_not_record_drug" in _reasons(f)


def test_d4_reference_scope_http(synthetic_pg, synthetic_app):
    T = "[SYNTHETIC] "
    _set(synthetic_pg, {
        A: ("[SYNTHETIC] Drug A", "", T + "The half-life is 4 hours; the duration of effect is 9 hours.[A2]"),
        B: ("[SYNTHETIC] Drug B1", "", T + "The half-life is 4 hours; adverse events are described elsewhere.[A2]"),
        C: ("[SYNTHETIC] Drug C1", "", T + "The half-life is 4 hours.[A1] The duration of effect is 9 hours.[A2]"),
    }, refs=[(A, "A2", "[SYNTHETIC] study of the duration of effect"),
             (B, "A2", "[SYNTHETIC] adverse event listing"),
             (C, "A1", "[SYNTHETIC] elimination study"), (C, "A2", "[SYNTHETIC] duration of effect study")])
    res = _post(synthetic_app, [A, B, C])
    for drug in (res[A], res[B]):
        (m,) = drug["measurements"]
        src = m["source"]
        assert src["reference_scope"] == "sentence_other_clause"
        assert src["references"] == [] and src["inline_reference_tokens"] == []
        assert src["nearby_reference_tokens"] == ["A2"]
        assert src["stored_reference_attributed"] is False
    (m,) = res[C]["measurements"]
    src = m["source"]
    assert src["reference_scope"] == "sentence_single_value" and src["stored_reference_attributed"] is True
    assert [r["ref_id"] for r in src["references"]] == ["A1"]
    assert "A2" not in src["nearby_reference_tokens"]


def test_d5_dispersion_http(synthetic_pg, synthetic_app):
    T = "[SYNTHETIC] "
    _set(synthetic_pg, {
        A: ("[SYNTHETIC] Drug A", "", T + "The elimination half-life is 4 ± 1 hours."),
        B: ("[SYNTHETIC] Drug B1", "", T + "The half-life is 4 ± " + "9" * 308 + " days."),
        C: ("[SYNTHETIC] Drug C1", "", T + "The half-life is 90 minutes; Tmax is not part of this field."),
    })
    res = _post(synthetic_app, [A, B, C])
    (m,) = res[A]["measurements"]
    assert m["dispersion"] == {"kind": "plus_minus", "value_original": 1.0, "unit": "hours", "value_hours": 1.0}
    (d,) = res[A]["derived"]
    assert d["status"] == "computed" and d["hours"]["value"] == 20.0
    assert d["dispersion"] == {"kind": "plus_minus", "statistic": "not_stated", "value_hours": 5.0,
                               "source_value_hours": 1.0}
    b = res[B]  # infinite spread: no silent null, no clean derived value
    assert b["measurements"] == [] and b["derived"] == []
    assert "invalid_value" in _reasons(b)
    assert "null" not in str(b["fields"][1]["review_items"])  # review item keeps text, no numbers
    (m,) = res[C]["measurements"]  # minutes conversion unchanged
    assert m["hours"]["value"] == 1.5


def test_d6_demo_guard_against_the_synthetic_database(synthetic_pg, monkeypatch):
    from src.timing import demo_guard

    url = os.environ["MEDICALLM_SYNTHETIC_PG_URL"]
    db = url.rsplit("/", 1)[-1]
    ok, msgs = demo_guard.check_target({"DO_POSTGRES_URL": url, "M02_DEMO_CONFIRM": db})
    assert ok is True, msgs
    # the same database holding a non-synthetic account is refused (then removed again)
    with synthetic_pg.begin() as conn:
        conn.execute(text("INSERT INTO users (user_id, email, password, name, is_premium) "
                          "VALUES ('m02-guard-probe', 'probe@example.invalid', '!', 'probe', false)"))
    try:
        ok, msgs = demo_guard.check_target({"DO_POSTGRES_URL": url, "M02_DEMO_CONFIRM": db})
        assert ok is False and "non-synthetic" in msgs[0]
    finally:
        with synthetic_pg.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE user_id = 'm02-guard-probe'"))
    # a closed port is refused with the exception type only
    ok, msgs = demo_guard.check_target({"DO_POSTGRES_URL": "postgresql://synth@127.0.0.1:1/none_synth",
                                        "M02_DEMO_CONFIRM": "none_synth"})
    assert ok is False and "OperationalError" in msgs[0] and "synth@" not in msgs[0]
