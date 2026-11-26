"""M02-O1-R5: subject and source boundaries on 91789f3.

D3-A: a condition or group word next to a name must not turn the candidate
into "no subject". D3-B: a partial name overlap (prefix/suffix) is not a
record match. D4: a dash followed by a separate numbered statement is not a
range. Expectations are fixed independently of the observed output; every
text is SYNTHETIC and 'Drug A' is the invented record name.
"""
from __future__ import annotations

import pytest

from src.timing import calc
from src.timing.parser import PARSER_VERSION, parse_field

S = "[SYNTHETIC] "
A = ["[SYNTHETIC] Drug A"]


def _p(text, names=A, field="half_life"):
    return parse_field(field, S + text, stored_max_length=1000 if field == "half_life" else None,
                       subject_names=names)


def _clean(fp):
    return [v for v in fp.values if not v.review_reasons]


def _derived(fp):
    return [calc.five_half_lives(v, fp.flags) for v in fp.values if v.measure_type == "half_life"]


def _no_clean_no_5x(fp):
    return _clean(fp) == [] and all(d["status"] == "not_computed" for d in _derived(fp))


def test_parser_version_bumped_for_behaviour_change():
    assert PARSER_VERSION.startswith("m02-text-parser/") and int(PARSER_VERSION.rsplit("/", 1)[1]) >= 6


# ---------------------------------------------------------------- D3-A --
CONDITIONS = ["", " monotherapy", " in adults", " in overdose", " in overdose in adults",
              " in patients with renal impairment", " extended-release tablets", " 10 mg",
              " in healthy volunteers after oral dosing"]


@pytest.mark.parametrize("cond", CONDITIONS)
@pytest.mark.parametrize("tpl", ["For {s}{c}, the half-life is {v} hours.", "The half-life of {s}{c} is {v} hours.",
                                 "In overdose of {s}{c}, the half-life is {v} hours."])
def test_d3a_foreign_subject_with_any_condition_is_never_clean(tpl, cond):
    for subject in ("drug b", "Drug B", "drug b hydrochloride", "compound a"):
        fp = _p(tpl.format(s=subject, c=cond, v=10))
        assert _no_clean_no_5x(fp), (subject, cond)
        assert {r.reason for r in fp.reviews} & {"subject_unresolved", "subject_not_record_drug"}


@pytest.mark.parametrize("cond", CONDITIONS)
@pytest.mark.parametrize("tpl", ["For {s}{c}, the half-life is {v} hours.", "The half-life of {s}{c} is {v} hours.",
                                 "In overdose of {s}{c}, the half-life is {v} hours."])
def test_d3a_record_subject_with_any_condition_stays_clean(tpl, cond):
    for subject in ("drug a", "Drug A", "drug a hydrochloride"):
        fp = _p(tpl.format(s=subject, c=cond, v=4))
        assert len(_clean(fp)) == 1, (subject, cond)


def test_d3a_audit_examples_exactly():
    for text in ("For drug b monotherapy, the half-life is 10 hours.",
                 "In overdose of drug b in adults, the half-life is 10 hours."):
        fp = _p(text)
        assert fp.values == [] and [r.reason for r in fp.reviews] == ["subject_unresolved"]


@pytest.mark.parametrize("text", [
    "For drug a monotherapy, the half-life is 4 hours.",
    "In overdose of drug a in adults, the half-life is 4 hours.",
    "For drug a in overdose, the half-life is 4 hours.",
    "The drug's half-life is 4 hours.",
    "For oral administration, the half-life is 4 hours.",
    "For monotherapy, the half-life is 4 hours.",
    "In adults, the half-life is 4 hours.",
    "In general, the half-life is 4 hours.",
    "In the event of overdose, the half-life is 4 hours.",
    "In children aged 2 to 12 years, the half-life is 4 hours.",
    "For the 10 mg dose, the half-life is 4 hours.",
    "The mean half-life for Japanese subjects was 4 hours.",
    "Patients who failed to respond had a half-life of 4 hours.",
    "The elimination half-life of the extended-release form is 4 hours.",
])
def test_d3a_positive_and_subjectless_settings(text):
    fp = _p(text)
    (v,) = fp.values
    assert v.review_reasons == [] and v.hours.value == 4.0
    (d,) = _derived(fp)
    assert d["status"] == "computed" and d["hours"].value == 20.0


