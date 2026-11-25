"""M02-O1-R3: open paths of D1 (an intervening phrase hides the governing
clause; 'failed to establish'), D3 (lower-case possessive / framing subject)
and D4 (a separate claim in a parenthesis or after a colon) on 844f3bb.
Positive, negative, near-but-different and combined examples. All texts
SYNTHETIC; 'Drug A' is the invented record name.
"""
from __future__ import annotations

import pytest

from src.timing import calc
from src.timing.parser import PARSER_VERSION, parse_field

S = "[SYNTHETIC] "
NAMES = ["[SYNTHETIC] Drug A"]


def _p(field, text, names=NAMES):
    return parse_field(field, S + text, stored_max_length=1000 if field == "half_life" else None,
                       subject_names=names)


def _clean(fp):
    return [v for v in fp.values if not v.review_reasons]


def _reasons(fp):
    return {r.reason for r in fp.reviews} | {x for v in fp.values for x in v.review_reasons}


def _derived(fp):
    return [calc.five_half_lives(v, fp.flags) for v in fp.values if v.measure_type == "half_life"]


def test_parser_version_bumped_for_behaviour_change():
    assert PARSER_VERSION == "m02-text-parser/4"


# ------------------------------------------------------------------ D1 --
@pytest.mark.parametrize("field,text,reason", [
    ("half_life", "There is no evidence that, in adults, the half-life is 4 hours.", "undetermined_statement"),
    ("half_life", "There is no evidence that the half-life, measured in adults, is 4 hours.",
     "undetermined_statement"),
    ("half_life", "Studies failed to establish that the half-life is 4 hours.", "undetermined_statement"),
    ("absorption", "It is not known whether, after oral administration, Tmax is 2 hours.",
     "hypothetical_or_open_question"),
    # near: other intervening phrases / other failure verbs
    ("half_life", "There is no evidence that, in adults and children, the half-life is 4 hours.",
     "undetermined_statement"),
    ("half_life", "It has not been established that the half-life, in adults, is 4 hours.",
     "undetermined_statement"),
    ("half_life", "Investigators were unable to determine whether, in adults, the half-life is 4 hours.",
     "hypothetical_or_open_question"),
    ("half_life", "Studies failed to show a half-life of 4 hours.", "undetermined_statement"),
    ("half_life", "There is a lack of evidence that the half-life is 4 hours.", "undetermined_statement"),
    ("half_life", "The half-life is not, in adults, 4 hours.", "negated_value"),
])
def test_d1_intervening_phrase_keeps_governing_clause(field, text, reason):
    fp = _p(field, text)
    assert fp.values == [] and reason in _reasons(fp)
    assert _derived(fp) == []
    # the text and the reason are kept as a review item
    assert fp.reviews and fp.reviews[0].reason == reason
    assert (S + text)[fp.reviews[0].sentence.start:fp.reviews[0].sentence.end].startswith("[SYNTHETIC]")


@pytest.mark.parametrize("field,text,population", [
    ("half_life", "Studies have shown that, in adults, the half-life is 4 hours.", ["adults"]),
    ("half_life", "There is evidence that, in adults, the half-life is 4 hours.", ["adults"]),
    ("half_life", "No dose adjustment is required as the half-life is 4 hours.", []),
    ("half_life", "The half-life, in adults, is 4 hours.", ["adults"]),
    ("half_life", "The half-life, however, is 4 hours.", []),
    ("half_life", "Patients who failed to respond had a half-life of 4 hours.", None),
    ("absorption", "If taken with food, Tmax is 3 hours.", None),
    ("absorption", "Whether taken with food or not, Tmax is 2 hours.", None),
])
def test_d1_positive_controls_stay_clean(field, text, population):
    fp = _p(field, text)
    (v,) = fp.values
    assert v.review_reasons == []
    if population is not None:
        assert v.conditions["population"] == population
    if field == "half_life":
        (d,) = _derived(fp)
        assert d["status"] == "computed" and d["hours"].value == 5 * v.hours.value


