"""M02-O1-R2: re-audit findings D1-D4 on 51b2d56 (governing clause, scope
sentence with a known species, lower-case subject, in-window reference of
another claim). Positive, negative/ambiguous and near-but-different examples,
and combinations. All texts SYNTHETIC; 'Drug A' is the invented record name.
"""
from __future__ import annotations

import pytest

from src.timing import calc
from src.timing.parser import parse_field

S = "[SYNTHETIC] "
NAMES = ["[SYNTHETIC] Drug A"]


def _p(field, text):
    return parse_field(field, S + text, stored_max_length=1000 if field == "half_life" else None,
                       subject_names=NAMES)


def _clean(fp):
    return [v for v in fp.values if not v.review_reasons]


def _reasons(fp):
    return {r.reason for r in fp.reviews} | {x for v in fp.values for x in v.review_reasons}


def _derived(fp):
    return [calc.five_half_lives(v, fp.flags) for v in fp.values if v.measure_type == "half_life"]


# ------------------------------------------------------------------ D1 --
@pytest.mark.parametrize("field,text,reason", [
    ("half_life", "There is no evidence that the half-life is 4 hours.", "undetermined_statement"),
    ("half_life", "It is not known whether the half-life is 4 hours.", "hypothetical_or_open_question"),
    ("half_life", "If the half-life were 4 hours, the estimate would change.", "hypothetical_or_open_question"),
    ("absorption", "It has not been established that Tmax is 2 hours.", "undetermined_statement"),
    ("half_life", "It is unclear whether the half-life is 4 hours.", "hypothetical_or_open_question"),
    ("half_life", "There is little evidence that the half-life is 4 hours.", "undetermined_statement"),
    ("half_life", "It is unlikely that the half-life is 4 hours.", "undetermined_statement"),
])
def test_d1_governing_clause_negation_or_question_is_not_a_measurement(field, text, reason):
    fp = _p(field, text)
    assert fp.values == [] and reason in _reasons(fp)


@pytest.mark.parametrize("text,value", [
    ("No dose adjustment is required as the half-life is 4 hours.", 4.0),
    ("Studies have shown that the half-life is 4 hours.", 4.0),
    ("It has been established that the half-life is 4 hours.", 4.0),
    ("The elimination half-life is 4 hours.", 4.0),
])
def test_d1_positive_governing_clauses_stay_clean(text, value):
    (v,) = _p("half_life", text).values
    assert v.hours.value == value and v.review_reasons == []


def test_d1_bound_and_hedged_governing_clause():
    (v,) = _p("half_life", "The half-life is not less than 4 hours.").values
    assert v.hours.kind == "lower_bound" and v.review_reasons == []
    (v,) = _p("half_life", "Some authors suggest that the half-life is 4 hours.").values
    assert "hedged_value" in v.review_reasons


# ------------------------------------------------------------------ D2 --
@pytest.mark.parametrize("text", [
    "In dogs, elimination was studied. The half-life is 4 hours.",
    "These values were observed in dogs. The half-life is 4 hours.",
    "Plasma levels were measured in rats. The half-life is 4 hours.",
])
def test_d2_species_scope_sentence_flags_the_value(text):
    fp = _p("half_life", text)
    (v,) = fp.values
    assert {"field_context_unattributed", "non_human_context_in_field"} <= set(v.review_reasons)
    assert _derived(fp)[0]["status"] == "not_computed"


def test_d2_explicit_human_context_and_unrelated_species_sentence():
    (v,) = _p("half_life", "These data were obtained in dogs. In humans, the half-life is 4 hours.").values
    assert v.conditions["other"] == ["humans"] and v.review_reasons == []
    # a species sentence about something else does not spread to the value
    (v,) = _p("absorption", "In vitro studies indicate that Drug A is a P-gp substrate. "
                            "Peak plasma concentrations are reached in 2 hours.").values
    assert v.review_reasons == []