# ---------------------------------------------------------------- D3-B --
@pytest.mark.parametrize("record,text_name,match", [
    ("magnesium sulfate", "magnesium sulfate", True),
    ("magnesium sulfate", "magnesium", False),          # audit example 3
    ("magnesium", "magnesium sulfate", False),          # audit example 4
    ("sodium chloride", "magnesium sulfate", False),
    ("valproic acid", "acid", False),
    ("acid", "valproic acid", False),
    ("Magnesium Sulfate", "Magnesium", False),          # capitalised path, same rule
    ("magnesium sulfate", "Magnesium Sulfate", True),
    ("Drug A", "drug a hydrochloride", True),           # salt of the same base name
    ("Drug A", "drug a sodium", True),
    ("drug a sodium", "drug a", True),
    ("Drug A", "drug a b", False),
])
@pytest.mark.parametrize("cond", ["", " in overdose", " in adults"])
def test_d3b_only_an_equal_normalized_name_is_the_record(record, text_name, match, cond):
    fp = _p(f"The half-life of {text_name}{cond} is 10 hours.", names=["[SYNTHETIC] " + record])
    if match:
        assert len(_clean(fp)) == 1
    else:
        assert _no_clean_no_5x(fp)


# ------------------------------------------------------------------ D4 --
@pytest.mark.parametrize("dash", [" - ", " – ", " — ", " -- ", "—"])
@pytest.mark.parametrize("claim", ["10 patients developed rash [A2]", "2 subjects withdrew [A2]",
                                   "10% of patients had rash [A2]", "3 studies are described elsewhere [A2]"])
def test_d4_numbered_statement_after_a_dash_is_not_the_source(dash, claim):
    (v,) = _p(f"The half-life is 4 hours{dash}{claim}.").values
    assert v.reference_tokens == [] and v.nearby_reference_tokens == ["A2"] and v.reference_scope == "none"
    (v,) = _p(f"The half-life is 4 hours [A1]{dash}{claim}.").values
    assert v.reference_tokens == ["A1"] and v.nearby_reference_tokens == ["A2"]


def test_d4_audit_examples_exactly():
    for text in ("The half-life is 4 hours - 10 patients developed rash [A2].",
                 "The half-life is 4 hours – 10 patients developed rash [A2]."):
        (v,) = _p(text).values
        assert (v.reference_tokens, v.nearby_reference_tokens, v.reference_scope) == ([], ["A2"], "none")


@pytest.mark.parametrize("text,value", [
    ("The half-life is 4-6 hours [A1].", (4.0, 6.0)),
    ("The half-life is 4 – 6 hours [A1].", (4.0, 6.0)),
    ("The half-life is 4 hours - 6 hours [A1].", (4.0, 6.0)),
    ("The half-life is 4 hours – 6 hours [A1].", (4.0, 6.0)),
])
def test_d4_ranges_stay_ranges_with_their_source(text, value):
    (v,) = _p(text).values
    assert (v.hours.lower, v.hours.upper) == value and v.reference_tokens == ["A1"]


@pytest.mark.parametrize("text", [
    "The half-life is 4 hours [A1] — in adults — adverse events are described elsewhere [A2].",
    "The half-life is 4 hours — in adults [A1] — adverse events are described elsewhere [A2].",
    "The half-life is 4 hours (in adults) [A1].",
    "The half-life is 4 hours.[A1]",
    "The elimination half-life of the extended-release form is 4 hours [A1].",
])
def test_d4_explicit_a1_kept_and_a2_separated(text):
    (v,) = _p(text).values
    assert v.reference_tokens == ["A1"] and "A2" not in v.reference_tokens


# ------------------------------------------------------------ combined --
def test_combined_foreign_subject_condition_and_numbered_dash_statement():
    fp = _p("For drug b monotherapy in adults, the half-life is 10 hours - 10 patients developed rash [A2].")
    assert _no_clean_no_5x(fp)


def test_combined_record_subject_condition_and_numbered_dash_statement():
    (v,) = _p("For drug a monotherapy in adults, the half-life is 4 hours [A1] – 10 patients developed "
              "rash [A2].").values
    assert v.review_reasons == [] and v.reference_tokens == ["A1"] and v.nearby_reference_tokens == ["A2"]
