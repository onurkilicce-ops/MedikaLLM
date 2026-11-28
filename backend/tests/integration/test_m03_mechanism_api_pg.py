"""M-03 through HTTP -> auth -> service -> SYNTHETIC PostgreSQL -> JSON.

The drug ids are fixture placeholders of the shared synthetic seed; every
name, protein entry, text and interaction record written here is SYNTHETIC
audit data, not a real DrugBank mapping."""
from __future__ import annotations

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from .conftest import requires_synthetic_pg
from .test_m02_audit_http_pg import A, B, C, D, _auth
from .test_m02_timing_api_pg import PATIENT, PLAIN, broken_db  # noqa: F401  (fixture)

pytestmark = requires_synthetic_pg
URL = "/api/mechanism/compare"
T = "[SYNTHETIC] "
CYP = ("BE9000001", T + "Cytochrome P450 3A4")
PGP = ("BE9000002", T + "P-glycoprotein 1")
ALB = ("BE9000003", T + "Serum albumin")


def set_mechanism(engine, drugs, interactions=()):
    """drugs: {drug_id: {name, route, metabolism, clearance, enzymes, transporters, carriers}};
    a protein is (id, name, organism, known_action, actions[, inhibition, induction])."""
    from src.db.sql_models import Drug, DrugCarrier, DrugEnzyme, DrugInteraction, DrugTransporter

    with Session(engine) as s:
        rows = {d.drug_id: d for d in s.scalars(select(Drug).where(Drug.drug_id.in_(list(drugs))))}
        pks = [d.id for d in rows.values()]
        for model in (DrugEnzyme, DrugTransporter, DrugCarrier):
            s.execute(delete(model).where(model.drug_pk.in_(pks)))
        s.execute(delete(DrugInteraction).where(DrugInteraction.drug1_id.in_(pks)))
        for drug_id, spec in drugs.items():
            d = rows[drug_id]
            if "name" in spec:
                d.name, d.name_lower = spec["name"], spec["name"].lower()
            d.route_of_elimination = spec.get("route", "")
            d.metabolism = spec.get("metabolism", "")
            d.clearance = spec.get("clearance", "")
            for p in spec.get("enzymes", ()):
                s.add(DrugEnzyme(drug_pk=d.id, enzyme_id=p[0], name=p[1], organism=p[2], known_action=p[3],
                                 actions=p[4], inhibition_strength=p[5] if len(p) > 5 else "",
                                 induction_strength=p[6] if len(p) > 6 else ""))
            for p in spec.get("transporters", ()):
                s.add(DrugTransporter(drug_pk=d.id, transporter_id=p[0], name=p[1], organism=p[2],
                                      known_action=p[3], actions=p[4]))
            for p in spec.get("carriers", ()):
                s.add(DrugCarrier(drug_pk=d.id, carrier_id=p[0], name=p[1], organism=p[2], known_action=p[3],
                                  actions=p[4]))
        for f, t, desc in interactions:
            s.add(DrugInteraction(drug1_id=rows[f].id, drug2_drugbank_id=t, drug2_name=rows[t].name, description=desc))
        s.commit()


SEED = {
    A: {"name": T + "Inhibitor drug", "route": T + "About 60% is excreted in urine and 30% in feces.",
        "metabolism": T + "Mainly hepatic.", "enzymes": [(*CYP, "Humans", "yes", "inhibitor", "strong")],
        "transporters": [(*PGP, "Humans", "unknown", "inhibitor")]},
    B: {"name": T + "Substrate drug", "route": T + "It is not excreted renally; elimination is biliary.",
        "clearance": T + "Clearance is reduced in patients with hepatic impairment.",
        "enzymes": [(*CYP, "Humans", "yes", "substrate"), ("BE9000009", T + "Rodent enzyme", "Rattus", "yes", "substrate")],
        "transporters": [(*PGP, "Humans", "yes", "substrate")], "carriers": [(*ALB, "Humans", "unknown", "binder")]},
    C: {"name": T + "Bystander drug", "carriers": [(*ALB, "Humans", "unknown", "carrier")]},
    D: {"name": T + "Empty drug"},
}


@pytest.fixture
def client(synthetic_pg, synthetic_app):
    set_mechanism(synthetic_pg, SEED, [(A, B, T + "The metabolism of Substrate drug can be decreased when combined with Inhibitor drug.")])
    return synthetic_app


