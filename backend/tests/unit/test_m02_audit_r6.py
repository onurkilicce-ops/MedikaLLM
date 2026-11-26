"""M02-O1-R6: amount vs name, range vs separate claim, whole token blocks.

D3: a candidate that starts with a digit is not a quantity by itself
('5-zoralen', '10 mg drug b'). D4-A: a dash is a range only between two
parsed durations, not because a duration follows it. D4-B: a window boundary
never splits a reference token block. Expectations are fixed independently
of observed output; every text is SYNTHETIC; '5-zoralen' is an invented name.
"""
from __future__ import annotations

import pytest

from src.timing import calc
from src.timing.parser import PARSER_VERSION, parse_field

S = "[SYNTHETIC] "


def _p(text, rec="Drug A"):
    return parse_field("half_life", S + text, stored_max_length=1000, subject_names=["[SYNTHETIC] " + rec])


def _clean(fp):
    return [v for v in fp.values if not v.review_reasons]


def _derived(fp):
    return [calc.five_half_lives(v, fp.flags) for v in fp.values if v.measure_type == "half_life"]


def test_parser_version_bumped_for_behaviour_change():
    assert PARSER_VERSION == "m02-text-parser/7"


# ------------------------------------------------------------------ D3 --
TEMPLATES = ["The half-life of {s} is {v} hours.", "For {s}, the half-life is {v} hours.",
             "For {s} in adults, the half-life is {v} hours.", "In overdose of {s}, the half-life is {v} hours."]


@pytest.mark.parametrize("tpl", TEMPLATES)
@pytest.mark.parametrize("subject,record", [
    ("5-zoralen", "Drug A"), ("5-zoralen", "6-zoralen"), ("10 mg drug b", "Drug A"), ("2.5 mg drug b", "Drug A"),
    ("10 mg 5-zoralen", "Drug A"), ("drug b 10 mg", "Drug A"), ("3-drug b", "Drug A"),
])
def test_d3_digit_led_or_amount_prefixed_foreign_subject_is_never_clean(tpl, subject, record):
    fp = _p(tpl.format(s=subject, v=10), record)
    assert _clean(fp) == [] and all(d["status"] == "not_computed" for d in _derived(fp))
    assert "subject_unresolved" in {r.reason for r in fp.reviews}


@pytest.mark.parametrize("tpl", TEMPLATES)
@pytest.mark.parametrize("subject,record", [
    ("5-zoralen", "5-zoralen"), ("10 mg drug a", "Drug A"), ("10-mg drug a", "Drug A"),
    ("10 mg 5-zoralen", "5-zoralen"), ("5-zoralen hydrochloride", "5-zoralen"), ("drug a 10 mg", "Drug A"),
])
def test_d3_digit_led_or_amount_prefixed_record_subject_stays_clean(tpl, subject, record):
    fp = _p(tpl.format(s=subject, v=4), record)
    (v,) = fp.values
    assert v.review_reasons == [] and v.hours.value == 4.0
    (d,) = _derived(fp)
    assert d["status"] == "computed" and d["hours"].value == 20.0


@pytest.mark.parametrize("text", [
    "For the 10 mg dose, the half-life is 4 hours.",
    "For a 10-mg dose, the half-life is 4 hours.",
    "After 2 doses, the half-life is 4 hours.",
    "In 12 healthy volunteers, the half-life is 4 hours.",
    "The half-life in 10 patients is 4 hours.",
    "The half-life of drug a is 4 hours.",
])
def test_d3_amount_only_phrases_carry_no_subject(text):
    assert len(_clean(_p(text))) == 1


def test_d3_audit_examples_exactly():
    for text in ("The half-life of 5-zoralen is 10 hours.", "For 5-zoralen, the half-life is 10 hours.",
                 "For 10 mg drug b, the half-life is 10 hours."):
        fp = _p(text)
        assert fp.values == [] and [r.reason for r in fp.reviews] == ["subject_unresolved"]


# ---------------------------------------------------------------- D4-A --
DASHES = [" - ", " – ", " — ", " -- ", "—"]


