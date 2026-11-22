"""Tiny SYNTHETIC drug dataset for tests and local end-to-end checks.

Safety: ``reset_and_seed`` drops and recreates every table, so it refuses to
run unless the database name ends in ``_synth``. It must never be pointed at
the application database. Drug ids are public DrugBank identifiers; every
text field is written for testing and marked "[SYNTHETIC TEST RECORD]" — it is
not DrugBank content and has no clinical meaning.

Usage (manual e2e):
    python -m tests.integration.synthetic_data postgresql://synth@127.0.0.1:55432/medicallm_synth
"""
from __future__ import annotations

import sys
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TAG = "[SYNTHETIC TEST RECORD]"

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


def assert_synthetic(url: str) -> None:
    dbname = (urlparse(url).path or "").lstrip("/")
    if not dbname.endswith("_synth"):
        raise RuntimeError(f"Refusing to modify database '{dbname}': name must end with '_synth'.")


def reset_and_seed(url: str) -> None:
    assert_synthetic(url)
    import json

    from src.db.sql_models import (
        Base,
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
        user = UserRecord(user_id="synthetic-patient-user", email="synthetic.patient@synthetic-medicallm.org",
                          email_canonical="synthetic.patient@synthetic-medicallm.org",
                          password="!", name="Synthetic Patient")
        s.add(user)
        s.flush()
        s.add(PatientRecord(patient_id=PATIENT_ID, user_pk=user.id,
                            current_medications=json.dumps(PATIENT_MEDS)))
        s.commit()
    engine.dispose()


if __name__ == "__main__":  # pragma: no cover - manual helper
    reset_and_seed(sys.argv[1])
    print("synthetic dataset ready")
