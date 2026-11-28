"""M-02 ``POST /api/timing/table``: HTTP -> auth -> table -> SYNTHETIC PostgreSQL.

Runs on the shared throw-away ``*_synth`` database. The module replaces the food
entries and categories of two already-seeded synthetic drug ids with SYNTHETIC
wording; the next reset drops everything again.
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete, event, select, text
from sqlalchemy.orm import Session

from .conftest import requires_synthetic_pg
from .test_m02_timing_api_pg import DOCTOR, PATIENT, PLAIN, _auth, _assert_clean_503, broken_db  # noqa: F401

pytestmark = requires_synthetic_pg

URL = "/api/timing/table"
A, B = "DB00006", "DB00316"

FOODS = {
    A: ["Avoid multivalent ions. [SYNTHETIC] Take at least 2 hours before or 6 hours after antacids.",
        "Take on an empty stomach. [SYNTHETIC] Measurement: food delays the Cmax by 1 hour.",
        "Avoid alcohol. [SYNTHETIC]"],
    B: [],
}
CATS = {A: ["[SYNTHETIC] Anti-Infective Agents"], B: ["Antacids"]}


@pytest.fixture
def tbl(synthetic_pg, synthetic_app):
    from src.db.sql_models import Drug, DrugCategory, DrugFoodInteraction

    with Session(synthetic_pg) as s:
        drugs = {d.drug_id: d for d in s.scalars(select(Drug).where(Drug.drug_id.in_([A, B])))}
        for drug_id in (A, B):
            d = drugs[drug_id]
            d.name, d.name_lower = f"[SYNTHETIC] Table Agent {drug_id}", f"[synthetic] table agent {drug_id}".lower()
            s.execute(delete(DrugFoodInteraction).where(DrugFoodInteraction.drug_pk == d.id))
            s.execute(delete(DrugCategory).where(DrugCategory.drug_pk == d.id))
            for f in FOODS[drug_id]:
                s.add(DrugFoodInteraction(drug_pk=d.id, interaction=f))
            for c in CATS[drug_id]:
                s.add(DrugCategory(drug_pk=d.id, category=c, category_lower=c.lower()))
        s.commit()
    return synthetic_app, synthetic_pg


def test_table_rows_columns_times_and_pair(tbl):
    client, _ = tbl
    r = client.post(URL, json={"drug_ids": [A, B, "DB99999"]}, headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_version"] == "m02-timing-table/1"
    assert [(d["requested_id"], d["found"], d["has_food_entries"]) for d in body["drugs"]] == [
        (A, True, True), (B, True, False), ("DB99999", False, False)]
    rows = {x["row_id"]: x["cells"] for x in body["rows"]}
    assert list(rows) == ["meal", "minerals_antacids", "selected_drugs", "alcohol"]
    ions = rows["minerals_antacids"][A][0]
    assert ions["timing_text"] == "≥2 sa önce veya ≥6 sa sonra"
    assert ions["source"] == "drugbank" and ions["source_text"] == FOODS[A][0]
    # a measurement sentence is never a time
    assert rows["meal"][A][0]["timing_text"] == "" and rows["meal"][A][0]["timing_quote"] == ""
    # B carries antacid ions (category): A's ion rule appears against B, in A's column only
    pair = rows["selected_drugs"][A]
    assert [p["with_drug_id"] for p in pair] == [B]
    assert pair[0]["timing_text"] == "≥2 sa önce veya ≥6 sa sonra"
    assert B not in rows["selected_drugs"]


def test_one_drug_is_enough_and_writes_nothing(tbl):
    client, engine = tbl
    statements = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(engine, "before_cursor_execute", _capture)
    try:
        assert client.post(URL, json={"drug_ids": [A]}, headers=_auth()).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", _capture)
    assert not {"INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP"} & set(statements)


def test_401_and_403(tbl):
    client, _ = tbl
    assert client.post(URL, json={"drug_ids": [A]}).status_code == 401
    for user in (PLAIN, PATIENT):
        assert client.post(URL, json={"drug_ids": [A]}, headers=_auth(user)).status_code == 403


@pytest.mark.parametrize("body", [{"drug_ids": []}, {"drug_ids": [A, A]}, {"drug_ids": ["db00006"]},
                                  {"drug_ids": [A], "foods": ["milk"]}, {}])
def test_422(tbl, body):
    client, _ = tbl
    assert client.post(URL, json=body, headers=_auth()).status_code == 422


def test_503_when_the_read_fails_after_auth(tbl, monkeypatch, broken_db):  # noqa: F811
    client, _ = tbl
    from src.timing import repository

    monkeypatch.setattr(repository, "read_professional_flag", lambda user_id: True)
    _assert_clean_503(client.post(URL, json={"drug_ids": [A]}, headers=_auth()))