@pytest.mark.parametrize("dash", DASHES)
def test_d4a_statement_before_a_dash_is_not_the_values_source(dash):
    (v,) = _p(f"Rash was observed [A2]{dash}4 hours is the half-life [A1].").values
    assert v.reference_tokens == ["A1"] and v.nearby_reference_tokens == ["A2"]
    assert v.reference_scope == "value_window"


@pytest.mark.parametrize("dash", DASHES)
def test_d4a_numbered_statement_before_a_dash(dash):
    fp = _p(f"Rash was observed in 10 patients [A2]{dash}the half-life is 4 hours [A1].")
    (v,) = [x for x in fp.values if x.hours.value == 4.0]
    assert v.reference_tokens == ["A1"] and "A2" not in v.reference_tokens


@pytest.mark.parametrize("text,lo,hi", [
    ("The half-life is 4-6 hours [A1].", 4.0, 6.0),
    ("The half-life is 4 – 6 hours [A1].", 4.0, 6.0),
    ("The half-life is 4 hours - 6 hours [A1].", 4.0, 6.0),
    ("The half-life is 4 hours – 6 hours [A1].", 4.0, 6.0),
    ("The half-life is 4 hours — 6 hours [A1].", 4.0, 6.0),
    ("The half-life ranges 4 - 6 hours [A1].", 4.0, 6.0),
])
def test_d4a_real_ranges_are_unchanged(text, lo, hi):
    (v,) = _p(text).values
    assert (v.hours.lower, v.hours.upper) == (lo, hi) and v.reference_tokens == ["A1"]


def test_d4a_double_hyphen_between_durations_stays_a_documented_limit():
    # not a range: two values, both in review, no 5x (RULES 8f/8g); not passed as a range
    fp = _p("The half-life is 4 hours -- 6 hours [A1].")
    assert len(fp.values) == 2 and _clean(fp) == []
    assert all(d["status"] == "not_computed" for d in _derived(fp))


# ---------------------------------------------------------------- D4-B --
@pytest.mark.parametrize("dash", DASHES)
def test_d4b_token_after_a_value_is_not_split_by_the_window(dash):
    text = f"The half-life is 4 hours [A1]{dash}10 hours after dosing, rash was observed [A2]."
    fp = _p(text)
    (v,) = fp.values  # 10 hours is a review item, not a half-life
    assert v.hours.value == 4.0 and v.reference_tokens == ["A1"] and v.nearby_reference_tokens == ["A2"]
    assert v.reference_scope == "value_window"
    assert "duration_not_identified_as_half_life" in {r.reason for r in fp.reviews}
    full = S + text
    assert full[v.value_span.start:v.value_span.end] == "4 hours"  # offsets unchanged
    assert full[v.sentence.start:v.sentence.end] == full


def test_d4b_audit_offsets_exactly():
    text = "The half-life is 4 hours [A1] - 10 hours after dosing, rash was observed [A2]."
    fp = _p(text)
    (v,) = fp.values
    assert (v.value_span.start, v.value_span.end) == (29, 36)
    (r,) = [x for x in fp.reviews if x.reason == "duration_not_identified_as_half_life"]
    assert (r.value_span.start, r.value_span.end) == (44, 52)


def test_d4b_token_list_with_comma_is_kept_whole():
    (v,) = _p("The half-life is 4 hours [A1, A2] - 10 hours after dosing, rash was observed.").values
    assert v.reference_tokens == ["A1", "A2"]


def test_d4b_two_values_each_keep_their_own_token():
    fp = _p("The half-life is 4 hours [A1] and 6 hours [A2] in adults and children, respectively.")
    assert [v.reference_tokens for v in fp.values] == [["A1"], ["A2"]]


# ------------------------------------------------------------ combined --
def test_combined_amount_name_and_dash_claim():
    fp = _p("For 10 mg drug b, the half-life is 10 hours [A1] - 10 patients developed rash [A2].")
    assert _clean(fp) == []
    (v,) = _p("For 10 mg drug a, the half-life is 4 hours [A1] - 10 patients developed rash [A2].").values
    assert v.review_reasons == [] and v.reference_tokens == ["A1"] and v.nearby_reference_tokens == ["A2"]
