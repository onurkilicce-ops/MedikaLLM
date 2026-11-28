"""Second independent adversarial round on the M-02 parser (19 findings, all
reproduced by a separate verifier before the fix). Inputs are the reviewers'
synthetic sentences; expected results come from the finding's "expected"
column, not from parser output.
"""
from __future__ import annotations

import pytest

from src.timing import calc
from src.timing.parser import parse_field

S = "[SYNTHETIC] "


def _p(field, text, prefix=True):
    return parse_field(field, (S + text) if prefix else text,
                       stored_max_length=1000 if field == "half_life" else None)


def _clean(fp):
    return [v for v in fp.values if not v.review_reasons]


def _derived(fp):
    return [calc.five_half_lives(v, fp.flags) for v in fp.values if v.measure_type == "half_life"]


@pytest.mark.parametrize("field,text", [
    ("absorption", "Tmax was 1:30 hours after oral dosing."),
    ("half_life", "The half-life is 1:30 h."),
])
def test_f1_clock_notation_is_not_30_hours(field, text):
    fp = _p(field, text)
    assert all(30.0 not in (v.hours.value, v.hours.lower, v.hours.upper) for v in fp.values)


@pytest.mark.parametrize("text,kind,bound", [
    ("The half-life is not less than 10 hours.", "lower_bound", 10.0),
    ("The terminal half-life is no less than 24 hours.", "lower_bound", 24.0),
    ("The half-life is no longer than 3 hours.", "upper_bound", 3.0),
])
def test_f2_negated_comparatives_keep_direction(text, kind, bound):
    (v,) = _p("half_life", text).values
    assert v.hours.kind == kind and v.hours.inclusive is True
    assert (v.hours.lower if kind == "lower_bound" else v.hours.upper) == bound


@pytest.mark.parametrize("field,text,prefix", [
    ("absorption", "A high-fat meal delayed Tmax approximately 1.5 hours.", True),
    ("absorption", "Tmax was delayed 2 hours by food.", True),
    ("absorption", "Tmax was increased 1 hour by food.", True),
    ("half_life", "Half-life was prolonged 3 hours in patients with renal impairment.", True),
    ("absorption", "Food delayed Tmax to 3 hours.", True),
    ("absorption", "Tmax was prolonged to 3 hours by food.", True),
    ("half_life", "Prolonged to 20 hours", False),
    ("half_life", "Increases to 30 hours with age", False),
    ("half_life", "Up to 40 hours after overdose", False),
])
def test_f3_r08_r09_change_verbs_and_unknown_context_are_not_clean_values(field, text, prefix):
    fp = _p(field, text, prefix)
    assert _clean(fp) == []
    assert all(d["status"] == "not_computed" for d in _derived(fp))


def test_f4_compound_duration_is_not_split():
    fp = _p("absorption", "Tmax is 1 h 30 min after oral administration.")
    assert _clean(fp) == [] and "compound_duration" in {r.reason for r in fp.reviews}


@pytest.mark.parametrize("text", [
    "Half-life and Tmax are 8 h and 2 h, in that order.",
    "Its elimination half-life and time to peak are about 12 hours and 3 hours.",
])
def test_f5_paired_measure_lists_are_not_resolved(text):
    fp = _p("half_life", text)
    assert _clean(fp) == [] and all(d["status"] == "not_computed" for d in _derived(fp))


@pytest.mark.parametrize("field,text,value", [
    ("half_life", "The plasma half-life is 6 hours, but platelet inhibition lasts 7 days.", 6.0),
    ("absorption", "Peak plasma concentrations are reached in 2 hours after oral dosing and steady-state "
                   "levels in 3 days.", 2.0),
    ("absorption", "Peak plasma concentrations occur 2 hours after oral dosing; the terminal phase lasts 30 hours.",
     2.0),
])
def test_f6_unrelated_later_clause_does_not_inherit_the_measure(field, text, value):
    fp = _p(field, text)
    assert [v.hours.value for v in fp.values] == [value]


@pytest.mark.parametrize("text", [
    "The half-life is 4 h in patients with renal and hepatic impairment, and 8 h in healthy volunteers.",
    "The half-life is 4 h in adults and children, and 8 h in neonates.",
    "The half-life was 4 h in patients with mild, moderate, or severe renal impairment and 2 h in healthy volunteers.",
    "The half-life is 8 h in adults with hepatic and renal impairment, and 4 h in children.",
    "The half-life is 4 hours after oral and intravenous administration, and 6 hours after intramuscular injection.",
])
def test_f7_r02_coordinated_conditions_make_attribution_uncertain(text):
    fp = _p("half_life", text)
    assert fp.values  # the first value is kept, flagged
    assert _clean(fp) == []
    assert all(d["status"] == "not_computed" for d in _derived(fp))


