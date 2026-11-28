"""M-02 parser /11: inline HTML markup in stored text ('T<sub>1/2</sub>') and values
stated per enantiomer ('R-warfarin', 'S-warfarin'). Every text is SYNTHETIC."""
from __future__ import annotations

import pytest

from src.timing.parser import normalize_markup, parse_field

S = "[SYNTHETIC] "
NAME = ["[SYNTHETIC] Warfarin"]


def _p(text, field="half_life"):
    return parse_field(field, S + text, stored_max_length=1000, subject_names=NAME)


def _vals(fp):
    return [((v.hours.lower, v.hours.upper) if v.hours.kind == "range" else v.hours.value, v.review_reasons,
             v.conditions["stereoisomer"]) for v in fp.values]


@pytest.mark.parametrize("raw,expected", [
    ("T<sub>1/2</sub>", "T1/2"), ("t<sub>max</sub>", "tmax"), ("C<SUB>max</SUB>", "Cmax"),
    ("10<sup>3</sup>", "10^3"), ("a<br/>b", "a b"), ("<i>in vitro</i>", "in vitro"),
    ("<span class=\"x\">4 h</span>", "4 h"), ("x < 5 and y > 3", "x < 5 and y > 3"),
])
def test_normalize_markup(raw, expected):
    assert normalize_markup(raw) == expected


@pytest.mark.parametrize("text,field,value", [
    ("The T<sub>1/2</sub> is 40 hours.", "half_life", 40.0),
    ("T<sub>max</sub> is 4 hours.", "absorption", 4.0),
])
def test_subscript_notation_is_read(text, field, value):
    fp = _p(text, field)
    assert _vals(fp) == [(value, [], [])] and "html_formatting_removed" in fp.flags
    assert "<sub>" not in fp.text


@pytest.mark.parametrize("text", [
    "R-warfarin T<sub>1/2</sub>=37-89 hours. S-warfarin T<sub>1/2</sub>=21-43 hours.",
    "T<sub>1/2</sub> of R-warfarin: 37-89 hours; T<sub>1/2</sub> of S-warfarin: 21-43 hours.",
    "The T1/2 of R-warfarin is 37-89 hours and the T1/2 of S-warfarin is 21-43 hours.",
])
def test_enantiomer_values_stay_separate(text):
    assert _vals(_p(text)) == [((37.0, 89.0), [], ["R-warfarin"]), ((21.0, 43.0), [], ["S-warfarin"])]


def test_a_value_without_its_own_keyword_still_goes_to_review():
    # cautious M-02 rule kept: the second value shares the keyword of the first
    fp = _p("The half-life of R-warfarin is 37-89 hours and of S-warfarin 21-43 hours.")
    assert _vals(fp) == [((37.0, 89.0), [], ["R-warfarin"])]
    assert "duration_not_identified_as_half_life" in [r.reason for r in fp.reviews]


@pytest.mark.parametrize("text", [
    "The half-life of R-drugb is 30 hours.",          # another drug with a stereo prefix
    "The half-life of S-zorvex is 30 hours.",
])
def test_a_prefixed_other_drug_is_still_foreign(text):
    assert _vals(_p(text)) == []


def test_plain_text_is_unchanged():
    fp = _p("The half-life is 40 hours.")
    assert _vals(fp) == [(40.0, [], [])] and "html_formatting_removed" not in fp.flags


def test_truncation_is_judged_on_the_stored_length():
    text = "T<sub>1/2</sub> is 40 hours. " + "x" * 2000
    fp = parse_field("half_life", text[:1000], stored_max_length=1000, subject_names=NAME)
    assert fp.possibly_truncated
