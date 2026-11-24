"""M-02 task acceptance examples, checked one by one (synthetic text only).

Expected values are the ones written in the M02-O1 task text; they were not
taken from parser output.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.timing import calc
from src.timing.models import TimingCompareRequest
from src.timing.parser import ParsedQuantity, parse_field

S = "[SYNTHETIC] "


def _one(field, text, **kw):
    fp = parse_field(field, S + text, **kw)
    assert len(fp.values) == 1, [(v.measure_type, v.hours) for v in fp.values]
    return fp, fp.values[0]


def test_90_minutes_is_1_5_hours():
    _, v = _one("half_life", "The half-life is 90 minutes.")
    assert (v.hours.kind, v.hours.value) == ("point", 1.5)
    assert (v.original.value, v.unit) == (90.0, "minutes")


def test_2_to_4_hours_stays_a_range_and_is_not_averaged():
    _, v = _one("half_life", "The half-life is 2-4 hours.")
    assert (v.hours.kind, v.hours.lower, v.hours.upper, v.hours.value) == ("range", 2.0, 4.0, None)


def test_1_to_2_days_is_24_to_48_hours():
    _, v = _one("half_life", "The terminal half-life is 1-2 days.")
    assert (v.hours.lower, v.hours.upper) == (24.0, 48.0)


def test_tmax_and_half_life_stay_separate_and_tmax_is_not_added():
    absorption = parse_field("absorption", S + "Peak plasma concentrations occur 0.5-1 hours after oral dosing.")
    half = parse_field("half_life", S + "The elimination half-life is 4-6 hours.")
    (t,) = absorption.values
    (h,) = half.values
    assert t.measure_type == "tmax" and (t.hours.lower, t.hours.upper) == (0.5, 1.0)
    assert t.time_reference == "after_administration"
    assert h.measure_type == "half_life" and h.time_reference == "not_applicable_duration"
    d = calc.five_half_lives(h, half.flags)
    assert d["status"] == "computed"
    assert (d["hours"].kind, d["hours"].lower, d["hours"].upper) == ("range", 20.0, 30.0)
    assert (d["hours"].lower, d["hours"].upper) != (20.5, 31.0)
    # the source measurement is unchanged by the derivation
    assert (h.hours.lower, h.hours.upper) == (4.0, 6.0)


@pytest.mark.parametrize("text,kind,expected,approx", [
    ("The half-life is 2.5 hours.", "point", {"value": 2.5}, False),
    ("The half-life is approximately 6 hours.", "point", {"value": 6.0}, True),
    ("The half-life is less than 2 hours.", "upper_bound", {"upper": 2.0}, False),
    ("The half-life is at least 24 hours.", "lower_bound", {"lower": 24.0}, False),
    ("The half-life is between 3.5 and 5 hours.", "range", {"lower": 3.5, "upper": 5.0}, False),
])
def test_decimals_ranges_approximations_and_inequalities(text, kind, expected, approx):
    _, v = _one("half_life", text)
    assert v.hours.kind == kind and v.approximate is approx
    for k, val in expected.items():
        assert getattr(v.hours, k) == val


@pytest.mark.parametrize("text,reason", [
    ("The half-life is 1,5 hours.", "ambiguous_number_format"),
    ("The half-life is 0 hours.", "invalid_value"),
    ("The half-life is -3 hours.", "invalid_value"),
    ("The half-life is 8-4 hours.", "inverted_range"),
    ("The half-life is NaN hours.", "keyword_without_parsable_value"),
    ("The half-life is infinite.", "keyword_without_parsable_value"),
    ("The half-life is ∞ hours.", "keyword_without_parsable_value"),
    ("The half-life is two hours.", "keyword_without_parsable_value"),
])
def test_unusable_numbers_go_to_review_and_never_become_zero(text, reason):
    fp = parse_field("half_life", S + text, stored_max_length=1000)
    assert fp.values == []
    assert fp.status == "unparsed_needs_review"
    assert reason in {r.reason for r in fp.reviews}


def test_derived_refuses_non_finite_or_non_positive_values():
    _, v = _one("half_life", "The half-life is 4 hours.")
    for bad in (float("nan"), float("inf"), 0.0, -1.0):
        v.hours = ParsedQuantity("point", value=bad)
        d = calc.five_half_lives(v, [])
        assert d["status"] == "not_computed" and "invalid_value" in d["not_computed_reasons"]
        assert d["hours"] is None


def test_formulation_population_phase_and_metabolite_are_not_merged():
    fp = parse_field("half_life", S + "In healthy adults the half-life of the tablet is 4 hours, whereas in "
                     "elderly patients given the extended-release capsule it is 9 hours.")
    a, b = fp.values
    assert a.conditions["population"] == ["healthy adults"] and "elderly" in b.conditions["population"]
    assert "tablet" in a.conditions["formulation"] and "extended-release" in b.conditions["formulation"]
    assert "elderly" not in a.conditions["population"] and "healthy adults" not in b.conditions["population"]
    assert a.conflict_group is None and b.conflict_group is None

    fp = parse_field("half_life", S + "The distribution half-life is 0.5 hours and the terminal half-life is 30 hours.")
    dist, term = fp.values
    assert calc.five_half_lives(dist, fp.flags)["not_computed_reasons"] == ["non_elimination_phase"]
    assert calc.five_half_lives(term, fp.flags)["hours"].value == 150.0

    fp = parse_field("half_life", S + "The half-life of the parent drug is 3 hours; the active metabolite has a "
                     "half-life of 14 hours.")
    parent, met = fp.values
    assert parent.conditions["analyte"] == "parent" and met.conditions["analyte"] == "metabolite"
    assert calc.five_half_lives(met, fp.flags)["status"] == "not_computed"


def test_same_conditions_disagreement_is_kept_and_flagged():
    fp = parse_field("half_life", S + "The half-life is 4 hours. Another study reported a half-life of 7 hours.")
    a, b = fp.values
    assert a.conflict_group == b.conflict_group is not None
    assert fp.status == "parsed_needs_review"
    for v in (a, b):
        assert "conflicting_values_same_conditions" in v.review_reasons
        assert calc.five_half_lives(v, fp.flags)["status"] == "not_computed"


def test_empty_placeholder_and_truncation_suspicion():
    assert parse_field("half_life", None).status == "empty"
    assert parse_field("half_life", "   ").status == "empty"
    assert parse_field("half_life", "Not Available").status == "placeholder"
    text = (S + "The half-life is 4 hours. " + "Filler text. " * 80)[:999] + "1"
    fp = parse_field("half_life", text, stored_max_length=1000)
    assert fp.possibly_truncated and fp.status == "parsed_needs_review"
    assert "sentence_possibly_truncated" in {r.reason for r in fp.reviews}
    assert calc.five_half_lives(fp.values[0], fp.flags)["status"] == "not_computed"
    # 999 characters: no truncation suspicion
    assert parse_field("half_life", text[:999], stored_max_length=1000).possibly_truncated is False


@pytest.mark.parametrize("field,text", [
    ("absorption", "Absorption is reduced in patients aged 65 years and older."),
    ("absorption", "Peak plasma concentrations of 12 mg/L were reached after a 500 mg dose."),
    ("absorption", "Doses of 10-20 mg produced plasma concentrations of 50-80 ng/mL."),
    ("absorption", "Maximum therapeutic effect is reached after 2 hours."),
    ("absorption", "The dose interval is 8 hours; dosing every 12 hours was also studied."),
    ("half_life", "Patients aged 65 years had a longer half-life."),
    ("half_life", "Dosing every 12 hours is recommended because of the half-life."),
    ("half_life", "Maximum therapeutic effect occurs at 4 hours; the half-life was not measured."),
])
def test_age_mg_concentration_dose_and_effect_are_never_tmax_or_half_life(field, text):
    fp = parse_field(field, S + text)
    assert fp.values == [], [(v.measure_type, v.hours) for v in fp.values]


def test_reference_linking_is_exact_and_same_drug_only():
    fp = parse_field("half_life", S + "The half-life is 4 hours.[A1] Absorption data are limited.[A2]")
    (v,) = fp.values
    assert v.reference_tokens == ["A1"]  # the other sentence's token is not attached
    assert calc.reference_status(v.reference_tokens, {"A1", "A2", "A3"}) == ("matched", ["A1"], [])
    assert calc.reference_status(v.reference_tokens, {"A2", "A3"}) == ("unmatched", [], ["A1"])
    assert calc.reference_status([], {"A1"}) == ("no_inline_reference", [], [])


@pytest.mark.parametrize("ids", [
    ["DB00001"], [], ["DB00001"] * 2, ["DB00001", "db00002"], ["DB00001", "DB0002"],
    ["DB00001", " DB00002"], [f"DB{n:05d}" for n in range(1, 12)],
])
def test_request_rejects_invalid_lists_without_fixing_them(ids):
    with pytest.raises(ValidationError):
        TimingCompareRequest(drug_ids=ids)


def test_request_keeps_order_and_rejects_extra_fields():
    assert TimingCompareRequest(drug_ids=["DB00002", "DB00001"]).drug_ids == ["DB00002", "DB00001"]
    with pytest.raises(ValidationError):
        TimingCompareRequest(drug_ids=["DB00001", "DB00002"], patient_id="p1")


def test_timing_module_has_no_llm_agent_or_network_imports():
    root = Path(__file__).resolve().parents[2] / "src" / "timing"
    banned = ("openai", "anthropic", "langchain", "langgraph", "httpx", "requests", "..agent", "..session",
              "..pubmed", "..conversations", "urllib")
    for py in root.glob("*.py"):
        src = py.read_text(encoding="utf-8")
        import_lines = [ln for ln in src.splitlines() if ln.lstrip().startswith(("import ", "from "))]
        for ln in import_lines:
            assert not any(b in ln for b in banned), (py.name, ln)


def test_interpretation_makes_no_positive_clearance_claim():
    text = calc.INTERPRETATION.lower()
    for banned in ("is safe", "safe to", "has left the body", "effect is over", "fully eliminated"):
        assert banned not in text
    assert "approximate" in text and "first-order" in text
    assert math.isclose(0.5 ** 5, 0.03125)  # "about 3% remains" statement in INTERPRETATION
