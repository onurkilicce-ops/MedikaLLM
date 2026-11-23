"""R1-O1: contracts C3 (change password) and C2 (existing-patient analysis).

Two layers:
  * stub layer (``app_with_stubs``): status-code mapping and "the service is
    not reached" checks, no database;
  * synthetic PostgreSQL layer (``synthetic_app``): the real SQL, real bcrypt
    hashes and real access policy against fictitious accounts in a throw-away
    ``*_synth`` database (see synthetic_data.py for the reset guard).

Nothing here is clinical validation: interaction texts are synthetic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from .conftest import requires_synthetic_pg
from .synthetic_data import (
    ACCOUNTS,
    PATIENT2_ID,
    PATIENT2_MEDS,
    PATIENT_ID,
    PATIENT_MEDS,
    SYNTH_EMAIL_DOMAIN,
    SYNTH_PASSWORD,
    account_email,
)

NEW_PASSWORD = "Synth-New-Pass-2!"
CHANGE = "/api/auth/change-password"
ANALYZE = "/api/drugs/analyze-patient"


def _token(user_id: str, *, expired: bool = False, secret: str | None = None) -> str:
    from src.config import settings

    exp = datetime.now(timezone.utc) + (timedelta(hours=-1) if expired else timedelta(hours=1))
    return jwt.encode({"userId": user_id, "exp": exp}, secret or settings.jwt_secret, algorithm="HS256")


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _body(current: str = SYNTH_PASSWORD, new: str = NEW_PASSWORD) -> dict:
    return {"current_password": current, "new_password": new}


# ============================================================================
# C3 — stub layer
# ============================================================================

@pytest.fixture
def change_spy(monkeypatch):
    calls = []

    def _spy(*args, **kwargs):
        calls.append(args)

    monkeypatch.setattr("src.auth.router.change_password", _spy)
    return calls


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic c3ludGg6c3ludGg="},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Bearer "},
    ],
    ids=["no-header", "basic-scheme", "malformed", "empty-bearer"],
)
def test_c3_missing_or_broken_token_is_401_and_service_not_called(app_with_stubs, change_spy, headers):
    res = app_with_stubs.post(CHANGE, json=_body(), headers=headers)
    assert res.status_code == 401
    assert change_spy == []


def test_c3_expired_token_is_401(app_with_stubs, change_spy):
    res = app_with_stubs.post(CHANGE, json=_body(), headers=_bearer(_token("u1", expired=True)))
    assert res.status_code == 401
    assert res.json()["detail"] == "Token expired"
    assert change_spy == []


def test_c3_token_signed_with_another_secret_is_401(app_with_stubs, change_spy):
    res = app_with_stubs.post(
        CHANGE, json=_body(), headers=_bearer(_token("u1", secret="another-secret-not-the-server-one"))
    )
    assert res.status_code == 401
    assert change_spy == []


@pytest.mark.parametrize(
    "new_password",
    ["short1!", "alllowercase1!", "ALLUPPERCASE1!", "NoDigits!!", "NoSpecial123"],
)
def test_c3_weak_new_password_is_422_and_service_not_called(app_with_stubs, change_spy, new_password):
    res = app_with_stubs.post(CHANGE, json=_body(new=new_password), headers=_bearer(_token("u1")))
    assert res.status_code == 422
    assert change_spy == []


def test_c3_missing_fields_is_422(app_with_stubs, change_spy):
    res = app_with_stubs.post(CHANGE, json={"new_password": NEW_PASSWORD}, headers=_bearer(_token("u1")))
    assert res.status_code == 422
    assert change_spy == []


def test_c3_db_failure_is_an_explicit_500_not_success(app_with_stubs, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("synthetic database failure")

    monkeypatch.setattr("src.auth.router.change_password", _boom)
    res = app_with_stubs.post(CHANGE, json=_body(), headers=_bearer(_token("u1")))
    assert res.status_code == 500
    assert res.json() == {"detail": "Password change failed"}
    assert "synthetic database failure" not in res.text


def test_c3_valid_token_for_missing_user_is_401(app_with_stubs):
    # app_with_stubs' fake session returns None for every .first(): no user row.
    res = app_with_stubs.post(CHANGE, json=_body(), headers=_bearer(_token("user_gone")))
    assert res.status_code == 401
    assert res.json()["detail"] == "User not found"


# ============================================================================
# C3 — synthetic PostgreSQL
# ============================================================================

def _hashes(engine) -> dict[str, str]:
    from sqlalchemy import text

    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT user_id, password FROM users")).all())


def _login(client, key: str, password: str):
    return client.post("/api/auth/login", json={"email": account_email(key), "password": password})


@requires_synthetic_pg
def test_c3_success_changes_only_this_user_old_fails_new_works(synthetic_app, synthetic_pg):
    client = synthetic_app
    login = _login(client, "patient2", SYNTH_PASSWORD)
    assert login.status_code == 200
    token = login.json()["token"]
    before = _hashes(synthetic_pg)

    res = client.post(CHANGE, json=_body(), headers=_bearer(token))

    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True and isinstance(body["message"], str) and body["message"]
    after = _hashes(synthetic_pg)
    me = ACCOUNTS["patient2"][0]
    assert after[me] != before[me]
    assert {k: v for k, v in after.items() if k != me} == {k: v for k, v in before.items() if k != me}
    assert _login(client, "patient2", SYNTH_PASSWORD).status_code == 401
    assert _login(client, "patient2", NEW_PASSWORD).status_code == 200
    # Another account that shared the same old password is untouched.
    assert _login(client, "doctor_assigned", SYNTH_PASSWORD).status_code == 200


@requires_synthetic_pg
@pytest.mark.parametrize(
    "body, headers_kind, expected",
    [
        (_body(current="Wrong-Pass-9!"), "valid", 400),
        (_body(new="weakpass"), "valid", 422),
        (_body(), "expired", 401),
        (_body(), "none", 401),
    ],
    ids=["wrong-current", "weak-new", "expired-token", "no-token"],
)
def test_c3_failed_attempts_change_nothing(synthetic_app, synthetic_pg, body, headers_kind, expected):
    user_id = ACCOUNTS["patient2"][0]
    headers = {
        "valid": _bearer(_token(user_id)),
        "expired": _bearer(_token(user_id, expired=True)),
        "none": {},
    }[headers_kind]
    before = _hashes(synthetic_pg)

    res = synthetic_app.post(CHANGE, json=body, headers=headers)

    assert res.status_code == expected
    assert _hashes(synthetic_pg) == before
    assert _login(synthetic_app, "patient2", SYNTH_PASSWORD).status_code == 200


@requires_synthetic_pg
def test_c3_account_without_bcrypt_hash_is_400_not_500(synthetic_app, synthetic_pg):
    # The seeded patient-1 user has the disabled-account marker "!".
    before = _hashes(synthetic_pg)
    res = synthetic_app.post(CHANGE, json=_body(), headers=_bearer(_token("synthetic-patient-user")))
    assert res.status_code == 400
    assert _hashes(synthetic_pg) == before


@requires_synthetic_pg
def test_c3_commit_failure_is_500_and_record_unchanged(synthetic_app, synthetic_pg, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from src.db import sql_client

    real_factory = sql_client._SessionLocal

    def _failing_session():
        s = real_factory()

        def _commit():
            raise OperationalError("COMMIT", {}, Exception("synthetic commit failure"))

        s.commit = _commit
        return s

    monkeypatch.setattr("src.auth.service.get_session", _failing_session)
    before = _hashes(synthetic_pg)

    res = synthetic_app.post(CHANGE, json=_body(), headers=_bearer(_token(ACCOUNTS["patient2"][0])))

    assert res.status_code == 500
    assert res.json() == {"detail": "Password change failed"}
    assert _hashes(synthetic_pg) == before


@requires_synthetic_pg
def test_c3_unreachable_database_is_500(synthetic_app, synthetic_pg, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    dead = create_engine("postgresql://synth@127.0.0.1:1/none_synth", connect_args={"connect_timeout": 2})
    monkeypatch.setattr("src.auth.service.get_session", sessionmaker(bind=dead))
    before = _hashes(synthetic_pg)

    res = synthetic_app.post(CHANGE, json=_body(), headers=_bearer(_token(ACCOUNTS["patient2"][0])))

    assert res.status_code == 500
    assert _hashes(synthetic_pg) == before
    dead.dispose()


# ============================================================================
# C2 — stub layer
# ============================================================================

@pytest.fixture
def analyze_spy(monkeypatch):
    """Records calls to the analysis service; returns a minimal valid response."""
    from src.drugs import service
    from src.drugs.models import AnalyzePatientResponse

    calls = []

    def _spy(request):
        calls.append(request)
        return AnalyzePatientResponse(patient_id=request.patient_id, status="no_record")

    monkeypatch.setattr(service, "analyze_patient", _spy)
    return calls


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-jwt"}],
    ids=["no-token", "malformed-token"],
)
def test_c2_unauthenticated_is_401_and_service_not_called(app_with_stubs, analyze_spy, headers):
    res = app_with_stubs.post(ANALYZE, json={"patient_id": PATIENT_ID}, headers=headers)
    assert res.status_code == 401
    assert analyze_spy == []


def test_c2_expired_token_is_401(app_with_stubs, analyze_spy):
    res = app_with_stubs.post(ANALYZE, json={"patient_id": PATIENT_ID}, headers=_bearer(_token("u1", expired=True)))
    assert res.status_code == 401
    assert analyze_spy == []


def test_c2_access_check_db_error_is_500_and_service_not_called(app_with_stubs, analyze_spy, monkeypatch):
    from unittest.mock import MagicMock

    import src.auth.dependencies as deps
    from src.auth.models import User

    monkeypatch.setattr(deps, "get_user_by_id", lambda uid: User(
        user_id=uid, email=f"x@{SYNTH_EMAIL_DOMAIN}", password="!", name="x",
        created_at="", updated_at="", is_doctor=True, is_patient=False, patient_id=None,
    ))
    broken = MagicMock()
    broken.query.side_effect = RuntimeError("synthetic database failure")
    monkeypatch.setattr("src.db.sql_client._SessionLocal", lambda: broken)

    res = app_with_stubs.post(ANALYZE, json={"patient_id": PATIENT_ID}, headers=_bearer(_token("u1")))

    assert res.status_code == 500
    assert "synthetic database failure" not in res.text
    assert analyze_spy == []


# ============================================================================
# C2 — synthetic PostgreSQL
# ============================================================================

def _uid(key: str) -> str:
    return ACCOUNTS[key][0]


def _meds(engine, patient_id: str) -> str:
    from sqlalchemy import text

    with engine.connect() as conn:
        return conn.execute(
            text("SELECT current_medications FROM patients WHERE patient_id = :p"), {"p": patient_id}
        ).scalar_one()


@pytest.fixture
def real_analyze_spy(monkeypatch):
    """Counts calls but runs the real analysis against the synthetic DB."""
    from src.drugs import service

    real = service.analyze_patient
    calls = []

    def _spy(request):
        calls.append(request.patient_id)
        return real(request)

    monkeypatch.setattr(service, "analyze_patient", _spy)
    return calls


@requires_synthetic_pg
def test_c2_assigned_doctor_gets_the_existing_response_shape(synthetic_app, synthetic_pg, real_analyze_spy):
    from src.drugs.models import AnalyzePatientResponse

    meds_before = _meds(synthetic_pg, PATIENT_ID)
    res = synthetic_app.post(
        ANALYZE,
        json={"patient_id": PATIENT_ID, "additional_drug_ids": ["DB01211"]},
        headers=_bearer(_token(_uid("doctor_assigned"))),
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == set(AnalyzePatientResponse.model_fields)
    assert body["patient_id"] == PATIENT_ID
    assert body["status"] in {"found", "no_record", "incomplete", "unresolved", "error"}
    assert body["status"] != "error", body.get("error")
    assert body["safe_alternatives"] == []
    assert body["alternatives_note"]
    assert "Xyzzyl" in body["unresolved_medications"]
    assert body["interactions"], "synthetic warfarin+aspirin record expected"
    for rec in body["interactions"]:
        assert rec["severity"] is None and rec["severity_status"] == "not_rated"
        assert rec["description"].startswith("[SYNTHETIC TEST RECORD]")
        assert rec["source_url"].startswith("https://go.drugbank.com/drugs/")
    assert real_analyze_spy == [PATIENT_ID]
    # The analysis never writes to the recorded medication list.
    assert _meds(synthetic_pg, PATIENT_ID) == meds_before


@requires_synthetic_pg
def test_c2_patient_can_analyze_own_record(synthetic_app, synthetic_pg, real_analyze_spy):
    login = _login(synthetic_app, "patient2", SYNTH_PASSWORD)
    res = synthetic_app.post(ANALYZE, json={"patient_id": PATIENT2_ID}, headers=_bearer(login.json()["token"]))
    assert res.status_code == 200, res.text
    assert res.json()["patient_id"] == PATIENT2_ID
    assert real_analyze_spy == [PATIENT2_ID]
    import json

    assert json.loads(_meds(synthetic_pg, PATIENT2_ID)) == PATIENT2_MEDS


@requires_synthetic_pg
@pytest.mark.parametrize(
    "caller, patient_id",
    [
        ("doctor_other", PATIENT_ID),        # doctor not assigned to patient 1
        ("doctor_assigned", PATIENT2_ID),    # doctor assigned to someone else
        ("patient2", PATIENT_ID),            # another patient's record
        ("plain", PATIENT_ID),               # account without any profile
        ("plain", PATIENT2_ID),
    ],
)
def test_c2_unauthorized_callers_get_403_and_service_not_called(
    synthetic_app, synthetic_pg, real_analyze_spy, caller, patient_id
):
    meds_before = _meds(synthetic_pg, patient_id)
    res = synthetic_app.post(ANALYZE, json={"patient_id": patient_id}, headers=_bearer(_token(_uid(caller))))
    assert res.status_code == 403
    assert real_analyze_spy == []
    assert _meds(synthetic_pg, patient_id) == meds_before
    # No patient data leaks into the error body.
    assert "Coumadin" not in res.text and "current_drugs" not in res.text


@requires_synthetic_pg
def test_c2_external_id_equal_to_internal_key_is_not_the_patient(synthetic_app, synthetic_pg, real_analyze_spy):
    """The seeded collision account's external user_id is str(patient-1's
    internal users.id). The old check ``str(patient.user_pk) == user_id``
    would have granted it 'self' access."""
    from sqlalchemy import text

    with synthetic_pg.connect() as conn:
        patient_user_pk = conn.execute(
            text("SELECT user_pk FROM patients WHERE patient_id = :p"), {"p": PATIENT_ID}
        ).scalar_one()
        collision = conn.execute(
            text("SELECT user_id FROM users WHERE email = :e"), {"e": f"synthetic.collision@{SYNTH_EMAIL_DOMAIN}"}
        ).scalar_one()
    assert collision == str(patient_user_pk)

    res = synthetic_app.post(ANALYZE, json={"patient_id": PATIENT_ID}, headers=_bearer(_token(collision)))
    assert res.status_code == 403
    assert real_analyze_spy == []


@requires_synthetic_pg
def test_c2_unknown_patient_is_404_and_service_not_called(synthetic_app, real_analyze_spy):
    res = synthetic_app.post(
        ANALYZE, json={"patient_id": "synthetic-patient-missing"}, headers=_bearer(_token(_uid("doctor_assigned")))
    )
    assert res.status_code == 404
    assert real_analyze_spy == []


@requires_synthetic_pg
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"patient_id": 123},
        {"patient_id": PATIENT_ID, "additional_drug_ids": "DB00945"},
        {"patient_id": PATIENT_ID, "additional_drug_ids": [1, 2]},
    ],
    ids=["empty", "numeric-id", "ids-not-list", "ids-not-strings"],
)
def test_c2_wrong_body_is_422_and_service_not_called(synthetic_app, real_analyze_spy, body):
    res = synthetic_app.post(ANALYZE, json=body, headers=_bearer(_token(_uid("doctor_assigned"))))
    assert res.status_code == 422
    assert real_analyze_spy == []


@requires_synthetic_pg
def test_c2_token_for_deleted_user_is_401(synthetic_app, real_analyze_spy):
    res = synthetic_app.post(ANALYZE, json={"patient_id": PATIENT_ID}, headers=_bearer(_token("synthetic-no-such-user")))
    assert res.status_code == 401
    assert real_analyze_spy == []


@requires_synthetic_pg
def test_shared_policy_matches_patient_details(synthetic_pg):
    """get_patient_details (chat patient context) and analyze-patient use the
    same resolve_patient_access policy: one decision, two consumers."""
    from src.db.sql_client import get_session
    from src.users import service as users

    cases = [(k, p) for k in ACCOUNTS for p in (PATIENT_ID, PATIENT2_ID)]
    for key, patient_id in cases:
        s = get_session()
        try:
            _, outcome = users.resolve_patient_access(s, patient_id, _uid(key))
        finally:
            s.close()
        details = users.get_patient_details(patient_id, _uid(key))
        assert (details is not None) == (outcome in users.PATIENT_ACCESS_GRANTED), (key, patient_id)
    granted = {
        (k, p) for k, p in cases
        if users.get_patient_details(p, _uid(k)) is not None
    }
    assert granted == {("doctor_assigned", PATIENT_ID), ("doctor_other", PATIENT2_ID), ("patient2", PATIENT2_ID)}
    assert PATIENT_MEDS  # dataset sanity


# ============================================================================
# Reset guard for the synthetic database (no DROP outside a throw-away DB)
# ============================================================================

@pytest.mark.parametrize(
    "url, confirm, message",
    [
        ("postgresql://u@127.0.0.1:5432/medicallm", "medicallm", "must end with '_synth'"),
        ("postgresql://u@db.example.org:5432/x_synth", "x_synth", "only a loopback"),
        ("postgresql://u@127.0.0.1:5432/x_synth", "", "MEDICALLM_SYNTHETIC_PG_CONFIRM"),
        ("postgresql://u@127.0.0.1:5432/x_synth", "other_synth", "MEDICALLM_SYNTHETIC_PG_CONFIRM"),
    ],
    ids=["name", "remote-host", "no-confirm", "wrong-confirm"],
)
def test_reset_guard_refuses_before_connecting(monkeypatch, url, confirm, message):
    from .synthetic_data import CONFIRM_ENV, assert_safe_to_reset

    monkeypatch.setenv(CONFIRM_ENV, confirm)
    with pytest.raises(RuntimeError, match=message):
        assert_safe_to_reset(url)


@requires_synthetic_pg
def test_reset_guard_refuses_a_database_with_non_synthetic_users(synthetic_pg):
    from sqlalchemy import text

    from .conftest import SYNTHETIC_PG_URL
    from .synthetic_data import assert_safe_to_reset

    with synthetic_pg.begin() as conn:
        conn.execute(text(
            "INSERT INTO users (user_id, email, password, name, is_premium) "
            "VALUES ('guard-probe', 'guard-probe@example.invalid', '!', 'guard probe', false)"
        ))
    try:
        with pytest.raises(RuntimeError, match="non-synthetic user"):
            assert_safe_to_reset(SYNTHETIC_PG_URL)
    finally:
        with synthetic_pg.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE user_id = 'guard-probe'"))
    assert_safe_to_reset(SYNTHETIC_PG_URL)  # clean again


# ============================================================================
# R1-O1-D1 / D2 — new password over bcrypt's 72-byte limit -> 422, not 500
# ============================================================================

PW_ASCII_72 = "Aa1!" + "x" * 68
PW_ASCII_73 = "Aa1!" + "x" * 69
PW_UTF8_72 = "Aa1!" + "ü" * 34   # 38 chars, 72 bytes
PW_UTF8_74 = "Aa1!" + "ü" * 35   # 39 chars, 74 bytes


@pytest.mark.parametrize("new_password", [PW_ASCII_73, PW_UTF8_74], ids=["ascii-73B", "utf8-74B"])
def test_d2_over_72_bytes_is_422_and_service_not_called(app_with_stubs, change_spy, new_password):
    res = app_with_stubs.post(CHANGE, json=_body(new=new_password), headers=_bearer(_token("u1")))
    assert res.status_code == 422
    assert "72 bytes" in res.text
    assert change_spy == []


@requires_synthetic_pg
@pytest.mark.parametrize("new_password", [PW_ASCII_73, PW_UTF8_74], ids=["ascii-73B", "utf8-74B"])
def test_d2_over_72_bytes_changes_nothing(synthetic_app, synthetic_pg, new_password):
    before = _hashes(synthetic_pg)
    res = synthetic_app.post(CHANGE, json=_body(new=new_password), headers=_bearer(_token(ACCOUNTS["patient2"][0])))
    assert res.status_code == 422
    assert _hashes(synthetic_pg) == before
    assert _login(synthetic_app, "patient2", SYNTH_PASSWORD).status_code == 200


@requires_synthetic_pg
@pytest.mark.parametrize("new_password", [PW_ASCII_72, PW_UTF8_72], ids=["ascii-72B", "utf8-72B"])
def test_d2_exactly_72_bytes_works_end_to_end(synthetic_app, synthetic_pg, new_password):
    before = _hashes(synthetic_pg)
    res = synthetic_app.post(CHANGE, json=_body(new=new_password), headers=_bearer(_token(ACCOUNTS["patient2"][0])))
    assert res.status_code == 200, res.text
    me = ACCOUNTS["patient2"][0]
    after = _hashes(synthetic_pg)
    assert after[me] != before[me]
    assert {k: v for k, v in after.items() if k != me} == {k: v for k, v in before.items() if k != me}
    assert _login(synthetic_app, "patient2", SYNTH_PASSWORD).status_code == 401
    assert _login(synthetic_app, "patient2", new_password).status_code == 200
    # The full secret is used, not a prefix: dropping the last character fails.
    assert _login(synthetic_app, "patient2", new_password[:-1]).status_code == 401


# ============================================================================
# R1-O1-D1 / D3 — signed token without a usable userId -> 401, not 500
# ============================================================================

def _claims_token(claims: dict) -> str:
    from src.config import settings

    body = {"exp": datetime.now(timezone.utc) + timedelta(hours=1), **claims}
    return jwt.encode(body, settings.jwt_secret, algorithm="HS256")


_BAD_ID_CLAIMS = [
    ({}, "missing"),
    ({"userId": None}, "null"),
    ({"userId": ""}, "empty"),
    ({"userId": "   "}, "blank"),
    ({"userId": 123}, "int"),
    ({"userId": ["synthetic-patient2-user"]}, "list"),
    ({"userId": {"id": "synthetic-patient2-user"}}, "object"),
    ({"user_id": "synthetic-patient2-user"}, "wrong-claim-name"),
]
_BAD_ID_PARAMS = dict(argvalues=[c for c, _ in _BAD_ID_CLAIMS], ids=[i for _, i in _BAD_ID_CLAIMS])


@pytest.mark.parametrize("claims", **_BAD_ID_PARAMS)
def test_d3_verify_token_rejects_unusable_user_id(claims):
    from src.auth.service import verify_token

    with pytest.raises(ValueError, match="Invalid token"):
        verify_token(_claims_token(claims))


def test_d3_verify_token_keeps_valid_expired_and_bad_signature_behaviour():
    from src.auth.service import verify_token

    assert verify_token(_token("user_0f3c")) == "user_0f3c"
    assert verify_token(_token("legacy-id-123")) == "legacy-id-123"  # format not narrowed
    with pytest.raises(ValueError, match="Token expired"):
        verify_token(_token("user_0f3c", expired=True))
    with pytest.raises(ValueError, match="Invalid token"):
        verify_token(_token("user_0f3c", secret="another-secret-not-the-server-one"))


@pytest.fixture
def db_session_spy(monkeypatch):
    """Records every attempt to open a DB session (none expected)."""
    from src.db import sql_client

    opened = []

    def _factory():
        opened.append(1)
        raise AssertionError("no DB session expected for an unusable token")

    monkeypatch.setattr(sql_client, "_SessionLocal", _factory)
    return opened


@pytest.mark.parametrize("claims", **_BAD_ID_PARAMS)
def test_d3_change_password_unusable_user_id_is_401_no_service_no_db(
    app_with_stubs, change_spy, db_session_spy, claims
):
    res = app_with_stubs.post(CHANGE, json=_body(), headers=_bearer(_claims_token(claims)))
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid token"
    assert change_spy == []
    assert db_session_spy == []


@pytest.mark.parametrize("claims", **_BAD_ID_PARAMS)
def test_d3_analyze_patient_unusable_user_id_is_401_no_service_no_db(
    app_with_stubs, analyze_spy, db_session_spy, claims
):
    res = app_with_stubs.post(ANALYZE, json={"patient_id": PATIENT_ID}, headers=_bearer(_claims_token(claims)))
    assert res.status_code == 401
    assert analyze_spy == []
    assert db_session_spy == []


# ============================================================================
# R1-O1-D1 / D1 — the reset guard checks the target the driver really uses
# ============================================================================

@pytest.fixture
def no_db_effects(monkeypatch):
    """Spy on every side effect reset_and_seed could have: engine creation
    (=> connection) and metadata DROP/CREATE. A rejected URL must hit none."""
    from src.db.sql_models import Base

    from . import synthetic_data

    calls = {"create_engine": [], "drop_all": [], "create_all": []}

    def _engine(*a, **k):
        calls["create_engine"].append(a)
        raise AssertionError("create_engine must not be reached for a rejected URL")

    monkeypatch.setattr(synthetic_data, "create_engine", _engine)
    monkeypatch.setattr(Base.metadata, "drop_all", lambda *a, **k: calls["drop_all"].append(a))
    monkeypatch.setattr(Base.metadata, "create_all", lambda *a, **k: calls["create_all"].append(a))
    for name in ("PGHOSTADDR", "PGSERVICE"):
        monkeypatch.delenv(name, raising=False)
    return calls


_D1_REJECTED = [
    # (url, confirm, expected message fragment)
    ("postgresql://audit@127.0.0.1:1/audit_synth?dbname=unapproved_app", "audit_synth", "query string"),
    ("postgresql://audit@127.0.0.1:1/audit_synth?host=unapproved.example.invalid", "audit_synth", "query string"),
    ("postgresql://audit@127.0.0.1:1/audit_synth?hostaddr=192.0.2.10", "audit_synth", "query string"),
    ("postgresql://audit@127.0.0.1:1/audit_synth?service=unapproved", "audit_synth", "query string"),
    ("postgresql://audit@127.0.0.1:1/audit_synth?options=-csearch_path%3Dother", "audit_synth", "query string"),
    ("postgresql://audit@127.0.0.1:1/audit_synth?sslmode=disable", "audit_synth", "query string"),
    ("postgresql://audit@127.0.0.1,unapproved.example.invalid:1/audit_synth", "audit_synth", "loopback"),
    ("postgresql://audit@db.example.invalid:5432/audit_synth", "audit_synth", "loopback"),
    ("postgresql:///audit_synth", "audit_synth", "loopback"),  # no host: libpq defaults/env decide
    ("postgresql://audit@127.0.0.1:1/unapproved_app", "unapproved_app", "_synth"),
    ("postgresql://audit@127.0.0.1:1/audit_synth", "", "MEDICALLM_SYNTHETIC_PG_CONFIRM"),
    ("postgresql://audit@127.0.0.1:1/audit_synth", "other_synth", "MEDICALLM_SYNTHETIC_PG_CONFIRM"),
    ("postgresql+asyncpg://audit@127.0.0.1:1/audit_synth", "audit_synth", "driver"),
    ("mysql://audit@127.0.0.1:1/audit_synth", "audit_synth", "driver"),
]


@pytest.mark.parametrize(
    "url, confirm, message",
    _D1_REJECTED,
    ids=["q-dbname", "q-host", "q-hostaddr", "q-service", "q-options", "q-sslmode", "multi-host",
         "remote-host", "no-host", "wrong-name", "no-confirm", "wrong-confirm", "asyncpg", "mysql"],
)
def test_d1_rejected_target_never_connects_drops_or_seeds(monkeypatch, no_db_effects, url, confirm, message):
    from .synthetic_data import CONFIRM_ENV, reset_and_seed

    monkeypatch.setenv(CONFIRM_ENV, confirm)
    with pytest.raises(RuntimeError, match=message):
        reset_and_seed(url)
    assert no_db_effects == {"create_engine": [], "drop_all": [], "create_all": []}


@pytest.mark.parametrize("env_name", ["PGHOSTADDR", "PGSERVICE"])
def test_d1_redirecting_libpq_env_is_rejected(monkeypatch, no_db_effects, env_name):
    from .synthetic_data import CONFIRM_ENV, reset_and_seed

    monkeypatch.setenv(CONFIRM_ENV, "audit_synth")
    monkeypatch.setenv(env_name, "192.0.2.10" if env_name == "PGHOSTADDR" else "unapproved")
    with pytest.raises(RuntimeError, match=env_name):
        reset_and_seed("postgresql://audit@127.0.0.1:1/audit_synth")
    assert no_db_effects == {"create_engine": [], "drop_all": [], "create_all": []}


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://audit@127.0.0.1:1/audit_synth",
        "postgresql+psycopg2://audit:pw@localhost:55433/audit_synth",
        "postgresql://audit@[::1]:5432/audit_synth",
    ],
    ids=["ipv4", "localhost-psycopg2", "ipv6"],
)
def test_d1_checked_target_is_the_driver_target(monkeypatch, url):
    """The accepted host/dbname are exactly what psycopg2 receives."""
    from sqlalchemy import create_engine

    from .synthetic_data import CONFIRM_ENV, resolve_reset_target

    for name in ("PGHOSTADDR", "PGSERVICE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(CONFIRM_ENV, "audit_synth")
    parsed, host, dbname = resolve_reset_target(url)
    _, driver_params = create_engine(parsed).dialect.create_connect_args(parsed)  # no connection
    assert (str(driver_params["host"]).lower(), driver_params["dbname"]) == (host, dbname)
    assert dbname == "audit_synth"
    assert not set(driver_params) & {"hostaddr", "service", "servicefile"}


def test_d1_connected_database_must_be_the_confirmed_one():
    from .synthetic_data import assert_connected_database

    class _Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class _Conn:
        def __init__(self, name):
            self.name = name

        def execute(self, *_a, **_k):
            return _Result(self.name)

    assert_connected_database(_Conn("audit_synth"), "audit_synth")
    with pytest.raises(RuntimeError, match="connected to database 'unapproved_app'"):
        assert_connected_database(_Conn("unapproved_app"), "audit_synth")


@requires_synthetic_pg
def test_d1_allowed_synthetic_target_still_resets(synthetic_pg):
    """The approved throw-away DB still passes the full guard (incl. the
    post-connect current_database() check) and was seeded."""
    from sqlalchemy import text

    from .conftest import SYNTHETIC_PG_URL
    from .synthetic_data import assert_safe_to_reset

    assert_safe_to_reset(SYNTHETIC_PG_URL)
    with synthetic_pg.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM patients")).scalar_one() == 2


def test_d1_reset_stops_when_server_reports_another_database(monkeypatch):
    """reset_and_seed itself runs the post-connect check: a connection that
    lands in another database is refused before any DROP/CREATE."""
    from contextlib import contextmanager

    from src.db.sql_models import Base

    from . import synthetic_data

    effects = {"drop_all": [], "create_all": [], "statements": []}

    class _Result:
        def scalar_one(self):
            return "unapproved_app"

    class _Conn:
        def execute(self, stmt, *_a, **_k):
            effects["statements"].append(str(stmt))
            return _Result()

    class _Engine:
        @contextmanager
        def connect(self):
            yield _Conn()

        def dispose(self):
            pass

    monkeypatch.setattr(synthetic_data, "create_engine", lambda *_a, **_k: _Engine())
    monkeypatch.setattr(Base.metadata, "drop_all", lambda *a, **k: effects["drop_all"].append(a))
    monkeypatch.setattr(Base.metadata, "create_all", lambda *a, **k: effects["create_all"].append(a))
    for name in ("PGHOSTADDR", "PGSERVICE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(synthetic_data.CONFIRM_ENV, "audit_synth")

    with pytest.raises(RuntimeError, match="connected to database 'unapproved_app'"):
        synthetic_data.reset_and_seed("postgresql://audit@127.0.0.1:1/audit_synth")
    assert effects["statements"] == ["SELECT current_database()"]  # read-only probe only
    assert effects["drop_all"] == [] and effects["create_all"] == []


# ============================================================================
# Review follow-ups: lone surrogate in a body field; out-of-range time claims
# ============================================================================

_SURROGATE_BODIES = [
    b'{"current_password":"Old1!pass","new_password":"Aa1!xxxxx\\ud800"}',
    b'{"current_password":"\\ud800","new_password":"Aa1!xxxxxx"}',
]


@pytest.mark.parametrize("raw", _SURROGATE_BODIES, ids=["new_password", "current_password"])
def test_lone_surrogate_in_password_is_422_not_500(app_with_stubs, change_spy, raw):
    res = app_with_stubs.post(
        CHANGE,
        content=raw,
        headers={**_bearer(_token("u1")), "Content-Type": "application/json"},
    )
    assert res.status_code == 422
    assert res.json()["detail"][0]["type"] == "string_unicode"
    assert change_spy == []


def test_validation_422_body_shape_is_unchanged(app_with_stubs):
    """Same JSON data as FastAPI's default handler (non-ASCII only escaped)."""
    res = app_with_stubs.post(CHANGE, json=_body(new="güçsüz"), headers=_bearer(_token("u1")))
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert isinstance(detail, list) and {"type", "loc", "msg", "input"} <= set(detail[0])
    assert detail[0]["loc"] == ["body", "new_password"]
    assert detail[0]["input"] == "güçsüz"  # round-trips exactly
    missing = app_with_stubs.post("/api/auth/login", json={})
    assert missing.status_code == 422 and [e["loc"][-1] for e in missing.json()["detail"]] == ["email", "password"]


_BAD_TIME_CLAIMS = [
    ({"userId": "u1", "exp": float("inf")}, "exp-inf"),
    ({"userId": "u1", "exp": 1e400}, "exp-1e400"),
    ({"userId": "u1", "exp": 4102444800, "nbf": float("inf")}, "nbf-inf"),
]


def _raw_claims_token(claims: dict) -> str:
    from src.config import settings

    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


@pytest.mark.parametrize("claims", [c for c, _ in _BAD_TIME_CLAIMS], ids=[i for _, i in _BAD_TIME_CLAIMS])
def test_out_of_range_time_claim_is_invalid_token(app_with_stubs, change_spy, analyze_spy, db_session_spy, claims):
    from src.auth.service import verify_token

    token = _raw_claims_token(claims)
    with pytest.raises(ValueError, match="Invalid token"):
        verify_token(token)
    assert app_with_stubs.post(CHANGE, json=_body(), headers=_bearer(token)).status_code == 401
    assert app_with_stubs.post(ANALYZE, json={"patient_id": PATIENT_ID}, headers=_bearer(token)).status_code == 401
    assert change_spy == [] and analyze_spy == [] and db_session_spy == []
