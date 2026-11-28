"""Regressions for defects found by the independent adversarial review of the
first M-02 implementation (each one reproduced by a separate verifier before
it was fixed). Inputs are the reviewers' synthetic sentences; expected
results come from the finding's "expected" column, not from parser output.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.timing import calc
from src.timing.models import TimingCompareRequest
from src.timing.parser import parse_field

S = "[SYNTHETIC] "


def _hl(text):
    return parse_field("half_life", S + text, stored_max_length=1000)


def _ab(text):
    return parse_field("absorption", S + text)


def _derived(fp):
    return [calc.five_half_lives(v, fp.flags) for v in fp.values if v.measure_type == "half_life"]


def _no_clean_value(fp):
    """Nothing may be presented as an unflagged value, and no 5x computed."""
    assert all(v.review_reasons for v in fp.values), [(v.hours, v.review_reasons) for v in fp.values]
    assert all(d["status"] == "not_computed" for d in _derived(fp))


# PB-01: unicode hyphen / minus / figure dash ranges
@pytest.mark.parametrize("dash", ["‐", "−", " − ", " ‒ ", "–", "—", "‑"])
def test_pb01_unicode_dash_range_is_a_range(dash):
    fp = _hl(f"The half-life is 3{dash}5 h.")
    (v,) = fp.values
    assert (v.hours.kind, v.hours.lower, v.hours.upper) == ("range", 3.0, 5.0)
    d = calc.five_half_lives(v, fp.flags)
    assert (d["hours"].lower, d["hours"].upper) == (15.0, 25.0)


# PB-02: '.[A1]' without a space still ends the sentence; tokens stay with their sentence
def test_pb02_token_without_space_splits_sentences_and_keeps_tokens_apart():
    fp = _hl("Half life was 12h.[A1]Half life in ESRD was 40h.[A2]")
    a, b = fp.values
    assert a.reference_tokens == ["A1"] and b.reference_tokens == ["A2"]
    assert a.conditions["population"] == [] and b.conditions["population"] == ["esrd"]
    fp = _ab("Tmax is 3 h.[A12]Bioavailability is 80%.[A13]")
    (t,) = fp.values
    assert t.reference_tokens == ["A12"]


# PB-03: AUC interval subscripts are not durations
@pytest.mark.parametrize("text", [
    "Peak plasma concentrations and AUC0–24h increased proportionally.",
    "Peak plasma concentrations and AUC0-24h increased proportionally.",
    "Peak plasma concentrations and AUC(0-24 h) increased proportionally.",
])
def test_pb03_auc_interval_is_not_tmax(text):
    fp = _ab(text)
    assert fp.values == []


def test_pb03_real_tmax_next_to_auc_is_kept_unflagged():
    fp = _ab("Tmax was 2 h and AUC0–24h was 300 ng·h/mL.")
    (t,) = fp.values
    assert t.hours.value == 2.0 and t.review_reasons == []


# PB-04: 'increased from X to Y' is a change between conditions, not a range
@pytest.mark.parametrize("field,text", [
    ("half_life", "The half-life increased from 3 to 8 h in patients with cirrhosis."),
    ("absorption", "Food increased Tmax from 2 to 4 h."),
])
def test_pb04_change_statement_is_not_a_range(field, text):
    fp = parse_field(field, S + text, stored_max_length=1000 if field == "half_life" else None)
    assert fp.values == []
    assert "change_statement" in {r.reason for r in fp.reviews}


def test_pb04_ranging_from_is_still_a_range():
    (v,) = _ab("The time to peak ranges from 2 to 4 hours.").values
    assert (v.hours.lower, v.hours.upper) == (2.0, 4.0)


# PB-05: number lists never pick one value silently
@pytest.mark.parametrize("text", [
    "The half-life was 3, 4, and 5 hours in three studies.",
    "The half-life is 3 h, 4 h and 5 h in three studies.",
    "The half-life was 3, 4 or 5 hours.",
])
def test_pb05_number_lists_are_not_resolved_silently(text):
    _no_clean_value(_hl(text))


# PB-06 / CS-02 / CS-05: durations of other events are not half-life / Tmax
@pytest.mark.parametrize("field,text", [
    ("half_life", "The drug is removed by hemodialysis in 4 hours."),
    ("half_life", "The drug is cleared from plasma in about 6 hours."),
    ("half_life", "Elimination is complete within 7 days."),
])
def test_pb06_other_event_durations_are_not_half_lives(field, text):
    fp = _hl(text)
    assert fp.values == [] and fp.status == "unparsed_needs_review"


def test_pb06_later_and_elimination_clauses_do_not_add_half_lives():
    fp = _hl("The half-life is 4 h and plasma levels are undetectable 24 h later.")
    assert [v.hours.value for v in fp.values] == [4.0]
    fp = _hl("The terminal half-life is 30 hours; elimination is complete in 7 days.")
    assert [v.hours.value for v in fp.values] == [30.0]
    fp = _hl("The half-life is 30 hours in adults; elimination takes about 7 days in children.")
    assert [v.hours.value for v in fp.values] == [30.0]


def test_cs02_persistence_after_tmax_is_not_tmax():
    fp = _ab("Peak plasma concentrations are reached within 1 hour in adults; serum levels remain "
             "elevated for up to 8 hours.")
    (t,) = fp.values
    assert (t.hours.kind, t.hours.upper) == ("upper_bound", 1.0)


def test_cs05_field_only_needs_a_bare_value():
    (v,) = parse_field("half_life", "4-6 hours", stored_max_length=1000).values
    assert v.basis == "field_only"
    (v,) = parse_field("half_life", "Approximately 2 hours in adults.", stored_max_length=1000).values
    assert v.basis == "field_only" and v.conditions["population"] == ["adults"]


# PB-07: no split after an abbreviation; condition stays with its own value
def test_pb07_abbreviation_does_not_move_a_condition():
    fp = _hl("The half-life (approx. 5 h) is prolonged in elderly pts. (i.e. 9 h).")
    assert len(split := [v for v in fp.values]) <= 2
    five = [v for v in fp.values if v.hours.value == 5.0]
    nine = [v for v in fp.values if v.hours.value == 9.0]
    assert five and "elderly" not in five[0].conditions["population"]
    for v in nine:
        assert "elderly" in v.conditions["population"]
    assert split  # at least the unconditioned 5 h is reported


# PB-08 / CS-01: windows and condition attribution
def test_pb08_age_expression_does_not_cut_the_window():
    (v,) = _hl("The half-life in patients aged 65 years was 12 hours.").values
    assert "aged 65 years" in v.conditions["population"]
    (t,) = _ab("Tmax was 1 h in children 2 to 12 years.").values
    assert "children 2 to 12 years" in t.conditions["population"]


def test_pb08_parenthesis_opens_the_window_of_the_value_inside_it():
    a, b = _hl("The half-life is 5 h (CYP2D6 poor metabolizers: 20 h).").values
    assert a.conditions["population"] == []
    assert any("poor metabolizer" in p for p in b.conditions["population"])
    assert a.conflict_group is None and b.conflict_group is None


def test_pb08_leading_clause_applies_to_later_windows():
    fp = _hl("In children, Tmax is 1 h and the half-life is 3 h.")
    (v,) = fp.values
    assert v.hours.value == 3.0 and v.conditions["population"] == ["children"]


def _pop(v):
    return " | ".join(v.conditions["population"])


def test_pb08_leading_clause_does_not_override_a_window_own_condition():
    a, b = _hl("In healthy adults, the half-life is 4 hours and 12 hours in patients with renal impairment.").values
    assert a.conditions["population"] == ["healthy adults"]
    assert "renal impairment" in _pop(b) and "healthy" not in _pop(b)


@pytest.mark.parametrize("text,first,second", [
    ("The half-life is 4 hours, and in patients with severe renal impairment, it is 20 hours.",
     None, "severe renal impairment"),
    ("In adults, the half-life is 4 hours; in children, 2 hours.", "adults", "children"),
    ("The half-life is 5 h (i.v.) and 7 h (p.o.).", "", ""),
])
def test_cs01_conditions_go_to_the_right_value(text, first, second):
    a, b = _hl(text).values
    if first is None:
        assert a.conditions["population"] == [] and second in _pop(b)
    elif first:
        assert _pop(a) == first and _pop(b) == second
    else:
        assert a.conditions["route"] == ["i.v."] and b.conditions["route"] == ["p.o."]


# PB-09: the same condition written differently still conflicts
@pytest.mark.parametrize("text", [
    "After oral administration the half-life is 5 h. When given orally, the half-life is 8 h.",
    "The half-life in adults is 5 h. In adult patients the half-life was 7 h.",
])
def test_pb09_canonical_conditions_for_conflicts(text):
    fp = _hl(text)
    assert len(fp.values) == 2
    assert fp.values[0].conflict_group == fp.values[1].conflict_group is not None
    _no_clean_value(fp)


# PB-10: a token inside one value's clause is not attached to the other value
def test_pb10_tokens_inside_a_clause_stay_with_that_value():
    a, b = _hl("The half-life is 5 h [A1] in adults and 9 h [A2] in neonates.").values
    assert a.reference_tokens == ["A1"] and a.reference_scope == "value_window"
    assert b.reference_tokens == ["A2"] and b.reference_scope == "value_window"


def test_pb10_sentence_end_token_with_two_values_is_shared_not_verified():
    a, b = _hl("The half-life is 5 h in adults and 9 h in neonates.[A1]").values
    assert a.reference_scope == b.reference_scope == "sentence_shared"
    (c,) = _hl("The half-life is 5 h.[A1]").values
    assert c.reference_scope == "sentence_single_value"


# PB-11: route shorthand and bare 'parent'
def test_pb11_route_shorthand_and_parent():
    a, b = _hl("The half-life is 5 h (i.v.) and 7 h (p.o.).").values
    assert b.conditions["route"] == ["p.o."]
    fp = _ab("Tmax for the metabolite M1 is 6 h and for parent 2 h.")
    met, par = fp.values
    assert met.conditions["analyte"] == "metabolite" and par.conditions["analyte"] == "parent"


# CS-03: mixed-unit +/-
def test_cs03_plus_minus_with_mixed_units():
    (v,) = _hl("The half-life was 1.5 h ± 20 min.").values
    assert (v.original.value, v.unit, v.hours.value) == (1.5, "h", 1.5)
    assert v.dispersion == (20.0, round(20 / 60, 6), "min")
    (t,) = _ab("Peak plasma concentrations are reached 2 h ± 30 min after oral administration.").values
    assert (t.unit, t.hours.value, t.dispersion[1]) == ("h", 2.0, 0.5)


# CS-06: species and co-administration are conditions
def test_cs06_species_and_coadministration():
    fp = _hl("In rats, the half-life was 10 hours.")
    (v,) = fp.values
    assert v.conditions["other"] == ["rats"]
    assert "non_human_or_in_vitro" in calc.five_half_lives(v, fp.flags)["not_computed_reasons"]
    a, b = _hl("The half-life is 4 hours when given alone and 12 hours when co-administered with ritonavir.").values
    assert a.conditions["other"] and b.conditions["other"]
    assert a.conflict_group is None and b.conflict_group is None


# CS-07: metabolite named in another sentence
def test_cs07_metabolite_elsewhere_in_field_blocks_5x_for_unmarked_value():
    fp = _hl("X is converted to its active metabolite Y. Its half-life is 20 hours.")
    (v,) = fp.values
    d = calc.five_half_lives(v, fp.flags)
    assert d["status"] == "not_computed" and "analyte_ambiguous_metabolite_mentioned" in d["not_computed_reasons"]


# CS-08: non-phase words
def test_cs08_initial_dose_and_beta_lactam_are_not_phases():
    (v,) = _hl("After an initial dose, the elimination half-life is 10 hours.").values
    assert calc.five_half_lives(v, []) ["status"] == "computed"
    fp = _hl("The half-life of the beta-lactam is 2 hours.")
    (v,) = fp.values
    assert v.conditions["phase"] == [] and calc.five_half_lives(v, fp.flags)["status"] == "computed"
    fp = _hl("The volume of distribution is large and the half-life is 6 hours.")
    (v,) = fp.values
    assert calc.five_half_lives(v, fp.flags)["status"] == "computed"


# CS-09: 'half-life is 4 hours after oral administration' is a half-life
def test_cs09_route_suffix_after_a_half_life_value():
    (v,) = _hl("The elimination half-life is 4 hours after oral administration.").values
    assert v.hours.value == 4.0 and v.conditions["route"] == ["oral"]
    fp = _hl("The half-life was measured 2 hours after a single dose.")
    assert fp.values == []


# M02-API-1: only ASCII digits
@pytest.mark.parametrize("bad", ["DB٠٠٠٠٦", "DB００００６",
                                 "DB00006\n", "DB0000٦"])
def test_api1_non_ascii_digits_rejected(bad):
    with pytest.raises(ValidationError):
        TimingCompareRequest(drug_ids=["DB00006", bad])


# Implementer spot check on a fixed-seed sample of real stored text (patterns
# re-written here as synthetic sentences; no stored text is reproduced).
def test_spot_later_concentration_is_not_tmax():
    (t,) = _ab("Peak serum levels of 2.6 mcg/mL were reached at 2 hours, decreasing to 1.4 mcg/mL at "
               "24 hours.").values
    assert t.hours.value == 2.0


@pytest.mark.parametrize("text", [
    "The AUC from 0 to 28 days was 114.2 h*uM and Cmax was reached.",
    "Tmax was not reported; AUC was 2,488 ng·h/mL.",
    "The time to peak was not reported; exposure was 300 h x ng/mL.",
])
def test_spot_auc_units_are_not_durations(text):
    assert _ab(text).values == []


def test_spot_label_bracket_ends_a_sentence():
    a, b = _ab("Fasted subjects reached peak plasma concentrations in 2.9 hours.[Label] Subjects given a "
               "high fat meal reached peak plasma concentrations in 6.4 hours.").values
    assert a.conditions["food_state"] == ["fasted"] and a.reference_tokens == []
    assert b.conditions["food_state"] == ["high fat meal"]


def test_spot_versus_number_pair_is_not_attributed():
    fp = _hl("The plasma elimination half-life was prolonged (13.6 versus 6 hours) in elderly volunteers "
             "compared with younger volunteers.")
    assert fp.values == []
    assert "number_list_shared_unit" in {r.reason for r in fp.reviews}


def test_spot_disease_groups_and_leading_context_are_kept():
    a, b = _hl("The half-life is 21.3 hours in patients with COPD and 16.0 hours in patients with asthma.").values
    assert _pop(a) == "patients with copd" and _pop(b) == "patients with asthma"
    fp = _hl("Renal function impairment causes a marked increase in half life (9 to 30 hours intravenously, "
             "15.7 to 18.2 hours orally).")
    for v in fp.values:
        assert "renal function impairment" in _pop(v)


def test_spot_delay_amount_table_label_and_respectively():
    fp = _ab("A high-fat meal decreased Cmax by 26% with a tmax delay of 2 hours.")
    assert fp.values == [] and "change_amount" in {r.reason for r in fp.reviews}
    fp = _ab("Mean Tmax (1 h): 1.7 in the fasted state.")
    assert fp.values == [] and "table_layout" in {r.reason for r in fp.reviews}
    fp = _ab("The median Tmax of the parent and its metabolite was 4 hours and 6 hours, respectively.")
    assert fp.values and all("respectively_construct" in v.review_reasons for v in fp.values)
    assert fp.status == "parsed_needs_review"


def test_spot_delay_amounts_are_not_tmax():
    for text in ("Taking the drug with food causes a 3 hour delay in Tmax and a 10% decrease in AUC.",
                 "With a high-fat meal, peak plasma levels are delayed for about 1 to 2 hours."):
        fp = _ab(text)
        assert fp.values == [], text
        assert "change_amount" in {r.reason for r in fp.reviews}


def test_spot_between_and_inside_an_age_range_is_not_a_window_boundary():
    fp = _hl("The terminal half-life was 44.6 h in adolescents between 12 and 18 years old, and 48.2 h in adults.")
    a, b = fp.values
    assert "adolescents" in _pop(a) and "18 years old" in _pop(a)
    assert _pop(b) == "adults"


def test_spot_single_value_clause_stops_at_semicolon():
    (v,) = _hl("The elimination half-life is 4.7 hours following oral administration; the terminal half-life "
               "is similar regardless of route (inhalation and intravenous).").values
    assert v.conditions["route"] == ["oral"]
