"""M02 independent delivery audit, fixes B1 and N1 (parser /10).

B1: an anaphoric or absent subject ('Its half-life', 'Half-life: 6 hours',
'Both have') inherits from the nearest earlier text that carries DRUG-SHAPED
evidence ('drug b', 'compound c', 'drugs B and C', 'the formulation of drug b').
Descriptive sentences ('Cmax is 200 ng/mL', 'The tablet contains lactose')
carry no owner. A definite 'The half-life' does not inherit. N1: salt / cross-reference / measure parentheses and pharmacokinetic
section labels are not owners; a possessive 's is not a name word.
Expectations written before the fix was run. Every text is SYNTHETIC.
"""
from __future__ import annotations

import pytest

from src.timing import calc
from src.timing.advice import SOURCES
from src.timing.parser import PARSER_VERSION, parse_field

S = "[SYNTHETIC] "


def _p(text, field="half_life", rec="Drug A"):
    return parse_field(field, S + text, stored_max_length=1000, subject_names=["[SYNTHETIC] " + rec])


def _clean(fp):
    return [v for v in fp.values if not v.review_reasons]


def _unresolved(fp):
    reasons = {r.reason for r in fp.reviews} | {x for v in fp.values for x in v.review_reasons}
    derived = [calc.five_half_lives(v, fp.flags) for v in fp.values if v.measure_type == "half_life"]
    return _clean(fp) == [] and all(d["status"] == "not_computed" for d in derived) and bool(
        reasons & {"subject_unresolved", "subject_not_record_drug"})


def test_parser_version_bumped_for_behaviour_change():
    assert int(PARSER_VERSION.rsplit("/", 1)[1]) >= 10


# ------------------------------------------------------------------ B1 --
@pytest.mark.parametrize("text", [
    "Drug B was studied. Its half-life is 6 hours.",
    "Drug A is well absorbed. Drug B is a prodrug. Its half-life is 6 hours.",
    "Drug B is a prodrug; its half-life is 6 hours.",
    "Drug B is a prodrug, and its half-life is 6 hours.",
    "drug b was studied. Its half-life is 6 hours.",
    "Drug B 10 mg. Half-life: 6 hours.",
    "drug b is a prodrug; their half-life is 6 hours.",
    "Drug B inhibits CYP3A4. Its half-life is 6 hours.",
    "In vitro studies indicate that drug b is a substrate. Its half-life is 6 hours.",
    "The formulation of drug b was studied. Its half-life is 6 hours.",
    "The formulation of drug b was studied and it has a half-life of 6 hours.",
])
def test_b1_anaphor_after_another_drug_is_not_the_record_value(text):
    assert _unresolved(_p(text))


@pytest.mark.parametrize("text", [
    "Drug A was studied. Its half-life is 6 hours.",
    "drug a is a prodrug; its half-life is 6 hours.",
    "The drug is well absorbed. Its half-life is 6 hours.",
    "Drug A 10 mg. Half-life: 6 hours.",
    "In vitro studies indicate that Drug A is a substrate. Its half-life is 6 hours.",
    # a definite 'The half-life' is the record field's own statement: no inheritance
    "Drug b is a CYP3A4 inhibitor. The half-life is 6 hours.",
    "Coadministration of drug b did not alter the pharmacokinetics. The half-life is 6 hours.",
    "In a study with drug b, no interaction was observed. The half-life is 6 hours.",
    "Absolute bioavailability is 90% in healthy volunteers. The half-life is 6 hours.",
])
def test_b1_record_or_generic_owner_stays_clean(text):
    (v,) = _clean(_p(text))
    assert v.hours.value == 6.0


def test_b1_absent_subject_after_a_neutral_sentence_stays_clean():
    (v,) = _clean(_p("Absolute bioavailability is 90% in healthy volunteers. Tmax is 1 hour.", field="absorption"))
    assert v.hours.value == 1.0


