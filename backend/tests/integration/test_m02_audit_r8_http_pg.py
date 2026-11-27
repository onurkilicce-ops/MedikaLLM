"""Independent delivery audit fixes through HTTP -> auth -> service ->
SYNTHETIC PostgreSQL -> JSON: B1 (anaphor after another drug), N4 (search is
normalised like the stored lower() columns), N5 (control characters are a 422,
not a driver-level 500). All data SYNTHETIC."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import requires_synthetic_pg
from .test_m02_audit_http_pg import A, B, C, _auth, _post, _reasons, _set

pytestmark = requires_synthetic_pg
T = "[SYNTHETIC] "


def test_b1_anaphor_after_another_drug_http(synthetic_pg, synthetic_app):
    _set(synthetic_pg, {A: ("[SYNTHETIC] Drug A", "", T + "Drug B was studied. Its half-life is 6 hours."),
                        B: ("[SYNTHETIC] Drug B", "", ""),
                        C: ("[SYNTHETIC] Drug A", "", T + "Drug A was studied. Its half-life is 6 hours.")})
    res = _post(synthetic_app, [A, B, C])
    assert res[A]["measurements"] == [] and res[A]["derived"] == []
    assert "subject_unresolved" in _reasons(res[A])
    (m,) = res[C]["measurements"]
    assert m["review_required"] is False and m["hours"]["value"] == 6.0
    assert res[C]["derived"][0]["status"] == "computed"


def test_n4_search_matches_stored_lower_case_synonym(synthetic_pg, synthetic_app):
    from src.db.sql_models import Drug, DrugSynonym

    _set(synthetic_pg, {A: ("[SYNTHETIC] Drug A", "", "")})
    with Session(synthetic_pg) as s:
        drug = s.scalars(select(Drug).where(Drug.drug_id == A)).one()
        s.add(DrugSynonym(drug_pk=drug.id, synonym="[SYNTHETIC] Süßholz", synonym_lower="[synthetic] süßholz"))
        s.commit()
    r = synthetic_app.get("/api/timing/drugs", params={"q": "Süß"}, headers=_auth())
    assert r.status_code == 200
    assert [x["drug_id"] for x in r.json()["items"]] == [A]


def test_n5_control_characters_are_rejected_before_the_database(synthetic_pg, synthetic_app):
    for q in ("ci\x00pro", "ci\x07pro"):
        r = synthetic_app.get("/api/timing/drugs", params={"q": q}, headers=_auth())
        assert r.status_code == 422
