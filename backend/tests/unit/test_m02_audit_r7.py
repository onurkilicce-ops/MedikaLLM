"""M02-O1-R7: an explicit subject that the capture patterns could not read
is not a generic subject.

On 4dd0e44 (and 90fda26) '20% drug b' and '2.5mg drug b' were not captured;
the empty candidate list then read as "the value has its own generic
subject" and Drug A got a clean value. Now (1) the capture tokens accept '%',
glued units and decimal commas, and (2) a frame that is present but not
(fully) captured adds UNCAPTURED, which is unresolved. Expectations are fixed
independently of the observed output; every text is SYNTHETIC; '5-zoralen' is
an invented name.
"""
from __future__ import annotations

import pytest

from src.timing import calc
from src.timing.parser import PARSER_VERSION, UNCAPTURED, _subject_candidates, parse_field

S = "[SYNTHETIC] "


def _p(text, rec="Drug A"):
    return parse_field("half_life", S + text, stored_max_length=1000, subject_names=["[SYNTHETIC] " + rec])


def _clean(fp):
    return [v for v in fp.values if not v.review_reasons]


def _reasons(fp):
    return {r.reason for r in fp.reviews} | {x for v in fp.values for x in v.review_reasons}


def _derived(fp):
    return [calc.five_half_lives(v, fp.flags) for v in fp.values if v.measure_type == "half_life"]


def _unresolved(fp):
    return _clean(fp) == [] and all(d["status"] == "not_computed" for d in _derived(fp)) and bool(
        _reasons(fp) & {"subject_unresolved", "subject_not_record_drug"})


def _clean_4h(fp):
    (v,) = _clean(fp)
    (d,) = [x for x in _derived(fp)]
    return v.hours.value == 4.0 and d["status"] == "computed" and d["hours"].value == 20.0


def test_parser_version_bumped_for_behaviour_change():
    assert PARSER_VERSION == "m02-text-parser/8"


# ------------------------------------------------------- the four findings --
@pytest.mark.parametrize("text", [
    "For 20% drug b, the half-life is 10 hours.",
    "The half-life of 20% drug b is 10 hours.",
    "For 2.5mg drug b, the half-life is 10 hours.",
    "The half-life of 2.5mg drug b is 10 hours.",
])
def test_findings_are_not_drug_a_measurements(text):
    fp = _p(text)
    assert fp.values == [] and [r.reason for r in fp.reviews] == ["subject_unresolved"]
    (r,) = fp.reviews  # text and position kept
    full = S + text
    assert full[r.value_span.start:r.value_span.end] == "10 hours"
    assert full[r.sentence.start:r.sentence.end] == full


# ------------------------------------------------------ positive controls --
@pytest.mark.parametrize("text,rec", [
    ("For 20% drug a, the half-life is 4 hours.", "Drug A"),
    ("The half-life of 20% drug a is 4 hours.", "Drug A"),
    ("For 2.5mg drug a, the half-life is 4 hours.", "Drug A"),
    ("The half-life of 2.5mg drug a is 4 hours.", "Drug A"),
    ("For 2.5 mg drug a, the half-life is 4 hours.", "Drug A"),
    ("For 10mg drug a, the half-life is 4 hours.", "Drug A"),
    ("The drug's half-life is 4 hours.", "Drug A"),
    ("The half-life is 4 hours.", "Drug A"),
    ("For oral administration, the half-life is 4 hours.", "Drug A"),
    ("The half-life of 5-zoralen is 4 hours.", "5-zoralen"),
    ("For 20% 5-zoralen, the half-life is 4 hours.", "5-zoralen"),
])
def test_record_and_generic_subjects_stay_clean_with_5x(text, rec):
    assert _clean_4h(_p(text, rec))


# ------------------------------------------- earlier negatives stay closed --
@pytest.mark.parametrize("text,rec", [
    ("For 2.5 mg drug b, the half-life is 10 hours.", "Drug A"),
    ("For 10mg drug b, the half-life is 10 hours.", "Drug A"),
    ("For 10 mg 5-zoralen, the half-life is 10 hours.", "Drug A"),
    ("The half-life of magnesium is 10 hours.", "magnesium sulfate"),
    ("The half-life of magnesium sulfate is 10 hours.", "magnesium"),
    ("The half-life of magnesium sulfate is 10 hours.", "sodium chloride"),
])
def test_earlier_negatives_stay_unresolved(text, rec):
    assert _unresolved(_p(text, rec))