# ------------------------------------------------------------------ D3 --
@pytest.mark.parametrize("text", [
    "The half-life of drug b is 10 hours.",
    "drug b has a half-life of 10 hours.",
    "The half-life of Drug B is 10 hours.",
    "The elimination half-life for drug b was 10 hours.",
    "Tmax is 2 hours for drug b.",
])
def test_d3_other_subject_in_any_case_is_not_the_record_drug(text):
    field = "absorption" if text.startswith("Tmax") else "half_life"
    fp = _p(field, text)
    assert fp.values == []
    assert _reasons(fp) & {"subject_unresolved", "subject_not_record_drug"}


@pytest.mark.parametrize("text,value", [
    ("The half-life of drug a is 4 hours.", 4.0),
    ("The half-life of Drug A is 4 hours.", 4.0),
    ("drug a has a half-life of 4 hours.", 4.0),
    ("The half-life of the drug is 4 hours.", 4.0),
    ("The half-life of elimination is 4 hours.", 4.0),
    ("The half-life of the extended-release formulation is 4 hours.", 4.0),
    ("The half-life of approximately 4 hours is consistent across studies.", 4.0),
    ("It has a half-life of 4 hours.", 4.0),
])
def test_d3_record_drug_generic_and_condition_subjects_are_kept(text, value):
    fp = _p("half_life", text)
    vals = [v for v in fp.values if v.hours.value == value]
    assert vals, [r.reason for r in fp.reviews]
    assert "subject_unresolved" not in _reasons(fp)


def test_d3_metabolite_and_coadministration_are_not_subjects():
    (v,) = _p("half_life", "The half-life of the active metabolite is 20 hours.").values
    assert v.conditions["analyte"] == "metabolite"
    (v,) = _p("half_life", "When co-administered with drug c, the half-life is 6 hours.").values
    assert v.hours.value == 6.0 and v.conditions["other"]


# ------------------------------------------------------------------ D4 --
def test_d4_in_window_token_of_another_claim_is_not_attributed():
    (v,) = _p("half_life", "The half-life is 4 hours, while adverse events are described elsewhere [A2] in "
                           "the report.").values
    assert v.reference_tokens == [] and v.nearby_reference_tokens == ["A2"]
    (v,) = _p("half_life", "The half-life is 4 hours [A1], while adverse events are described elsewhere [A2] "
                           "in the report.").values
    assert v.reference_tokens == ["A1"] and v.reference_scope == "value_window"
    assert v.nearby_reference_tokens == ["A2"]
    (v,) = _p("half_life", "Adverse events are described elsewhere [A2], and the half-life is 4 hours.").values
    assert v.reference_tokens == [] and v.nearby_reference_tokens == ["A2"]


def test_d4_clear_attributions_still_work():
    (v,) = _p("half_life", "The half-life is 4 hours.[A1]").values
    assert v.reference_tokens == ["A1"] and v.reference_scope == "sentence_single_value"
    (v,) = _p("half_life", "The half-life is 4 hours [A1] in adults.").values
    assert v.reference_tokens == ["A1"] and v.reference_scope == "value_window"
    (v,) = _p("half_life", "The half-life is 4 hours; the duration of effect is 9 hours.[A2]").values
    assert v.reference_scope == "sentence_other_clause" and v.reference_tokens == []


# ------------------------------------------------------------ combined --
def test_combined_governing_negation_subject_species_and_reference():
    fp = _p("half_life", "In dogs, elimination was studied. There is no evidence that the half-life of drug b "
                         "is 10 hours [A2], and the half-life is 4 hours [A1].")
    assert all(v.hours.value != 10.0 for v in fp.values)
    (v,) = fp.values
    assert v.hours.value == 4.0 and v.reference_tokens == ["A1"] and "A2" in v.nearby_reference_tokens
    assert "non_human_context_in_field" in v.review_reasons
    assert _derived(fp)[0]["status"] == "not_computed"