def test_d1_lower_bound_is_not_a_negation():
    fp = _p("half_life", "The half-life is not less than 4 hours.")
    (v,) = fp.values
    assert v.review_reasons == [] and v.hours.kind == "lower_bound" and v.hours.lower == 4.0


# ------------------------------------------------------------------ D3 --
@pytest.mark.parametrize("text", [
    "drug b's half-life is 10 hours.",
    "For drug b, the half-life is 10 hours.",
    "DRUG B'S half-life is 10 hours.",
    "In drug b, the half-life is 10 hours.",
    "The half-life is 4 hours in adults; for drug b, the half-life is 10 hours.",
])
def test_d3_lower_case_possessive_and_frame_are_not_the_record_drug(text):
    fp = _p("half_life", text)
    assert all(v.hours.value != 10.0 for v in fp.values)
    assert _reasons(fp) & {"subject_unresolved", "subject_not_record_drug"}


@pytest.mark.parametrize("text", [
    "drug a's half-life is 4 hours.",
    "For drug a, the half-life is 4 hours.",
    "Drug A's half-life is 4 hours.",
    "For Drug A, the half-life is 4 hours.",
    "The drug's half-life is 4 hours.",
    "The patient's half-life is 4 hours.",
    "In general, the half-life is 4 hours.",
    "For example, the half-life is 4 hours.",
    "In women, the half-life is 4 hours.",
    "In healthy volunteers, the half-life is 4 hours.",
])
def test_d3_record_drug_generic_and_framing_words_stay_clean(text):
    fp = _p("half_life", text)
    (v,) = fp.values
    assert v.review_reasons == [] and v.hours.value == 4.0


def test_d3_upper_and_lower_case_behave_alike():
    for a, b in (("drug b's half-life is 10 hours.", "Drug B's half-life is 10 hours."),
                 ("For drug b, the half-life is 10 hours.", "For Drug B, the half-life is 10 hours.")):
        assert _p("half_life", a).values == [] and _p("half_life", b).values == []
    for a, b in (("drug a's half-life is 4 hours.", "Drug A's half-life is 4 hours."),
                 ("For drug a, the half-life is 4 hours.", "For Drug A, the half-life is 4 hours.")):
        assert len(_clean(_p("half_life", a))) == 1 and len(_clean(_p("half_life", b))) == 1


def test_d3_multiword_record_name_suffix_is_the_record():
    fp = _p("half_life", "valproic acid's half-life is 4 hours.", names=["[SYNTHETIC] valproic acid"])
    assert len(_clean(fp)) == 1


# ------------------------------------------------------------------ D4 --
@pytest.mark.parametrize("text", [
    "The half-life is 4 hours (adverse events are described elsewhere [A2]).",
    "The half-life is 4 hours: adverse events are described elsewhere [A2] in the report.",
    "The half-life is 4 hours (see [A2]).",
])
def test_d4_separate_claim_in_parenthesis_or_after_colon_is_not_attributed(text):
    fp = _p("half_life", text)
    (v,) = fp.values
    assert "A2" not in v.reference_tokens and "A2" in v.nearby_reference_tokens
    assert v.reference_scope in ("none", "sentence_other_clause")
    assert v.review_reasons == []  # the value itself is unaffected


@pytest.mark.parametrize("text,tokens,scope", [
    ("The half-life is 4 hours.[A1]", ["A1"], "sentence_single_value"),
    ("The half-life is 4 hours, in adults.[A1]", ["A1"], "sentence_single_value"),
    ("The half-life is 4.5 hours.[A1]", ["A1"], "sentence_single_value"),
    ("The half-life is 4 hours (in adults).[A1]", ["A1"], "sentence_single_value"),
    ("The half-life is 4 hours (n = 12).[A1]", ["A1"], "sentence_single_value"),
    ("The half-life is 4 hours: in adults.[A1]", ["A1"], "sentence_single_value"),
    ("Half-life: 4 hours [A1]", ["A1"], "sentence_single_value"),
    ("The half-life is 4 hours [A1] (adverse events are described elsewhere [A2]).", ["A1"], "value_window"),
])
def test_d4_condition_or_statistic_aside_stays_attributed(text, tokens, scope):
    fp = _p("half_life", text)
    (v,) = fp.values
    assert v.reference_tokens == tokens and v.reference_scope == scope
    assert "A2" not in v.reference_tokens


