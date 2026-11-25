"""M02-O1-R4: the two remaining audit findings on d18b591.

D3: cleaning the subject phrase (salt words, condition words) must not erase
a named subject; an empty phrase after cleaning is not a match with the
record drug. D4: a statement after a dash is not the value's source.
Positive, negative, near-but-different and combined examples; every text is
SYNTHETIC and 'Drug A' is the invented record name.
"""
from __future__ import annotations

import pytest

from src.timing import calc
from src.timing.parser import PARSER_VERSION, parse_field

S = "[SYNTHETIC] "
NAMES = ["[SYNTHETIC] Drug A"]


def _p(text, names=NAMES, field="half_life"):
    return parse_field(field, S + text, stored_max_length=1000 if field == "half_life" else None,
                       subject_names=names)


def _clean(fp):
    return [v for v in fp.values if not v.review_reasons]


def _reasons(fp):
    return {r.reason for r in fp.reviews} | {x for v in fp.values for x in v.review_reasons}


def _derived(fp):
    return [calc.five_half_lives(v, fp.flags) for v in fp.values if v.measure_type == "half_life"]


def test_parser_version_bumped_for_behaviour_change():
    assert PARSER_VERSION.startswith("m02-text-parser/") and int(PARSER_VERSION.rsplit("/", 1)[1]) >= 5


# ------------------------------------------------------------------ D3 --
@pytest.mark.parametrize("text", [
    "The half-life of magnesium sulfate is 10 hours.",
    "For drug b in overdose, the half-life is 10 hours.",
    # near: other salts, other conditions, other positions
    "The half-life of sodium chloride is 10 hours.",
    "For magnesium sulfate, the half-life is 10 hours.",
    "For drug b in patients with renal impairment, the half-life is 10 hours.",
    "For drug b hydrochloride in overdose, the half-life is 10 hours.",
    "For drug b after oral dosing, the half-life is 10 hours.",
    "In overdose of drug b, the half-life is 10 hours.",
    "The half-life of drug b sulfate is 10 hours.",
    "The half-life of drug b hydrochloride extended-release tablets is 10 hours.",
    "The half-life of magnesium sulfate in overdose is 10 hours.",
])
def test_d3_named_subject_survives_cleaning(text):
    fp = _p(text)
    assert _clean(fp) == [] and all(d["status"] == "not_computed" for d in _derived(fp))
    assert "subject_unresolved" in _reasons(fp)
    assert fp.reviews and fp.reviews[0].reason == "subject_unresolved"  # text kept for review


@pytest.mark.parametrize("cond", ["", " in overdose", " in patients with renal impairment", " in healthy volunteers",
                                  " after oral dosing", " extended-release tablets"])
def test_d3_adding_or_removing_a_condition_never_makes_a_foreign_subject_clean(cond):
    for subject in ("drug b", "magnesium sulfate", "drug b hydrochloride"):
        assert _clean(_p(f"For {subject}{cond}, the half-life is 10 hours.")) == []
        assert _clean(_p(f"The half-life of {subject}{cond} is 10 hours.")) == []


@pytest.mark.parametrize("text", [
    "For drug a in overdose, the half-life is 4 hours.",
    "For drug a hydrochloride, the half-life is 4 hours.",
    "The drug's half-life is 4 hours.",
    "For Drug A in patients with renal impairment, the half-life is 4 hours.",
    "The half-life of drug a in overdose is 4 hours.",
    "In overdose, the half-life is 4 hours.",
    "In the event of overdose, the half-life is 4 hours.",
    "For oral administration, the half-life is 4 hours.",
    "In the fasted state, the half-life is 4 hours.",
])
def test_d3_record_drug_and_subjectless_settings_stay_clean(text):
    fp = _p(text)
    (v,) = fp.values
    assert v.review_reasons == [] and v.hours.value == 4.0
    (d,) = _derived(fp)
    assert d["status"] == "computed" and d["hours"].value == 20.0


def test_d3_metabolite_frame_is_not_a_foreign_subject():
    # the value stays clean; 5x is not computed for a metabolite (calc rule, unchanged)
    (v,) = _p("For the active metabolite, the half-life is 4 hours.").values
    assert v.review_reasons == [] and v.conditions["analyte"] == "metabolite"


