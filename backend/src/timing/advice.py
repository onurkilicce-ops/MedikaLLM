"""Manually checked label statements. No LLM, PK inference or runtime web fetch.

Matching uses the database's canonical drug name, not a user-supplied name.
Profiles are explicit confirmations of the exact product/route/formulation;
an active ingredient alone cannot select a profile. See SOURCES.md.
"""
from itertools import combinations
from . import repository
from .advice_models import (AdviceRequest, AdviceResponse, AdviceCoverage, EvidenceAdvice,
                            EvidenceSource, ProductProfile)
from .models import Quantity

PROFILES = {
    "cipro_uk_tablet": (('ciprofloxacin', 'ciprofloxacin hydrochloride'), ProductProfile(
        profile_id="cipro_uk_tablet", label="Ciprofloxacin 500 mg tablet — Ranbaxy/Sun (UK)",
        route="oral", formulation="500 mg film-coated tablet", jurisdiction="UK")),
    "ciproxin_uk_suspension": (('ciprofloxacin', 'ciprofloxacin hydrochloride'), ProductProfile(
        profile_id="ciproxin_uk_suspension", label="Ciproxin 250 mg/5 mL suspension — Bayer (UK)",
        route="oral", formulation="250 mg/5 mL oral suspension", jurisdiction="UK")),
    "sucralfate_oral": (('sucralfate',), ProductProfile(
        profile_id="sucralfate_oral", label="Sucralfate — oral preparation",
        route="oral", formulation="oral preparation", jurisdiction="context of UK ciprofloxacin label")),
    "levothyroxine_us_tablet": (('levothyroxine', 'levothyroxine sodium'), ProductProfile(
        profile_id="levothyroxine_us_tablet", label="Levothyroxine sodium 100 mcg tablet — Proficient Rx/Lannett (US)",
        route="oral", formulation="100 mcg tablet", jurisdiction="US")),
}

SOURCES = {
    "cipro_dd": EvidenceSource(source_ref="emc:4346:4.5", url="https://www.medicines.org.uk/emc/product/4346/smpc",
        title="Ciprofloxacin 500 mg film-coated tablets (Ranbaxy/Sun)",
        section="4.5 — Chelation Complex Formation", label_updated="2026-10-15",
        excerpt="Consequently, ciprofloxacin should be administered either 1-2 hours before or at least 4 hours after these preparations."),
    "cipro_food": EvidenceSource(source_ref="emc:885:4.5", url="https://www.medicines.org.uk/emc/product/885/smpc",
        title="Ciproxin 250 mg/5 mL oral suspension (Bayer)",
        section="4.5 — Food and Dairy Products (also 4.2)", label_updated="2026-10-15",
        excerpt="ciprofloxacin oral suspension could be administered either 1-2 hours before or at least 4 hours after dairy products or mineral-fortified drinks"),
    "levothyroxine_food": EvidenceSource(source_ref="dailymed:9e588c43-b9b5-478e-99f7-e197add3cd26:2.1",
        url="https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=9e588c43-b9b5-478e-99f7-e197add3cd26",
        title="Levothyroxine sodium tablet — Proficient Rx LP / Lannett",
        section="2.1 — General Administration Information", label_updated="2025-08-01",
        excerpt="Administer levothyroxine sodium tablets as a single daily dose, on an empty stomach, one-half to one hour before breakfast."),
}

FOOD_LABELS = {"breakfast": "Breakfast", "dairy_alone": "Dairy outside meals",
               "calcium_drink_alone": "Calcium-fortified drink outside meals", "dairy_in_meal": "Dairy within a meal"}


def canonical_name(name):
    # Test records must retain this explicit tag in the synthetic database.
    # This is not fuzzy matching, a synonym inference or chemical equivalence.
    return name.removeprefix("[SYNTHETIC] ").removeprefix("[SYNTHETIC TEST RECORD] ").strip().casefold()


def profiles_for(name):
    return [profile for names, profile in PROFILES.values() if canonical_name(name) in names]