def _post(client, ids):
    r = client.post(URL, json={"drug_ids": ids}, headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_version"] == "m03-mechanism/1" and body["rules_version"] == "m03-mechanism-rules/1"
    return body


def test_profile_organs_and_proteins(client):
    body = _post(client, [B, A, "DB99999"])
    drugs = {d["requested_id"]: d for d in body["drugs"]}
    assert [d["requested_id"] for d in body["drugs"]] == [B, A, "DB99999"]
    assert drugs["DB99999"] == {"requested_id": "DB99999", "lookup_status": "not_found", "drug": None,
                                "proteins": [], "organs": [], "organs_truncated": False,
                                "proteins_truncated": False, "texts": []}
    a = drugs[A]
    assert [(o["organ"], o["source_field"], o["notes"]) for o in a["organs"]] == [
        ("kidney", "route_of_elimination", []), ("bile_feces", "route_of_elimination", []), ("liver", "metabolism", [])]
    assert all("amount_text" not in o for o in a["organs"])
    q = a["organs"][0]
    stored = next(t["stored_text"] for t in a["texts"] if t["source_field"] == q["source_field"])
    assert stored[q["quote_start"]:q["quote_end"]] == q["quote"]
    b = drugs[B]
    notes = {(o["organ"], o["source_field"]): o["notes"] for o in b["organs"]}
    assert "negated_or_minor" in notes[("kidney", "route_of_elimination")]
    assert notes[("bile_feces", "route_of_elimination")] == []  # ';' ends the negated sentence
    assert notes[("liver", "clearance")] == ["condition_context"]
    kinds = {(p["kind"], p["name"], p["human"], tuple(p["roles"])) for p in b["proteins"]}
    assert ("enzyme", T + "Rodent enzyme", False, ("substrate",)) in kinds
    assert ("carrier", ALB[1], True, ("other",)) in kinds


def test_pair_explained_through_the_shared_enzyme_and_transporter(client):
    body = _post(client, [B, A])
    (pair,) = body["pairs"]
    assert pair["drug_ids"] == [B, A] and pair["status"] == "explained_by_shared_protein"
    first = pair["explanations"][0]
    assert (first["protein_kind"], first["protein_id"], first["mechanism"], first["perpetrator_id"],
            first["victim_id"], first["effect"]) == ("enzyme", CYP[0], "inhibition", A, B, "victim_exposure_may_increase")
    assert [e["strength"] for e in first["evidence"]] == ["strong", ""]
    pgp = [x for x in pair["explanations"] if x["protein_kind"] == "transporter"]
    assert first["directional"] is True
    assert len(pgp) == 1 and pgp[0]["effect"] == "victim_transport_may_decrease"
    assert "known_action_not_confirmed" in pgp[0]["caveats"]
    # the rodent enzyme is never part of an explanation
    assert all(x["protein_id"] != "BE9000009" for x in pair["explanations"])
    assert pair["recorded_interactions"] == [{"from_drug_id": A, "to_drug_id": B,
        "description": T + "The metabolism of Substrate drug can be decreased when combined with Inhibitor drug."}]


def test_pair_statuses(client):
    body = _post(client, [B, C, D, "DB99999"])
    st = {tuple(p["drug_ids"]): (p["status"], p["shared_proteins_without_direction"]) for p in body["pairs"]}
    assert st[(B, C)] == ("shared_protein_no_direction", [ALB[1]])
    assert st[(B, D)] == ("no_shared_protein_in_record", [])
    assert st[(D, "DB99999")][0] == "drug_not_found"
    assert len(body["pairs"]) == 6


def _assert_clean_503(r):
    assert r.status_code == 503, r.text
    assert r.json() == {"detail": "Mechanism data is temporarily unavailable; no result was produced."}
    low = r.text.lower()
    for leak in ("postgresql", "127.0.0.1", "traceback", "select ", "operationalerror", "password", "synth@"):
        assert leak not in low


def test_review_placeholders_caps_and_shared_substrate_status(synthetic_pg, synthetic_app):
    many = [(f"BE8{i:06d}", f"{T}Enzyme {i}", "Humans", "yes", "inhibitor") for i in range(205)]
    set_mechanism(synthetic_pg, {
        A: {"name": T + "Many", "route": "Not Available.", "clearance": "N/A.", "metabolism": T + "Hepatic metabolism. " * 80,
            "enzymes": many},
        B: {"name": T + "Victim", "enzymes": [("BE8000204", T + "Enzyme 204", "Humans", "yes", "substrate"),
                                             ("BE7000001", T + "Shared", "Humans", "yes", "substrate")]},
        C: {"name": T + "Other", "enzymes": [("BE7000001", T + "Shared", "Humans", "yes", "substrate")]},
    })
    body = _post(synthetic_app, [A, B, C])
    a = body["drugs"][0]
    assert [t["source_field"] for t in a["texts"]] == ["metabolism"]  # 'Not Available.' / 'N/A.' are placeholders
    assert a["organs_truncated"] is True and len(a["organs"]) == 50
    assert a["proteins_truncated"] is True and len(a["proteins"]) == 200
    st = {tuple(p["drug_ids"]): p for p in body["pairs"]}
    # the explanation uses the 205th entry even though only 200 are displayed
    assert [x["protein_id"] for x in st[(A, B)]["explanations"]] == ["BE8000204"]
    assert st[(B, C)]["status"] == "shared_substrate_only"


def test_single_drug_has_no_pairs(client):
    body = _post(client, [A])
    assert body["pairs"] == [] and body["drugs"][0]["lookup_status"] == "found"


def test_read_only_nothing_written(client, synthetic_pg):
    with synthetic_pg.connect() as conn:
        before = [conn.execute(text(f"SELECT md5(string_agg(t::text, '|' ORDER BY t::text)) FROM {tb} t")).scalar()
                  for tb in ("drugs", "drug_enzymes", "drug_transporters", "drug_carriers", "drug_interactions")]
    _post(client, [A, B, C])
    with synthetic_pg.connect() as conn:
        after = [conn.execute(text(f"SELECT md5(string_agg(t::text, '|' ORDER BY t::text)) FROM {tb} t")).scalar()
                 for tb in ("drugs", "drug_enzymes", "drug_transporters", "drug_carriers", "drug_interactions")]
    assert before == after


def test_auth(client):
    assert client.post(URL, json={"drug_ids": [A]}).status_code in (401, 403)
    assert client.post(URL, json={"drug_ids": [A]}, headers={"Authorization": "Bearer x"}).status_code == 401


@pytest.mark.parametrize("user", [PLAIN, PATIENT], ids=["no_profile", "patient"])
def test_403_without_professional_profile(client, user):
    from datetime import datetime, timedelta, timezone

    import jwt
    from src.config import settings

    token = jwt.encode({"userId": user, "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, settings.jwt_secret,
                       algorithm="HS256")
    r = client.post(URL, json={"drug_ids": [A]}, headers={"Authorization": "Bearer " + token})
    assert r.status_code == 403


@pytest.mark.parametrize("body", [{}, {"drug_ids": []}, {"drug_ids": [A, A]}, {"drug_ids": ["DB1"]},
                                  {"drug_ids": [A], "extra": 1}, {"drug_ids": [f"DB{i:05d}" for i in range(11)]}])
def test_422(client, body):
    assert client.post(URL, json=body, headers=_auth()).status_code == 422


def test_503_when_the_database_is_unreachable(client, broken_db):
    _assert_clean_503(client.post(URL, json={"drug_ids": [A, B]}, headers=_auth()))


def test_503_on_a_query_error_mid_read(client, monkeypatch):
    from src.timing import repository

    real_begin = repository._begin_read_only
    calls = {"n": 0}

    def begin_then_fail(session):
        real_begin(session)
        calls["n"] += 1
        if calls["n"] == 2:
            session.execute(text("SELECT no_such_column_m03 FROM drug_enzymes"))

    monkeypatch.setattr(repository, "_begin_read_only", begin_then_fail)
    _assert_clean_503(client.post(URL, json={"drug_ids": [A, B]}, headers=_auth()))


def test_astra_another_drug_named_in_the_record_is_recognised_from_drugbank_names(synthetic_pg, synthetic_app):
    """The other drug's name comes from the drugs table itself (here a synthetic record
    renamed 'Zorvatinib'); the record's own name is never 'another drug'."""
    set_mechanism(synthetic_pg, {
        A: {"name": "Quellamide", "route": T + "Zorvatinib is mainly excreted in urine. Quellamide is eliminated in feces."},
        C: {"name": "Zorvatinib"},
    })
    body = _post(synthetic_app, [A])
    organs = {o["organ"]: o for o in body["drugs"][0]["organs"]}
    assert "other_drug_named" in organs["kidney"]["notes"] and organs["kidney"]["other_drugs"] == ["Zorvatinib"]
    assert organs["bile_feces"]["notes"] == [] and organs["bile_feces"]["other_drugs"] == []