# ----------------------------------------------------------- boundary set --
# case, glued / spaced unit, decimal point / comma, percent; written before running
AMOUNTS = ["20%", "20 %", "2.5mg", "2.5 mg", "2,5 mg", "10mg", "10 mg", "2.5MG", "0.5-mg"]
FRAMES = ["For {s}, the half-life is {v} hours.", "The half-life of {s} is {v} hours.",
          "In overdose of {s}, the half-life is {v} hours.", "{s}'s half-life is {v} hours."]


@pytest.mark.parametrize("amount", AMOUNTS)
@pytest.mark.parametrize("frame", FRAMES)
def test_boundary_amount_before_a_foreign_name_is_unresolved(amount, frame):
    for drug in ("drug b", "Drug B", "DRUG B"):
        assert _unresolved(_p(frame.format(s=f"{amount} {drug}", v=10))), drug


@pytest.mark.parametrize("amount", AMOUNTS)
@pytest.mark.parametrize("frame", FRAMES)
def test_boundary_amount_before_the_record_name_is_clean(amount, frame):
    for drug in ("drug a", "Drug A", "DRUG A"):
        assert _clean_4h(_p(frame.format(s=f"{amount} {drug}", v=4))), drug


@pytest.mark.parametrize("frame", FRAMES)
def test_boundary_amount_after_the_name(frame):
    assert _unresolved(_p(frame.format(s="drug b 20%", v=10)))
    assert _clean_4h(_p(frame.format(s="drug a 20%", v=4)))


# Forms the strict patterns cannot read (an unusual character, a colon, brackets,
# an annotation in parentheses, a frame beyond the word limits). The loose frame
# phrase is judged, never dropped: a foreign name stays unresolved, the record
# name is read. (The first R7 draft expected review for the record drug too;
# an independent probe showed that blanket marking over-rejected ordinary
# frames, so the expectation is that the readable name decides.)
UNUSUAL = [
    "For {d}®, the half-life is {v} hours.",
    "The half-life of {d}® is {v} hours.",
    "{d}®'s half-life is {v} hours.",
    "For {d}: the half-life is {v} hours.",
    "In [{d}], the half-life is {v} hours.",
    "For {d} (oral), the half-life is {v} hours.",
    "For {d} given once daily with food to adults and children older than twelve years in "
    "clinical practice, the half-life is {v} hours.",
]


@pytest.mark.parametrize("tpl", UNUSUAL)
def test_boundary_unusual_forms_foreign_name_is_unresolved(tpl):
    assert _unresolved(_p(tpl.format(d="drug b", v=10)))


@pytest.mark.parametrize("tpl", UNUSUAL)
def test_boundary_unusual_forms_record_name_is_read(tpl):
    assert _clean_4h(_p(tpl.format(d="drug a", v=4)))


def test_uncaptured_marker_is_explicit():
    # a frame present but not captured is never dropped: its loose phrase is a candidate
    assert "drug b®" in [c.strip() for c in _subject_candidates("For drug b®, the half-life is ")]
    # a frame whose phrase has no readable word is the explicit UNCAPTURED marker
    assert UNCAPTURED in _subject_candidates("For ®®, the half-life is ")
    assert UNCAPTURED not in _subject_candidates("For drug b, the half-life is ")
    assert UNCAPTURED not in _subject_candidates("The half-life is ")  # no frame: a generic subject
    assert UNCAPTURED not in _subject_candidates("The half-life of ~")  # a value qualifier, not a subject
    assert _unresolved(_p("For ®®, the half-life is 10 hours."))


# ------------------------- independently verified probe findings (R7 review) --
@pytest.mark.parametrize("text", [
    "The half-life is 10 hours for 20% drug b.",
    "The half-life is 10 hours for 2,5 mg drug b.",
    "The half-life is 10 hours for 20 mg drug b.",
    "The half-life is 10 hours of 2.5 mg drug b.",
    "The half-life is 10 hours for the 20 mg dose of drug b.",
])
def test_review_trailing_foreign_subject_is_unresolved(text):
    assert _unresolved(_p(text))