# B1 regression set from the adversarial probe of the first /10 draft
# (verbs outside a list, comma splices, anaphor chains, plural anaphors,
# 'Unlike Drug A, compound C ...').
@pytest.mark.parametrize("text", [
    "Drug B penetrates the CNS. Its half-life is 6 hours.",
    "Drug B crosses the placenta. Its half-life is 6 hours.",
    "Drug B accumulates in fat. Its half-life is 6 hours.",
    "Drug B distributes widely. Its half-life is 6 hours.",
    "Drug B circulates widely. Half-life: 6 hours.",
    "Drug B circulates widely. Half-life (terminal): 6 hours.",
    "Drug B is a prodrug, its half-life is 6 hours.",
    "Drug B is a prodrug, half-life 6 hours.",
    "Drug B is a prodrug, it has a half-life of 6 hours.",
    "Drug B is a prodrug. It is converted to an active metabolite. Its half-life is 6 hours.",
    "Drug B is a prodrug. The tablets should be swallowed whole. Its half-life is 6 hours.",
    "Drug B and compound C were coadministered. Both had a half-life of 6 hours.",
    "Drug B and compound C were coadministered. These have a half-life of 6 hours.",
    "Drug B and compound C were coadministered; each has a half-life of 6 hours.",
    "Drugs B and C penetrate the CNS. Their half-life is 6 hours.",
    "Unlike Drug A, compound C circulates widely. Its half-life is 6 hours.",
    "Compound C, unlike Drug A, circulates widely. Its half-life is 6 hours.",
    "Compound C circulates widely, and its half-life is 6 hours.",
    "Compound C circulates widely: its half-life is 6 hours.",
    "Compound C circulates widely - its half-life is 6 hours.",
    "Compound C circulates widely (its half-life is 6 hours).",
    "Drug B was given with Drug A; the former has a half-life of 6 hours.",
    "The tablet contains Drug B. Its half-life is 6 hours.",
])
def test_b1_probe_another_drug_is_never_inherited_as_clean(text):
    assert _unresolved(_p(text))


@pytest.mark.parametrize("text", [
    "Drug A tablets contain lactose. Half-life: 6 hours.",
    "Pharmacokinetic properties: Absorption is rapid. Half-life: 6 hours.",
    "Pharmacokinetic properties: The half-life is 6 hours.",
    "The volume of distribution is 50 L. Its half-life is 6 hours.",
    "Cmax is 200 ng/mL. Half-life: 6 hours.",
    "Healthy volunteers received 10 mg. Its half-life is 6 hours.",
    "The tablet contains lactose. Its half-life is 6 hours.",
    "Linear pharmacokinetics were observed. Its half-life is 6 hours.",
    "Glucuronidation is the main pathway. Its half-life is 6 hours.",
    "High-fat food reduces Cmax by 20%. Its half-life is 6 hours.",
    "Gender has no clinically relevant effect. Its half-life is 6 hours.",
    "Systemic exposure increases proportionally and its half-life is 6 hours.",
    "Drug A is a prodrug. It is converted to an active metabolite. Its half-life is 6 hours.",
    "Hemodialysis does not remove drug A. Its half-life is 6 hours.",
    "Drug A binds to albumin; its half-life is 6 hours.",
])
def test_b1_probe_descriptive_previous_text_stays_clean(text):
    (v,) = _clean(_p(text))
    assert v.hours.value == 6.0


# ------------------------------------------------------------------ N1 --
@pytest.mark.parametrize("text", [
    "Excretion: Mainly renal. The half-life is 6 hours.",
    "Metabolism: Extensive. The half-life is 6 hours.",
    "Protein binding: 90%. The half-life is 6 hours.",
    "Drug A (hydrochloride) has a half-life of 6 hours.",
    "Drug A (as sodium) has a half-life of 6 hours.",
    "Drug A (see section 5.2) has a half-life of 6 hours.",
    "Peak levels occur at 2 hours (Tmax). The half-life is 6 hours.",
    "drug a's mean terminal elimination half-life is 6 hours.",
])
def test_n1_ordinary_label_structures_stay_clean(text):
    clean = _clean(_p(text))
    assert any(v.hours.value == 6.0 for v in clean)


@pytest.mark.parametrize("text", [
    "drug b (hydrochloride) has a half-life of 6 hours.",
    "drug b's mean terminal elimination half-life is 6 hours.",
    "The tablet (drug b) has a half-life of 6 hours.",
])
def test_n1_the_same_structures_with_another_drug_stay_unresolved(text):
    assert _unresolved(_p(text))


# ------------------------------------------------------------------ N3 --
def test_n3_food_rule_cites_the_section_that_holds_the_quote():
    src = SOURCES["cipro_food"]
    assert src.source_ref == "emc:885:4.2" and src.section.startswith("4.2")
    assert "1-2 hours before or at least 4 hours after dairy products" in src.excerpt