def test_d4_a1_and_unrelated_a2_stay_separate():
    fp = _p("half_life", "The half-life is 4 hours.[A1] Adverse events are described elsewhere.[A2]")
    (v,) = fp.values
    assert v.reference_tokens == ["A1"] and v.reference_scope == "sentence_single_value"
    assert v.nearby_reference_tokens == []  # 'nearby' covers the value's own sentence only


def test_d4_unclear_aside_reports_uncertainty_instead_of_exclusive_attribution():
    fp = _p("half_life", "The half-life is 4 hours (adverse events described elsewhere [A2]).[A1]")
    (v,) = fp.values
    assert v.reference_tokens == ["A1"] and v.reference_scope == "sentence_shared"  # not exclusive
    assert v.nearby_reference_tokens == ["A2"]


def test_d4_claim_aside_before_sentence_end_token_makes_it_other_clause():
    fp = _p("half_life", "The half-life is 4 hours (adverse events are described elsewhere [A2]).[A1]")
    (v,) = fp.values
    assert v.reference_tokens == [] and v.reference_scope == "sentence_other_clause"
    assert v.nearby_reference_tokens == ["A1", "A2"]


# ------------------------------------------------- combined examples --
def test_combined_governing_clause_aside_subject_and_reference():
    fp = _p("half_life", "There is no evidence that, for drug b, the half-life (measured in adults) is 4 hours [A2].")
    assert fp.values == [] and "undetermined_statement" in _reasons(fp)


def test_combined_positive_governing_frame_and_claim_aside():
    fp = _p("half_life", "Studies have shown that, for drug a, the half-life is 4 hours "
                         "(adverse events are described elsewhere [A2]).[A1]")
    (v,) = fp.values
    assert v.review_reasons == [] and v.hours.value == 4.0
    assert "A2" not in v.reference_tokens and "A2" in v.nearby_reference_tokens
    (d,) = _derived(fp)
    assert d["status"] == "computed" and d["hours"].value == 20.0


def test_combined_lower_case_next_sentence_subject_and_colon_claim():
    fp = _p("half_life", "drug b's half-life is 10 hours: adverse events are described elsewhere [A2]. "
                         "drug a's half-life is 4 hours.[A1]")
    (v,) = fp.values  # 10 h of drug b dropped, 4 h of the record drug kept
    assert v.hours.value == 4.0 and "subject_unresolved" in _reasons(fp)
    assert "A2" not in v.reference_tokens and "A2" in v.nearby_reference_tokens


def test_combined_whether_aside_and_foreign_frame_in_tmax():
    fp = _p("absorption", "For drug b, it is not known whether, after oral administration, Tmax is 2 hours.")
    assert fp.values == [] and _reasons(fp) & {"hypothetical_or_open_question", "subject_unresolved"}


# ------------------------------------- independent adversarial review --
# Paths found by a separate adversarial probe of the first R3 fix; each was
# reproduced by running the parser before it was fixed.
@pytest.mark.parametrize("field,text", [
    ("half_life", "There is no evidence, however, that the half-life is 4 hours."),
    ("half_life", "We did not, however, find that the half-life is 4 hours."),
    ("half_life", "Studies failed, despite repeated attempts, to establish that the half-life is 4 hours."),
    ("half_life", "Investigators were unable, in several studies, to determine that the half-life is 4 hours."),
    ("half_life", "The half-life, which has never been confirmed, is 4 hours."),
    ("half_life", "The half-life is, it has not been established, 4 hours."),
    ("half_life", "The half-life was, in no study, 4 hours."),
    ("half_life", "The half-life is, according to unconfirmed reports, 4 hours."),
    ("half_life", "The half-life is, possibly, 4 hours."),
    ("half_life", "The half-life, it is claimed, is 4 hours."),
    ("half_life", "The half-life, if confirmed, is 4 hours."),
    ("half_life", "It is not true that the investigators reported that the half-life is 4 hours."),
    ("half_life", "It remains to be shown that the half-life is 4 hours."),
    ("half_life", "It is false that the half-life is 4 hours."),
    ("half_life", "The belief that the half-life is 4 hours is mistaken."),
    ("half_life", "Is the half-life 4 hours?"),
    ("half_life", "drug b's half-life is 8 hours in adults and 12 hours in children."),
    ("absorption", "drug b's peak plasma concentration occurs at 2 hours."),
    ("absorption", "drug b reaches peak plasma concentrations at 2 hours."),
])
def test_review_paths_give_no_clean_value(field, text):
    fp = _p(field, text)
    assert _clean(fp) == [] and _derived(fp) in ([], [d for d in _derived(fp) if d["status"] == "not_computed"])