@pytest.mark.parametrize("text", [
    "The half-life is 4 hours for 20 mg drug a.",
    "The half-life is 4 hours for the 20 mg dose of drug a.",
    "The half-life is 4 hours for most patients.",
    "In healthy adults (n=12), the half-life is 4 hours.",
    "For the 10 mg/5 mL solution, the half-life is 4 hours.",
    "In patients with CrCl < 30 mL/min, the half-life is 4 hours.",
    "For doses > 10 mg, the half-life is 4 hours.",
    "For the 0.5 mg/mL formulation, the half-life is 4 hours.",
    "In adults (18–65 y), the half-life is 4 hours.",
    "In patients on dialysis (HD), the half-life is 4 hours.",
    "In patients' plasma, the half-life is 4 hours.",
    "In the fed state (high-fat meal), the half-life is 4 hours.",
    "In patients with moderate (Child-Pugh B) hepatic impairment, the half-life is 4 hours.",
    "For the 2.5 mg/kg dose, the half-life is 4 hours.",
    "The half-life of the 2.5 mg/kg dose is 4 hours.",
    "The half-life of Drug A 2.5 mg/kg is 4 hours.",
    "For the 2.5% cream, the half-life is 4 hours.",
    "In summary: the half-life is 4 hours.",
    "In patients with severe hepatic impairment who were also receiving concomitant strong inhibitors for "
    "more than two weeks, the half-life was 4 hours.",
])
def test_review_ordinary_frames_are_not_over_rejected(text):
    assert _clean_4h(_p(text))


def test_review_approximate_value_after_of_is_not_a_subject():
    (v,) = _p("The half-life of ~4 hours supports once-daily dosing.").values
    assert v.review_reasons == [] and v.approximate is True


# second independent probe round: the 'has' frame and 'of' chains
@pytest.mark.parametrize("text", [
    "drug b® has a half-life of 10 hours.",
    "Drug B® has a half-life of 10 hours.",
    "drug b (20 mg) has a half-life of 10 hours.",
    "Drug B (oral) has a half-life of 10 hours.",
    "2.5 mg/mL drug b has a half-life of 10 hours.",
    "very long named synthetic drug b analogue x has a half-life of 10 hours.",
    "The half-life of the formulation of drug b is 10 hours.",
    "For the tablet of drug b, the half-life is 10 hours.",
    "The half-life of the metabolite of drug b is 10 hours.",
])
# Documented limit, NOT a pass: a foreign subject separated from 'has' by an
# apposition or interrupter ('drug b, a synthetic agent, has ...', 'drug b, in
# contrast, has ...') is not read; a clause-wide rule over-rejected ordinary
# record sentences in the independent probe (RULES 8h).
def test_review2_has_frame_and_of_chain_foreign_subject(text):
    assert _unresolved(_p(text))


@pytest.mark.parametrize("text", [
    "Drug A® has a half-life of 4 hours.",
    "Drug A (oral) has a half-life of 4 hours.",
    "The drug (oral) has a half-life of 4 hours.",
    "It has a half-life of 4 hours.",
    "Drug A, a synthetic agent, has a half-life of 4 hours.",
    "This agent has a half-life of 4 hours.",
    "The drug, which is cleared by the kidney, has a half-life of 4 hours.",
    "Clinical studies in healthy adults have shown it has a half-life of 4 hours.",
    "In adults, drug a has a half-life of 4 hours.",
    "The half-life of the formulation of drug a is 4 hours.",
    "For the tablet of drug a, the half-life is 4 hours.",
    "For doses below 2.5 mg/kg, the half-life of Drug A is 4 hours.",
    "For doses greater than 2.5 mg/kg, the half-life is 4 hours.",
    "In 10-20% of patients, the half-life was 4 hours.",
    "In patients weighing >100 kg, the half-life was 4 hours.",
    "In the 2.5-5 mg/kg cohort, the half-life was 4 hours.",
    "In the mg/kg/day cohort, the half-life was 4 hours.",
])
def test_review2_has_frame_of_chain_and_descriptors_stay_clean(text):
    assert _clean_4h(_p(text))


@pytest.mark.parametrize("text", [
    "For 20% of patients, the half-life is 4 hours.",
    "In 20% of patients, the half-life is 4 hours.",
    "For the 2.5mg dose, the half-life is 4 hours.",
    "For the 10mg tablet, the half-life is 4 hours.",
    "In 12 healthy volunteers, the half-life is 4 hours.",
    "The half-life of the 2.5mg tablet is 4 hours.",
])
def test_boundary_amount_only_subjects_stay_generic(text):
    assert _clean_4h(_p(text))


# -------------------------------------------------- source behaviour kept --
def test_source_attribution_unchanged_with_amount_subject():
    (v,) = _p("For 2.5mg drug a, the half-life is 4 hours [A1] - 10 patients developed rash [A2].").values
    assert v.reference_tokens == ["A1"] and v.nearby_reference_tokens == ["A2"] and v.reference_scope == "value_window"