def test_f8_f9_tiny_and_huge_values_are_never_0_or_inf():
    fp = _p("half_life", "Half-life of 0.001 seconds.")
    assert fp.values == [] and "value_below_precision" in {r.reason for r in fp.reviews}
    fp = _p("half_life", "Half-life: " + "1" * 308 + " days.")
    assert fp.values == [] and "invalid_value" in {r.reason for r in fp.reviews}
    fp = _p("half_life", "Half-life: 1" + "0" * 308 + " hours.")  # 1e308 h: finite, but x5 overflows
    for d in _derived(fp):
        assert d["status"] == "not_computed" and d["hours"] is None


@pytest.mark.parametrize("field,text", [
    ("half_life", "The half-life is 2 h after 10 mg i.v. Following oral dosing, the half-life is 6 h."),
    ("absorption", "Tmax is 1 h after 50 mg p.o. With food, Tmax is 3 h."),
])
def test_r01_route_abbreviation_can_end_a_sentence(field, text):
    a, b = _p(field, text).values
    assert a.sentence.start != b.sentence.start
    if field == "half_life":
        assert a.conditions["route"] == ["i.v."] and b.conditions["route"] == ["oral"]
    else:
        assert a.conditions["food_state"] == [] and b.conditions["food_state"] == ["with food"]


@pytest.mark.parametrize("field,text,lead", [
    ("half_life", "In elderly patients, the oral half-life was 10 hours versus 6 hours in younger patients.", "elderly"),
    ("absorption", "In the elderly, Tmax after oral dosing was 3 h, compared with 1 h in young people.", "elderly"),
    ("half_life", "In patients with cirrhosis, the terminal half-life was 20 h, compared with 8 h in healthy controls.",
     "cirrhosis"),
    ("half_life", "In rats, the half-life was 2 hours, and in humans it was 8 hours.", "rats"),
])
def test_r03_contrasted_value_does_not_inherit_leading_condition(field, text, lead):
    fp = _p(field, text)
    first, later = fp.values[0], fp.values[1:]
    assert lead in " ".join(first.conditions["population"] + first.conditions["other"])
    # the contrasted value is either kept for review or present without the
    # leading condition - never a value under the wrong group
    for v in later:
        assert lead not in " ".join(v.conditions["population"] + v.conditions["other"])


@pytest.mark.parametrize("field,text", [
    ("half_life", "Renal impairment prolonged the half-life by 10 h (from 6 to 16 h)."),
    ("absorption", "Tmax increased by 2 h (from 1 to 3 h) with food."),
])
def test_r04_change_statement_in_parentheses(field, text):
    assert _clean(_p(field, text)) == []


@pytest.mark.parametrize("field,text,key,term", [
    ("half_life", "In patients with severe renal impairment (CrCl < 30 mL/min; n = 6), the half-life was 20 hours.",
     "population", "renal impairment"),
    ("absorption", "After a high-fat meal (800 kcal; 50% fat), Tmax was 4 hours.", "food_state", "high-fat"),
    ("half_life", "Terminal half-life (mean; SD): 8 hours.", "phase", "terminal"),
])
def test_r05_semicolon_inside_parentheses_is_not_a_clause_end(field, text, key, term):
    (v,) = _p(field, text).values
    assert any(term in c for c in v.conditions[key]), v.conditions[key]


def test_r06_midpoint_boundary_is_flagged():
    fp = _p("half_life", "The half-life of 20 hours in hepatic impairment exceeds the 6 hours in healthy volunteers.")
    assert fp.values and _clean(fp) == []


def test_r07_parallel_list_without_respectively():
    fp = _p("half_life", "The half-lives in young and elderly subjects were 4 h and 8 h.")
    assert fp.values and all("parallel_value_list" in v.review_reasons for v in fp.values)


@pytest.mark.parametrize("text,reason", [
    ("When studied in cattle, sheep, and horses, the half-life is in the range of 1 to 2.5 hours.",
     "non_human_or_in_vitro"),
    ("The isotope decays by beta emission with a physical half-life of 8.04 days.", "physical_decay_not_elimination"),
])
def test_spot4_animal_species_and_physical_decay_block_5x(text, reason):
    fp = _p("half_life", text)
    (d,) = _derived(fp)
    assert d["status"] == "not_computed" and reason in d["not_computed_reasons"]


def test_r10_age_bands_and_population_synonyms():
    fp = _p("half_life", "The half-life in children 2 to 6 years is 3 h; the half-life in children 7 to 12 years is 5 h.")
    assert len(fp.values) == 2 and all(v.conflict_group is None for v in fp.values)
    fp = _p("half_life", "The half-life in children is 3 h. The half-life in pediatric patients is 5 h.")
    assert fp.values[0].conflict_group == fp.values[1].conflict_group is not None