@pytest.mark.parametrize("text", [
    "The half-life of magnesium sulfate is 4 hours.",
    "For magnesium sulfate in overdose, the half-life is 4 hours.",
    "The half-life of magnesium sulfate extended-release tablets is 4 hours.",
])
def test_d3_salt_named_record_is_still_matched(text):
    assert len(_clean(_p(text, names=["[SYNTHETIC] magnesium sulfate"]))) == 1
    # ... but not under a record with another salt name
    assert _clean(_p(text, names=["[SYNTHETIC] sodium chloride"])) == []


# ------------------------------------------------------------------ D4 --
@pytest.mark.parametrize("sep", [" — ", "—", " – ", " -- ", " - "])
@pytest.mark.parametrize("claim", ["adverse events are described elsewhere [A2]", "rash is common [A2]",
                                   "adverse events described elsewhere [A2]"])
def test_d4_statement_after_a_dash_is_not_the_values_source(sep, claim):
    fp = _p(f"The half-life is 4 hours{sep}{claim}.")
    (v,) = fp.values
    assert v.reference_tokens == [] and "A2" in v.nearby_reference_tokens
    assert v.reference_scope == "none"
    assert v.review_reasons == [] and v.hours.value == 4.0  # the value itself is unaffected


def test_d4_finding_example_exactly():
    (v,) = _p("The half-life is 4 hours — adverse events are described elsewhere [A2].").values
    assert (v.reference_tokens, v.nearby_reference_tokens, v.reference_scope) == ([], ["A2"], "none")


@pytest.mark.parametrize("sep", [" — ", " -- ", " - "])
def test_d4_explicit_a1_before_a_dash_is_kept(sep):
    (v,) = _p(f"The half-life is 4 hours [A1]{sep}adverse events are described elsewhere [A2].").values
    assert v.reference_tokens == ["A1"] and v.reference_scope == "value_window"
    assert v.nearby_reference_tokens == ["A2"]


def test_d4_statement_before_the_value_after_a_dash_is_not_the_source():
    (v,) = _p("Adverse events are described elsewhere [A2] — the half-life is 4 hours.").values
    assert "A2" not in v.reference_tokens and "A2" in v.nearby_reference_tokens


def test_d4_claim_dash_before_a_sentence_end_token_is_other_clause():
    (v,) = _p("The half-life is 4 hours — adverse events are described elsewhere.[A1]").values
    assert v.reference_tokens == [] and v.reference_scope == "sentence_other_clause"
    assert v.nearby_reference_tokens == ["A1"]


@pytest.mark.parametrize("text,tokens,scope", [
    ("The half-life is 4 hours.[A1]", ["A1"], "sentence_single_value"),
    ("The half-life is 4 hours [A1] (adverse events are described elsewhere [A2]).", ["A1"], "value_window"),
    ("The half-life is 4 hours (in adults) [A1].", ["A1"], "value_window"),
    ("The half-life is 4-6 hours [A1].", ["A1"], "value_window"),
    ("The half-life is 4 – 6 hours [A1].", ["A1"], "value_window"),
    ("The elimination half-life of the extended-release tablets is 4 hours [A1].", ["A1"], "value_window"),
    ("The half-life is 4 hours — in adults — [A1].", ["A1"], "value_window"),
])
def test_d4_hyphens_ranges_and_annotation_dashes_keep_attribution(text, tokens, scope):
    fp = _p(text)
    v = fp.values[0]
    assert v.reference_tokens == tokens and v.reference_scope == scope


# ------------------------------------------------------------ combined --
def test_combined_foreign_subject_with_condition_and_dash_reference():
    fp = _p("For drug b in overdose, the half-life is 10 hours — adverse events are described elsewhere [A2].")
    assert _clean(fp) == [] and "subject_unresolved" in _reasons(fp)


def test_combined_record_subject_with_condition_and_dash_reference():
    fp = _p("For drug a in overdose, the half-life is 4 hours [A1] — adverse events are described "
            "elsewhere [A2].")
    (v,) = fp.values
    assert v.review_reasons == [] and v.reference_tokens == ["A1"] and v.nearby_reference_tokens == ["A2"]
