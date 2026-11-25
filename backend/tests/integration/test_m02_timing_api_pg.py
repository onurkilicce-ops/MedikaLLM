"""M-02 ``POST /api/timing/compare``: HTTP -> auth -> service -> SYNTHETIC
PostgreSQL -> response.

Runs on the shared throw-away ``*_synth`` database (``synthetic_pg`` /
``synthetic_app`` fixtures, unchanged). After the shared seed, this module
overwrites the timing text of the already-seeded synthetic drug ids with
SYNTHETIC wording and renames them "[SYNTHETIC] Timing Agent ..." so nothing
here can be read as real drug data. The next reset drops everything again.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from .conftest import requires_synthetic_pg
from .synthetic_data import ACCOUNTS

pytestmark = requires_synthetic_pg

URL = "/api/timing/compare"
TAG = "[SYNTHETIC TEST RECORD]"
A, B, C, D, E, F = "DB00006", "DB00316", "DB00682", "DB00945", "DB01211", "DB01418"
UNKNOWN1, UNKNOWN2 = "DB99998", "DB99999"  # valid format, not in the synthetic DB

DOCTOR = ACCOUNTS["doctor_assigned"][0]
PLAIN = ACCOUNTS["plain"][0]
PATIENT = ACCOUNTS["patient2"][0]

TRUNCATED_HALF_LIFE = (f"{TAG} The elimination half-life is 4 hours. " + "Filler sentence. " * 70)[:999] + "1"
assert len(TRUNCATED_HALF_LIFE) == 1000

TIMING_TEXT = {
    # drug_id: (name, absorption, half_life)
    A: ("[SYNTHETIC] Timing Agent A",
        f"{TAG} Peak plasma concentrations are reached within 0.5-1 hours after oral administration.[A900001]",
        f"{TAG} The elimination half-life is 4-6 hours.[A900002]"),
    B: ("[SYNTHETIC] Timing Agent B",
        f"{TAG} Absorption is extensive; bioavailability is about 60%.",
        f"{TAG} The half-life is 90 minutes in healthy adults and 3 hours in patients with renal impairment.[L900003]"),
    C: ("[SYNTHETIC] Timing Agent C", "Not Available", ""),
    D: ("[SYNTHETIC] Timing Agent D", f"{TAG} Tmax is 2 hours.", TRUNCATED_HALF_LIFE),
    E: ("[SYNTHETIC] Timing Agent E", "", "1-2 days"),
    F: ("[SYNTHETIC] Timing Agent F", f"{TAG} Maximum therapeutic effect is seen after 2-3 weeks.",
        f"{TAG} The half-life of the active metabolite is 20 hours."),
}
# (drug, ref_id, ref_type, citation). A900099 is a general reference that no
# sentence cites: it must never be attached to a value.
REFERENCES = [
    (A, "A900001", "article", f"{TAG} Synthetic absorption study."),
    (A, "A900002", "article", f"{TAG} Synthetic elimination study."),
    (A, "A900099", "article", f"{TAG} Synthetic general reference, not cited inline."),
]


def _token(user_id: str, *, expired: bool = False) -> str:
    from src.config import settings

    exp = datetime.now(timezone.utc) + (timedelta(hours=-1) if expired else timedelta(hours=1))
    return jwt.encode({"userId": user_id, "exp": exp}, settings.jwt_secret, algorithm="HS256")


def _auth(user_id: str = DOCTOR) -> dict:
    return {"Authorization": f"Bearer {_token(user_id)}"}


@pytest.fixture
def m02(synthetic_pg, synthetic_app):
    from src.db.sql_models import Drug, DrugReference

    with Session(synthetic_pg) as s:
        drugs = {d.drug_id: d for d in s.scalars(select(Drug).where(Drug.drug_id.in_(list(TIMING_TEXT))))}
        assert set(drugs) == set(TIMING_TEXT)
        for drug_id, (name, absorption, half_life) in TIMING_TEXT.items():
            d = drugs[drug_id]
            d.name, d.name_lower = name, name.lower()
            d.absorption, d.half_life = absorption, half_life
        for drug_id, ref_id, ref_type, citation in REFERENCES:
            s.add(DrugReference(drug_pk=drugs[drug_id].id, ref_type=ref_type, ref_id=ref_id, citation=citation))
        s.commit()
    return synthetic_app, synthetic_pg


def _snapshot(engine) -> dict:
    tables = ["drugs", "drug_references", "drug_interactions", "users", "patients", "doctors",
              "conversations", "doctor_patient_associations"]
    with engine.connect() as conn:
        out = {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in tables}
        out["drugs_text"] = conn.execute(
            text("SELECT md5(string_agg(drug_id || coalesce(half_life,'') || coalesce(absorption,'') || name, '|' "
                 "ORDER BY drug_id)) FROM drugs")).scalar_one()
        out["patients_meds"] = conn.execute(
            text("SELECT md5(string_agg(patient_id || current_medications, '|' ORDER BY patient_id)) FROM patients")
        ).scalar_one()
    return out


def _by_id(body: dict) -> dict:
    return {d["requested_id"]: d for d in body["drugs"]}


# ---------------------------------------------------------------------------
# 200 - sourced values
# ---------------------------------------------------------------------------

def test_two_drugs_sourced_values_order_and_separate_derived(m02):
    client, _ = m02
    r = client.post(URL, json={"drug_ids": [B, A]}, headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_version"] == "m02-timing-compare/2"
    assert body["parser_version"] == "m02-text-parser/2"
    assert [d["requested_id"] for d in body["drugs"]] == [B, A]
    assert [d["position"] for d in body["drugs"]] == [0, 1]
    assert body["timing_advice"] == {
        "status": "not_evaluated", "advice": [],
        "note": body["timing_advice"]["note"],
    }
    assert "not a statement that no source exists" in body["timing_advice"]["note"]
    codes = {lim["code"] for lim in body["limitations"]}
    assert {"tmax_not_added", "five_half_lives_is_an_approximation", "timing_advice_not_evaluated",
            "no_expert_acceptance", "general_references_not_linked"} <= codes

    a = _by_id(body)[A]
    assert a["lookup_status"] == "found"
    assert a["drug"] == {"drug_id": A, "name": "[SYNTHETIC] Timing Agent A",
                         "source_record_url": f"https://go.drugbank.com/drugs/{A}"}
    assert a["data_status"] == {"tmax": "parsed", "half_life": "parsed"}
    tmax = [m for m in a["measurements"] if m["measure_type"] == "tmax"]
    half = [m for m in a["measurements"] if m["measure_type"] == "half_life"]
    assert len(tmax) == 1 and len(half) == 1
    t, h = tmax[0], half[0]
    assert t["hours"] == {"kind": "range", "value": None, "lower": 0.5, "upper": 1.0, "inclusive": None}
    assert t["time_reference"] == "after_administration"
    assert t["conditions"]["route"] == ["oral"]
    assert t["source"]["source_field"] == "absorption"
    assert t["source"]["value_text"] == "0.5-1 hours"
    stored_abs = TIMING_TEXT[A][1]
    assert stored_abs[t["source"]["value_start"]:t["source"]["value_end"]] == "0.5-1 hours"
    assert stored_abs[t["source"]["quote_start"]:t["source"]["quote_end"]] == t["source"]["quote"]
    assert t["source"]["reference_status"] == "matched"
    assert t["source"]["reference_scope"] == "sentence_single_value"
    assert t["source"]["stored_reference_attributed"] is True
    assert [ref["ref_id"] for ref in t["source"]["references"]] == ["A900001"]
    assert t["source"]["references"][0]["citation"] == f"{TAG} Synthetic absorption study."

    assert h["hours"] == {"kind": "range", "value": None, "lower": 4.0, "upper": 6.0, "inclusive": None}
    assert h["original"]["unit"] == "hours"
    assert h["time_reference"] == "not_applicable_duration"
    assert [ref["ref_id"] for ref in h["source"]["references"]] == ["A900002"]
    # The uncited general reference is attached nowhere.
    assert "A900099" not in r.text

    assert len(a["derived"]) == 1
    d = a["derived"][0]
    assert d["based_on_measurement_id"] == h["measurement_id"]
    assert d["status"] == "computed"
    assert d["hours"] == {"kind": "range", "value": None, "lower": 20.0, "upper": 30.0, "inclusive": None}
    assert d["includes_tmax"] is False
    assert "first_order_exponential_decline" in d["assumptions"]
    # Tmax (0.5-1 h) is not added: 20.5 / 31 never appear.
    assert d["hours"]["lower"] != 20.5 and d["hours"]["upper"] != 31.0
    # No positive "eliminated / effect over / safe" claim anywhere in the response.
    # (the timing_advice note itself is a negation: "not a statement that no source exists ...")
    low = r.text.lower().replace(body["timing_advice"]["note"].lower(), "")
    for banned in ("is safe", "safe to", "completely eliminated", "fully eliminated", "effect is over",
                   "has left the body", "no interaction", "no source"):
        assert banned not in low, banned

    b = _by_id(body)[B]
    assert b["data_status"] == {"tmax": "no_statement_found", "half_life": "parsed"}
    halves = [m for m in b["measurements"] if m["measure_type"] == "half_life"]
    assert [m["hours"]["value"] for m in halves] == [1.5, 3.0]
    assert halves[0]["original"] == {"kind": "point", "value": 90.0, "lower": None, "upper": None,
                                     "inclusive": None, "unit": "minutes", "lower_unit": None}
    # Each population stays with its own value.
    assert halves[0]["conditions"]["population"] == ["healthy adults"]
    assert halves[1]["conditions"]["population"] == ["patients with renal impairment"]
    # Token present, but no reference row of this drug has that id.
    assert halves[0]["source"]["reference_status"] == "unmatched"
    assert halves[0]["source"]["unmatched_reference_tokens"] == ["L900003"]
    assert halves[0]["source"]["reference_scope"] == "sentence_shared"  # one token, two values
    assert halves[0]["source"]["stored_reference_attributed"] is False
    assert [x["hours"] for x in b["derived"]] == [
        {"kind": "point", "value": 7.5, "lower": None, "upper": None, "inclusive": None},
        {"kind": "point", "value": 15.0, "lower": None, "upper": None, "inclusive": None},
    ]
    assert "no_tmax_statement_in_absorption_text" in b["limitations"]


def test_missing_and_unusable_timing_data_are_explicit_200(m02):
    client, _ = m02
    r = client.post(URL, json={"drug_ids": [C, D, E, F]}, headers=_auth())
    assert r.status_code == 200, r.text
    res = _by_id(r.json())

    c = res[C]
    assert c["lookup_status"] == "found"
    assert c["data_status"] == {"tmax": "placeholder", "half_life": "empty"}
    assert c["measurements"] == [] and c["derived"] == []
    assert {f["source_field"]: f["stored_text"] for f in c["fields"]} == {"absorption": "Not Available",
                                                                         "half_life": ""}

    d = res[D]
    assert d["data_status"]["tmax"] == "parsed"
    assert d["data_status"]["half_life"] == "parsed_needs_review"
    half_field = next(f for f in d["fields"] if f["source_field"] == "half_life")
    assert half_field["stored_text_length"] == 1000 and half_field["stored_text_possibly_truncated"] is True
    assert "sentence_possibly_truncated" in {i["reason"] for i in half_field["review_items"]}
    (hd,) = d["derived"]
    assert hd["status"] == "not_computed" and hd["hours"] is None
    assert "stored_text_possibly_truncated" in hd["not_computed_reasons"]
    assert "half_life_text_possibly_truncated" in d["limitations"]

    e = res[E]
    (em,) = e["measurements"]
    assert em["measure_basis"] == "field_only"
    assert em["hours"] == {"kind": "range", "value": None, "lower": 24.0, "upper": 48.0, "inclusive": None}
    assert e["derived"][0]["hours"]["lower"] == 120.0 and e["derived"][0]["hours"]["upper"] == 240.0
    assert e["data_status"]["tmax"] == "empty"

    f = res[F]
    assert [m["measure_type"] for m in f["measurements"]] == ["half_life"]  # effect duration is not Tmax
    assert f["data_status"]["tmax"] == "unparsed_needs_review"
    (fd,) = f["derived"]
    assert fd["status"] == "not_computed" and "metabolite_not_parent" in fd["not_computed_reasons"]
    for drug in res.values():
        for m in drug["measurements"]:
            for k in ("value", "lower", "upper"):
                assert m["hours"][k] != 0


def test_unknown_ids_are_per_drug_not_found_200(m02):
    client, _ = m02
    r = client.post(URL, json={"drug_ids": [UNKNOWN1, A, UNKNOWN2]}, headers=_auth())
    assert r.status_code == 200
    drugs = r.json()["drugs"]
    assert [d["lookup_status"] for d in drugs] == ["not_found", "found", "not_found"]
    for d in (drugs[0], drugs[2]):
        assert d["drug"] is None and d["data_status"] is None
        assert d["fields"] == [] and d["measurements"] == [] and d["derived"] == []
        assert d["limitations"] == ["drug_id_not_in_database"]


def test_all_unknown_is_200_with_every_drug_not_found(m02):
    client, _ = m02
    r = client.post(URL, json={"drug_ids": [UNKNOWN2, UNKNOWN1]}, headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert [d["requested_id"] for d in body["drugs"]] == [UNKNOWN2, UNKNOWN1]
    assert {d["lookup_status"] for d in body["drugs"]} == {"not_found"}
    assert body["timing_advice"]["status"] == "not_evaluated"


def test_ten_drugs_is_the_technical_limit_and_order_is_kept(m02):
    client, _ = m02
    ids = [F, UNKNOWN1, A, B, "DB90001", C, D, "DB90002", E, UNKNOWN2]
    r = client.post(URL, json={"drug_ids": ids}, headers=_auth())
    assert r.status_code == 200
    assert [d["requested_id"] for d in r.json()["drugs"]] == ids


# ---------------------------------------------------------------------------
# 401 / 403 / 422
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer not-a-jwt"},
    {"Authorization": "Basic c3ludGg6c3ludGg="},
], ids=["no_token", "garbage_token", "not_bearer"])
def test_401_without_valid_token(m02, headers):
    client, _ = m02
    r = client.post(URL, json={"drug_ids": [A, B]}, headers=headers)
    assert r.status_code == 401


def test_missing_token_with_invalid_body_follows_fastapi_order(m02):
    """Documented in API.md: the auth dependency is resolved before the body
    here, so no token + invalid body is 401 (FastAPI order left unchanged)."""
    client, _ = m02
    assert client.post(URL, json={"drug_ids": [A]}).status_code == 401


def test_401_expired_token_and_deleted_user(m02):
    client, _ = m02
    expired = {"Authorization": f"Bearer {_token(DOCTOR, expired=True)}"}
    assert client.post(URL, json={"drug_ids": [A, B]}, headers=expired).status_code == 401
    ghost = client.post(URL, json={"drug_ids": [A, B]}, headers=_auth("synthetic-no-such-user"))
    assert ghost.status_code == 401


@pytest.mark.parametrize("user", [PLAIN, PATIENT], ids=["no_profile", "patient"])
def test_403_signed_in_without_professional_profile(m02, user):
    client, _ = m02
    r = client.post(URL, json={"drug_ids": [A, B]}, headers=_auth(user))
    assert r.status_code == 403
    assert "measurements" not in r.text


@pytest.mark.parametrize("body", [
    {"drug_ids": [A]},
    {"drug_ids": []},
    {"drug_ids": [A, B, C, D, E, F, "DB90001", "DB90002", "DB90003", "DB90004", "DB90005"]},
    {"drug_ids": [A, A]},
    {"drug_ids": [A, "db00316"]},
    {"drug_ids": [A, " DB00316"]},
    {"drug_ids": [A, "DB0031"]},
    {"drug_ids": [A, "DB003166"]},
    {"drug_ids": [A, "Paracetamol"]},
    {"drug_ids": [A, 316]},
    {"drug_ids": f"{A},{B}"},
    {"drug_ids": [A, B], "patient_id": "synthetic-patient-1"},
    {"drug_ids": [A, B], "dose_mg": 500},
    {},
], ids=["one", "empty", "eleven", "duplicate", "lowercase", "whitespace", "short", "long", "name",
        "number", "string", "patient_field", "dose_field", "missing"])
def test_422_invalid_body_is_rejected_not_fixed(m02, body):
    client, _ = m02
    r = client.post(URL, json=body, headers=_auth())
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 503 - database errors are never "not found" or an empty success
# ---------------------------------------------------------------------------

@pytest.fixture
def broken_db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.db import sql_client

    engine = create_engine("postgresql://synth@127.0.0.1:1/none_synth", connect_args={"connect_timeout": 2})
    monkeypatch.setattr(sql_client, "_SessionLocal", sessionmaker(bind=engine))
    yield
    engine.dispose()


def _assert_clean_503(r):
    assert r.status_code == 503, r.text
    assert r.json() == {"detail": "Timing data is temporarily unavailable; no result was produced."}
    low = r.text.lower()
    for leak in ("postgresql", "127.0.0.1", "traceback", "select ", "operationalerror", "password", "synth@"):
        assert leak not in low


def test_503_when_the_user_lookup_cannot_reach_the_database(m02, broken_db):
    client, _ = m02
    _assert_clean_503(client.post(URL, json={"drug_ids": [A, B]}, headers=_auth()))


def test_503_when_the_drug_read_fails_after_auth(m02, monkeypatch, broken_db):
    client, _ = m02
    from src.timing import repository

    monkeypatch.setattr(repository, "read_professional_flag", lambda user_id: True)
    _assert_clean_503(client.post(URL, json={"drug_ids": [A, UNKNOWN1]}, headers=_auth()))


def test_503_on_a_query_error_mid_read(m02, monkeypatch):
    """A failing SQL statement (not only a dead connection) is also 503."""
    client, _ = m02
    from src.timing import repository

    real_begin = repository._begin_read_only
    calls = {"n": 0}

    def begin_then_fail_on_data_read(session):
        real_begin(session)
        calls["n"] += 1
        if calls["n"] == 2:  # 1 = user lookup (succeeds), 2 = drug read
            session.execute(text("SELECT no_such_column_m02 FROM drugs"))

    monkeypatch.setattr(repository, "_begin_read_only", begin_then_fail_on_data_read)
    _assert_clean_503(client.post(URL, json={"drug_ids": [A, B]}, headers=_auth()))
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Read-only, no LLM, only the needed columns
# ---------------------------------------------------------------------------

def test_request_writes_nothing_and_runs_read_only_transactions(m02):
    client, engine = m02
    before = _snapshot(engine)
    statements = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _capture)
    try:
        for ids in ([A, B], [C, D, E, F], [UNKNOWN1, UNKNOWN2]):
            assert client.post(URL, json={"drug_ids": ids}, headers=_auth()).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", _capture)
    assert _snapshot(engine) == before
    joined = "\n".join(statements).upper()
    for verb in ("INSERT", "UPDATE ", "DELETE", "ALTER", "CREATE", "DROP", "TRUNCATE"):
        assert verb not in joined, verb
    assert joined.count("SET TRANSACTION READ ONLY") >= 6  # auth + data read, per request
    # Only the drug columns and the cited references are read; no interactions,
    # products or patient tables.
    for table in ("DRUG_INTERACTIONS", "DRUG_PRODUCTS", "DRUG_FOOD_INTERACTIONS", "PATIENTS", "CONVERSATIONS"):
        assert table not in joined, table


def test_no_llm_or_agent_is_called(m02, monkeypatch):
    client, _ = m02
    from unittest.mock import MagicMock

    from src.main import app

    agent = MagicMock()
    monkeypatch.setattr(app.state, "medical_agent", agent, raising=False)

    def _forbidden(*a, **k):
        raise AssertionError("LLM client must not be constructed by M-02")

    monkeypatch.setattr("openai.OpenAI.__init__", _forbidden)
    monkeypatch.setattr("openai.AsyncOpenAI.__init__", _forbidden)
    r = client.post(URL, json={"drug_ids": [A, B]}, headers=_auth())
    assert r.status_code == 200
    assert agent.mock_calls == []


def test_db_is_read_only_inside_the_m02_transaction(m02):
    """The guard itself: a write inside the transaction M-02 opens is refused
    by PostgreSQL."""
    _, engine = m02
    from sqlalchemy.exc import InternalError, ProgrammingError, DBAPIError

    from src.db import sql_client
    from src.timing import repository

    session = sql_client.get_session()
    try:
        repository._begin_read_only(session)
        with pytest.raises((InternalError, ProgrammingError, DBAPIError)) as exc:
            session.execute(text("UPDATE drugs SET name = name"))
        assert "read-only" in str(exc.value).lower()
    finally:
        session.rollback()
        session.close()
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(text("drugs"))).scalar_one() == 6


def test_openapi_documents_the_contract(m02):
    client, _ = m02
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/api/timing/compare"]["post"]
    assert {"200", "401", "403", "422", "429", "503"} <= set(op["responses"])
    schemas = spec["components"]["schemas"]
    for name in ("TimingCompareRequest", "TimingCompareResponse", "TimingMeasurement", "DerivedDuration",
                 "SourceExcerpt", "Conditions", "TimingAdvice"):
        assert name in schemas, name
    # Always-present response fields are required in the schema (no "maybe missing" arrays).
    assert {"route", "population", "other", "analyte"} <= set(schemas["Conditions"]["required"])
    assert {"status", "advice", "note"} <= set(schemas["TimingAdvice"]["required"])
    assert {"includes_tmax", "hours", "not_computed_reasons", "assumptions"} <= set(
        schemas["DerivedDuration"]["required"])
    assert {"reference_scope", "stored_reference_attributed", "references"} <= set(
        schemas["SourceExcerpt"]["required"])
    assert {"kind", "value", "lower", "upper", "inclusive"} <= set(schemas["Quantity"]["required"])
    assert {"schema_version", "drugs", "timing_advice", "limitations"} <= set(
        schemas["TimingCompareResponse"]["required"])
    req = schemas["TimingCompareRequest"]
    assert req["additionalProperties"] is False
    assert req["properties"]["drug_ids"]["minItems"] == 2 and req["properties"]["drug_ids"]["maxItems"] == 10