# third independent probe round (narrow 'has' subject, 'of' chains, more frame openers)
@pytest.mark.parametrize("text", [
    "In the treatment of hypertension, the half-life is 4 hours.",
    "In the treatment of hypertension, Drug A has a half-life of 4 hours.",
    "Drug A, given orally, has a half-life of 4 hours.",
    "Drug A, administered as a single dose, has a half-life of 4 hours.",
    "Drug A, 20 mg once daily, has a half-life of 4 hours.",
    "Drug A, at doses of 10 to 40 mg, has a half-life of 4 hours.",
    "Drug A, synthetic agonist of the X receptor, has a half-life of 4 hours.",
    "Based on population pharmacokinetic analysis, Drug A has a half-life of 4 hours.",
    "Consequently, Drug A has a half-life of 4 hours.",
    "Once absorbed, Drug A has a half-life of 4 hours.",
    "At steady state, it has a half-life of 4 hours.",
    "It is estimated that, at therapeutic doses, Drug A has a half-life of 4 hours.",
    "Plasma concentrations decline biexponentially, and Drug A has a half-life of 4 hours.",
    "Patients with mild, moderate, or severe hepatic impairment have a half-life of 4 hours.",
    "After oral administration, the half-life is 4 hours.",
    "Following a single dose, the half-life is 4 hours.",
    "With food, the half-life is 4 hours.",
    "During pregnancy, the half-life is 4 hours.",
    "After discontinuation, the half-life is 4 hours.",
    "Drug A has a mean terminal elimination half-life of 4 hours.",
    "Drug A demonstrates a half-life of 4 hours.",
    "The half-life after overdose of drug a is 4 hours.",
])
def test_review3_ordinary_sentences_stay_clean(text):
    assert _clean_4h(_p(text))


@pytest.mark.parametrize("text", [
    "Drug b has a mean terminal elimination half-life of 10 hours.",
    "Drug b had a reported mean terminal half-life of 10 hours.",
    "The tablet of drug b has a mean terminal elimination half-life of 10 hours.",
    "Drug b demonstrates a half-life of 10 hours.",
    "The tablets of drug b demonstrate a half-life of 10 hours.",
    "Tablets of drug b were found to have a half-life of 10 hours.",
    "The tablets of drug b are reported to have a half-life of 10 hours.",
    "The half-life after overdose of drug b is 10 hours.",
    "The half-life after an overdose of drug b is 10 hours.",
    "The half-life in overdose of drug b is 10 hours.",
    "The half-life following administration of drug b is 10 hours.",
    "The half-life after use of drug b is 10 hours.",
    "Following overdose of drug b, the half-life is 10 hours.",
    "After administration of drug b, the half-life is 10 hours.",
    "After overdose of drug b, half-life was 10 hours.",
    "With tablets of drug b, the half-life is 10 hours.",
    "The half-life of the solution of the tablet of drug b is 10 hours.",
    "The half-life of the dose of the formulation of drug b is 10 hours.",
    "The dose of the formulation of drug b has a half-life of 10 hours.",
])
def test_review3_foreign_subject_in_has_frame_and_of_chain(text):
    assert _unresolved(_p(text))


# fourth independent probe round: event openers judge only their 'of' chains;
# passive 'is reported / has been shown to have'; 'studies/trials of X'
@pytest.mark.parametrize("text", [
    "Drug A is reported to have a half-life of 4 hours.",
    "Drug A has been shown to have a half-life of 4 hours.",
    "Upon reaching steady state, Drug A has a half-life of 4 hours.",
    "During continuous infusion, the half-life of Drug A is approximately 4 hours.",
    "With multiple daily doses of 20 mg, the half-life was 4 hours.",
    "Following the first dose of the maintenance regimen, the half-life was 4 hours.",
    "Following topical application of 2.5% cream, the half-life was 4 hours.",
    "After removal of the patch, the apparent half-life was 4 hours.",
    "With concomitant food intake, the half-life was 4 hours.",
    "During the third trimester of pregnancy, the half-life is 4 hours.",
    "Following ophthalmic instillation of one drop, the half-life was 4 hours.",
    "In studies of healthy volunteers, the half-life was 4 hours.",
])
def test_review4_event_openers_and_passive_stay_clean(text):
    (v,) = _clean(_p(text))
    assert v.hours.value == 4.0


@pytest.mark.parametrize("text", [
    "In studies of drug b, the half-life was 10 hours.",
    "In trials of drug b, the half-life was 10 hours.",
    "Drug B has been shown to have a half-life of 10 hours.",
    "drug b has been shown to have a half-life of 10 hours.",
])
def test_review4_study_chain_and_passive_foreign_subject(text):
    assert _unresolved(_p(text))
