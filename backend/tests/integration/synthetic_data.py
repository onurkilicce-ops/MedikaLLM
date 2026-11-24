"""Tiny SYNTHETIC drug dataset for tests and local end-to-end checks.

Safety: ``reset_and_seed`` drops and recreates every table. A ``_synth`` name
suffix alone is NOT permission to do that. ``assert_safe_to_reset`` requires
all of:

  0. the host and database checked below are the ones the psycopg2 driver
     will really use: URL query options and redirecting libpq environment
     variables are refused, and after connecting the server must report the
     confirmed database (see ``resolve_reset_target``);
  1. the database name ends in ``_synth``;
  2. the host is a loopback address (a local server or a CI service
     container), never a remote/managed database;
  3. the operator named this exact database in
     ``MEDICALLM_SYNTHETIC_PG_CONFIRM`` (identifies the throw-away database
     created for this run);
  4. the database holds no non-synthetic users or drugs (checked with a
     read-only query before anything is dropped).

It must never be pointed at the application database. Drug ids are public
DrugBank identifiers; every text field is written for testing and marked
"[SYNTHETIC TEST RECORD]" — it is not DrugBank content and has no clinical
meaning. Users, doctors and patients below are fictitious test accounts; the
passwords are throw-away test values for this synthetic database only.

Usage (manual e2e, against a database you created for the run):
    MEDICALLM_SYNTHETIC_PG_CONFIRM=medicallm_synth \
    python -m tests.integration.synthetic_data postgresql://synth@127.0.0.1:55432/medicallm_synth
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

TAG = "[SYNTHETIC TEST RECORD]"
SYNTH_EMAIL_DOMAIN = "synthetic-medicallm.org"
CONFIRM_ENV = "MEDICALLM_SYNTHETIC_PG_CONFIRM"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_ALLOWED_DRIVERS = {"postgresql", "postgresql+psycopg2"}
# libpq environment variables that redirect a connection even when the URL
# names host and database explicitly (hostaddr wins over host; a service
# entry can supply hostaddr).
_REDIRECTING_PG_ENV = ("PGHOSTADDR", "PGSERVICE")
_REDIRECTING_PARAMS = {"hostaddr", "service", "servicefile"}

DRUGS = {
    # drug_id: (name, synonyms, brands, categories, food interactions)
    "DB00682": ("Warfarin", ["Warfarin sodium"], ["Coumadin"], ["Anticoagulants", "Coumarins"],
                [f"{TAG} Keep vitamin K intake consistent."]),
    "DB00945": ("Acetylsalicylic acid", ["Aspirin"], [], ["Platelet Aggregation Inhibitors"], []),
    "DB00316": ("Acetaminophen", ["Paracetamol"], [], ["Analgesics"], []),
    "DB01211": ("Clarithromycin", [], [], ["Anti-Bacterial Agents"], []),
    "DB01418": ("Acenocoumarol", [], [], ["Anticoagulants", "Coumarins"], []),
    "DB00006": ("Bivalirudin", [], [], ["Anticoagulants"], []),
}

# (owner drug_id, other drug_id, description). Stored once, on the owner.
INTERACTIONS = [
    ("DB00682", "DB00945", f"{TAG} The risk of bleeding can be increased when Acetylsalicylic acid is combined with Warfarin."),
    ("DB01211", "DB00682", f"{TAG} Clarithromycin may increase the anticoagulant activities of Warfarin."),
    # Same-category candidate WITH a record against aspirin -> must be excluded as an alternative.
    ("DB01418", "DB00945", f"{TAG} The risk of bleeding can be increased when Acetylsalicylic acid is combined with Acenocoumarol."),
    # Negated wording that the old text-pattern scorer rated 1.0 ("contraindicated").
    ("DB00316", "DB01211", f"{TAG} This combination is not contraindicated."),
]


# Combination product owned by Acetaminophen: its name resolves to ONE ingredient.
MIXTURES = [("DB00316", "Synthocomb Forte", "Acetaminophen, Codeine")]

# One synthetic patient: an exact brand, an exact synonym with a dose suffix
# handled by fuzzy search, an unknown name, and a combination product.
PATIENT_ID = "synthetic-patient-1"
PATIENT_MEDS = ["Coumadin", "Aspirin", "Xyzzyl", "Synthocomb Forte"]

# --- Accounts for the access-control / password tests (R1-O1) -------------
# Every account below is fictitious. Passwords satisfy the registration rules
# and exist only in this throw-away database.
SYNTH_PASSWORD = "Synth-Pass-1!"

PATIENT2_ID = "synthetic-patient-2"
PATIENT2_MEDS = ["Coumadin", "Aspirin"]

# key -> (user_id, email local part, display name, role, profile id)
ACCOUNTS = {
    "patient2": ("synthetic-patient2-user", "synthetic.patient2", "Synthetic Patient Two", "patient", PATIENT2_ID),
    "doctor_assigned": ("synthetic-doctor-a-user", "synthetic.doctor.a", "Synthetic Doctor A", "doctor", "synthetic-doctor-a"),
    "doctor_other": ("synthetic-doctor-b-user", "synthetic.doctor.b", "Synthetic Doctor B", "doctor", "synthetic-doctor-b"),
    "plain": ("synthetic-plain-user", "synthetic.plain", "Synthetic Plain User", "none", None),
}
# doctor_assigned <-> synthetic-patient-1 ; doctor_other <-> synthetic-patient-2
ASSIGNMENTS = [("doctor_assigned", PATIENT_ID), ("doctor_other", PATIENT2_ID)]


def account_email(key: str) -> str:
    return f"{ACCOUNTS[key][1]}@{SYNTH_EMAIL_DOMAIN}"


def _dbname(url: str) -> str:
    return (urlparse(url).path or "").lstrip("/")


def assert_synthetic(url: str) -> None:
    """Name check only (kept for callers that just need the name rule)."""
    dbname = _dbname(url)
    if not dbname.endswith("_synth"):
        raise RuntimeError(f"Refusing to modify database '{dbname}': name must end with '_synth'.")


def resolve_reset_target(url: str):
    """Validate the target the DRIVER will actually use, without connecting.

    The checks run on the connection parameters SQLAlchemy's psycopg2 dialect
    builds from the URL (``create_connect_args``), not on a separate parse of
    the URL text, so what is checked is what libpq receives. To keep that
    mapping unambiguous:

      * only ``postgresql`` / ``postgresql+psycopg2`` URLs are accepted;
      * ANY query-string option is refused — ``?host=``, ``?dbname=``,
        ``?hostaddr=``, ``?service=`` and friends can silently replace the
        host/database shown in the URL body;
      * libpq environment variables that redirect a connection even when host
        and database are explicit (``PGHOSTADDR``, ``PGSERVICE``) must be
        unset;
      * the resulting ``host`` must be a single loopback name/address and the
        resulting ``dbname`` must end in ``_synth`` and equal
        ``MEDICALLM_SYNTHETIC_PG_CONFIRM``.

    Returns ``(sqlalchemy_url, host, dbname)``; callers must connect with that
    exact URL object. Raises RuntimeError before any connection otherwise.
    """
    from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError

    try:
        parsed = make_url(url)
    except ArgumentError as exc:
        raise RuntimeError(f"Refusing to reset: unparseable database URL ({exc}).") from exc
    if parsed.drivername not in _ALLOWED_DRIVERS:
        raise RuntimeError(
            f"Refusing to reset: driver '{parsed.drivername}' is not one of {sorted(_ALLOWED_DRIVERS)}."
        )
    if parsed.query:
        raise RuntimeError(
            "Refusing to reset: connection options in the URL query string are not allowed "
            f"(found {sorted(parsed.query)}); they can change the real host/database."
        )
    redirecting_env = [name for name in _REDIRECTING_PG_ENV if os.environ.get(name)]
    if redirecting_env:
        raise RuntimeError(
            f"Refusing to reset: unset {', '.join(redirecting_env)}; libpq would use it to "
            "redirect the connection away from the host in the URL."
        )
    _, params = PGDialect_psycopg2().create_connect_args(parsed)
    redirecting_params = sorted(set(params) & _REDIRECTING_PARAMS)
    if redirecting_params:  # defensive: unreachable without a query string
        raise RuntimeError(f"Refusing to reset: driver options {redirecting_params} are not allowed.")
    host = str(params.get("host") or "").lower()
    dbname = str(params.get("dbname") or "")
    if not dbname.endswith("_synth"):
        raise RuntimeError(f"Refusing to modify database '{dbname}': name must end with '_synth'.")
    if host not in _LOOPBACK_HOSTS:
        raise RuntimeError(
            f"Refusing to reset '{dbname}' on host '{host or '?'}': only a loopback "
            "database created for this test run may be reset."
        )
    if os.getenv(CONFIRM_ENV, "") != dbname:
        raise RuntimeError(
            f"Refusing to reset '{dbname}': set {CONFIRM_ENV}={dbname} to confirm this "
            "is the throw-away database created for this run."
        )
    return parsed, host, dbname


def assert_connected_database(conn, expected_dbname: str) -> None:
    """Second line of defence after connecting: the server must report the
    confirmed database as the current one (catches anything that still
    redirected the session, e.g. a server-side or pooler mapping)."""
    current = conn.execute(text("SELECT current_database()")).scalar_one()
    if current != expected_dbname:
        raise RuntimeError(
            f"Refusing to reset: connected to database '{current}', expected '{expected_dbname}'."
        )


def assert_safe_to_reset(url: str):
    """All conditions from the module docstring, before any DROP.

    Returns the validated SQLAlchemy URL that the reset must use.
    """
    parsed, _host, dbname = resolve_reset_target(url)
    engine = create_engine(parsed)
    try:
        with engine.connect() as conn:
            assert_connected_database(conn, dbname)
            tables = set(inspect(conn).get_table_names())
            if "users" in tables:
                foreign_users = conn.execute(
                    text("SELECT count(*) FROM users WHERE email NOT LIKE :pat"),
                    {"pat": f"%@{SYNTH_EMAIL_DOMAIN}"},
                ).scalar_one()
                if foreign_users:
                    raise RuntimeError(
                        f"Refusing to reset '{dbname}': it contains {foreign_users} non-synthetic user(s)."
                    )
            if "drugs" in tables:
                foreign_drugs = conn.execute(
                    text("SELECT count(*) FROM drugs WHERE NOT (drug_id = ANY(:ids))"),
                    {"ids": list(DRUGS)},
                ).scalar_one()
                if foreign_drugs:
                    raise RuntimeError(
                        f"Refusing to reset '{dbname}': it contains {foreign_drugs} non-synthetic drug(s)."
                    )
    finally:
        engine.dispose()
    return parsed


def _hash(password: str) -> str:
    import bcrypt

    # Low cost factor: test-only hashes in a throw-away database.
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("utf-8")


def reset_and_seed(url: str) -> None:
    # Connect with the exact URL object that was validated.
    url = assert_safe_to_reset(url)
    import json

    from src.db.sql_models import (
        Base,
        DoctorPatientAssociation,
        DoctorRecord,
        Drug,
        DrugCategory,
        DrugFoodInteraction,
        DrugGroup,
        DrugInteraction,
        DrugInternationalBrand,
        DrugMixture,
        DrugSynonym,
        PatientRecord,
        UserRecord,
    )

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    with Session() as s:
        by_id: dict[str, Drug] = {}
        for drug_id, (name, synonyms, brands, categories, foods) in DRUGS.items():
            d = Drug(drug_id=drug_id, name=name, name_lower=name.lower(), drug_type="small molecule",
                     description=f"{TAG} {name} test entry.", indication=f"{TAG} test indication.")
            d.synonyms = [DrugSynonym(synonym=x, synonym_lower=x.lower()) for x in synonyms]
            d.international_brands = [DrugInternationalBrand(brand_name=x, brand_name_lower=x.lower()) for x in brands]
            d.categories = [DrugCategory(category=c, category_lower=c.lower()) for c in categories]
            d.groups = [DrugGroup(group_name="approved")]
            d.food_interactions = [DrugFoodInteraction(interaction=f) for f in foods]
            s.add(d)
            by_id[drug_id] = d
        s.flush()
        for owner, other, desc in INTERACTIONS:
            s.add(DrugInteraction(drug1_id=by_id[owner].id, drug2_drugbank_id=other,
                                  drug2_name=DRUGS[other][0], description=desc))
        for owner, mixture_name, ingredients in MIXTURES:
            s.add(DrugMixture(drug_pk=by_id[owner].id, mixture_name=mixture_name,
                              mixture_name_lower=mixture_name.lower(), ingredients=ingredients))
        user = UserRecord(user_id="synthetic-patient-user", email=f"synthetic.patient@{SYNTH_EMAIL_DOMAIN}",
                          email_canonical=f"synthetic.patient@{SYNTH_EMAIL_DOMAIN}",
                          password="!", name="Synthetic Patient")
        s.add(user)
        s.flush()
        patient1 = PatientRecord(patient_id=PATIENT_ID, user_pk=user.id,
                                 current_medications=json.dumps(PATIENT_MEDS))
        s.add(patient1)
        s.flush()

        password_hash = _hash(SYNTH_PASSWORD)
        records: dict[str, UserRecord] = {}
        doctors: dict[str, DoctorRecord] = {}
        patients: dict[str, PatientRecord] = {PATIENT_ID: patient1}
        for key, (user_id, _local, name, role, profile_id) in ACCOUNTS.items():
            rec = UserRecord(user_id=user_id, email=account_email(key), email_canonical=account_email(key),
                             password=password_hash, name=name)
            s.add(rec)
            s.flush()
            records[key] = rec
            if role == "patient":
                p = PatientRecord(patient_id=profile_id, user_pk=rec.id,
                                  current_medications=json.dumps(PATIENT2_MEDS))
                s.add(p)
                s.flush()
                patients[profile_id] = p
            elif role == "doctor":
                d = DoctorRecord(doctor_id=profile_id, user_pk=rec.id, specialty=f"{TAG}")
                s.add(d)
                s.flush()
                doctors[key] = d
        for doctor_key, patient_id in ASSIGNMENTS:
            s.add(DoctorPatientAssociation(doctor_pk=doctors[doctor_key].id,
                                           patient_pk=patients[patient_id].id))
        # A user whose EXTERNAL id is the decimal string of patient 1's
        # INTERNAL user key. The old analyze-patient check compared
        # str(PatientRecord.user_pk) with the JWT user id and would have
        # treated this account as the patient themselves.
        s.add(UserRecord(user_id=str(user.id), email=f"synthetic.collision@{SYNTH_EMAIL_DOMAIN}",
                         email_canonical=f"synthetic.collision@{SYNTH_EMAIL_DOMAIN}",
                         password=password_hash, name="Synthetic Id Collision"))
        s.commit()
    engine.dispose()


if __name__ == "__main__":  # pragma: no cover - manual helper
    reset_and_seed(sys.argv[1])
    print("synthetic dataset ready")