def evaluate(body: AdviceRequest) -> AdviceResponse:
    rows, _ = repository.read_timing_data(body.drug_ids, lambda _: [])
    chosen = {x.drug_id: x.profile_id for x in body.contexts}
    # Invalid/mismatched assertions are not silently accepted or guessed.
    for drug_id, profile_id in chosen.items():
        if profile_id not in PROFILES:
            raise ValueError("Unknown product profile")
        if drug_id in rows and profile_id not in {p.profile_id for p in profiles_for(rows[drug_id].name)}:
            raise ValueError("Product profile does not match the selected drug")
    advice, coverage = [], []

    def cover(ids, status, reason):
        coverage.append(AdviceCoverage(item_ids=ids, status=status, reason=reason))

    def add(subject, other, kind, name, source, conditions, rule, directions):
        for direction, interval in directions:
            advice.append(EvidenceAdvice(rule_id=rule, subject_drug_id=subject, other_kind=kind,
                other_id=other, other_name=name, direction=direction, interval_hours=interval,
                conditions=conditions, source=SOURCES[source]))

    cipro_intervals = [("before", Quantity(kind="range", lower=1, upper=2)),
                       ("after", Quantity(kind="lower_bound", lower=4, inclusive=True))]
    for a, b in combinations(body.drug_ids, 2):
        if a not in rows or b not in rows:
            cover([a, b], "drug_not_found", "At least one drug is missing from the database.")
            continue
        names = {canonical_name(rows[a].name): a, canonical_name(rows[b].name): b}
        cipro = next((names[n] for n in ('ciprofloxacin', 'ciprofloxacin hydrochloride') if n in names), None)
        suc = names.get('sucralfate')
        if not (cipro and suc):
            cover([a, b], "not_in_catalog", "No matching drug-pair timing rule in this catalog.")
        elif chosen.get(cipro) != "cipro_uk_tablet" or chosen.get(suc) != "sucralfate_oral":
            cover([a, b], "conditions_required", "Confirm the UK 500 mg tablet profile and oral sucralfate; other products are not covered here.")
        else:
            add(cipro, suc, "drug", rows[suc].name, "cipro_dd",
                ["Ciprofloxacin 500 mg film-coated tablet, Ranbaxy/Sun UK; oral sucralfate.",
                 "Absorption interaction; this interval is not evidence that all co-use risks are resolved."],
                "cipro-tablet-sucralfate", cipro_intervals)
            cover([a, b], "matched", "Directional intervals from the specified product label.")
    for drug_id in body.drug_ids:
        for food in body.foods:
            ids = [drug_id, food]
            if drug_id not in rows:
                cover(ids, "drug_not_found", "Drug is missing from the database.")
                continue
            name = canonical_name(rows[drug_id].name)
            if name in ('ciprofloxacin', 'ciprofloxacin hydrochloride') and food != 'breakfast':
                if chosen.get(drug_id) != "ciproxin_uk_suspension":
                    cover(ids, "conditions_required", "The sourced numeric food interval requires the Ciproxin UK suspension profile.")
                elif food == 'dairy_in_meal':
                    cover(ids, "not_applicable", "This spacing rule is for dairy outside meals. No general safety conclusion is made for a meal.")
                else:
                    add(drug_id, food, "food", FOOD_LABELS[food], "cipro_food",
                        ["Bayer Ciproxin UK 250 mg/5 mL oral suspension.",
                         "Dairy or calcium-fortified drink consumed alone OUTSIDE meals; not applied to dairy within a meal."],
                        "cipro-suspension-food", cipro_intervals)
                    cover(ids, "matched", "Outside-meal conditions explicitly selected.")
            elif name in ('levothyroxine', 'levothyroxine sodium') and food == 'breakfast':
                if chosen.get(drug_id) != "levothyroxine_us_tablet":
                    cover(ids, "conditions_required", "Confirm the specified oral levothyroxine sodium tablet profile.")
                else:
                    add(drug_id, food, "food", FOOD_LABELS[food], "levothyroxine_food",
                        ["Proficient Rx/Lannett US 100 mcg oral tablet; empty stomach, before breakfast.",
                         "No interval after breakfast is inferred."], "levothyroxine-breakfast",
                        [("before", Quantity(kind="range", lower=0.5, upper=1))])
                    cover(ids, "matched", "Breakfast interval from section 2.1.")
            else:
                cover(ids, "not_in_catalog", "No matching drug-food timing rule in this catalog.")
    pending = any(x.status in ('conditions_required', 'drug_not_found') for x in coverage)
    status = 'partially_evaluated' if pending and advice else 'not_evaluated' if pending else 'evaluated'
    return AdviceResponse(status=status, advice=advice, coverage=coverage)