@pytest.mark.parametrize("text", [
    "compound a's half-life is 10 hours.",
    "For compound a, the half-life is 10 hours.",
    "For drug b and drug c, the half-life is 10 hours.",
    "For the reference drug b, the half-life is 10 hours.",
    "For drug b extended-release tablets, the half-life is 10 hours.",
    "drug bʼs half-life is 10 hours.",
    "drug b`s half-life is 10 hours.",
    "drug b's mean terminal elimination half-life is 10 hours.",
    "the comparator drug's half-life is 10 hours.",
    "The reference product's half-life is 10 hours.",
    "drugs b and c' half-lives are 10 hours.",
    "the two drugs' half-lives are 10 hours.",
    "the metabolite of drug b has a half-life of 10 hours.",
])
def test_review_other_subjects_are_not_credited(text):
    assert not any(v.hours.value == 10.0 for v in _clean(_p("half_life", text)))


@pytest.mark.parametrize("field,text", [
    ("half_life", "For oral administration, the half-life is 10 hours."),
    ("half_life", "In overdose, the half-life is 10 hours."),
    ("half_life", "For drug a hydrochloride, the half-life is 10 hours."),
    ("half_life", "The metabolite of drug a has a half-life of 10 hours."),
    ("half_life", "Clinically, the drug's half-life is 10 hours."),
    ("half_life", "The patients' half-life is 10 hours."),
    ("half_life", "The mean half-life for Japanese subjects was 10 hours."),
    ("half_life", "The half-life was not measured in adults, but in children, 10 hours."),
    ("half_life", "There is no evidence that the half-life of drug b is 4 hours [A2], and the half-life is 10 hours."),
    ("absorption", "drug a reaches peak plasma concentrations at 10 hours."),
    ("absorption", "Tmax is 10 hours for ER tablets."),
])
def test_review_ordinary_texts_keep_the_value(field, text):
    assert any(v.hours.value == 10.0 or v.hours.upper == 10.0 for v in _p(field, text).values)


def test_review_never_shorter_than_is_a_lower_bound():
    for text in ("The half-life is never shorter than 4 hours.", "The half-life isn't shorter than 4 hours."):
        (v,) = _p("half_life", text).values
        assert v.hours.kind == "lower_bound" and v.hours.lower == 4.0 and v.review_reasons == []


@pytest.mark.parametrize("text,a1", [
    ("The half-life is 4 hours (rash is common) [A2].", False),
    ("The half-life of 4 hours (rash is common) supports once daily dosing [A2].", False),
    ("The half-life is 4 hours (e.g. in adults) [A1].", True),
    ("The half-life is 4 hours (i.e. in healthy volunteers) [A1].", True),
    ("The half-life is 4 hours (n = 12, SD 1.1) [A1].", True),
    ("The half-life is 4 hours (Smith et al. [A1]).", True),
    ("The half-life is 4 hours (Table 3 [A1]).", True),
])
def test_review_reference_after_or_inside_parentheses(text, a1):
    (v,) = _p("half_life", text).values
    assert "A2" not in v.reference_tokens
    assert (v.reference_tokens == ["A1"]) is a1
