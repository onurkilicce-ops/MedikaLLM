"""M02-O1-D1: the six findings of the independent audit (Astra) on 6776fac.

Each finding has a positive (still parsed cleanly), a near-but-different and a
negative/ambiguous example. All texts are SYNTHETIC; they are audit evidence,
not drug data and not an expert acceptance set.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.timing import calc, demo_guard
from src.timing.parser import parse_field

S = "[SYNTHETIC] "


def _hl(text, names=None):
    return parse_field("half_life", S + text, stored_max_length=1000, subject_names=names)


def _ab(text, names=None):
    return parse_field("absorption", S + text, subject_names=names)


def _clean(fp):
    return [v for v in fp.values if not v.review_reasons]


def _reasons(fp):
    return {r.reason for r in fp.reviews} | {x for v in fp.values for x in v.review_reasons}


def _derived(fp):
    return [calc.five_half_lives(v, fp.flags) for v in fp.values if v.measure_type == "half_life"]


# ---------------------------------------------------------------- M02-D1 --
@pytest.mark.parametrize("field,text,reason", [
    ("half_life", "The half-life is not 4 hours.", "negated_value"),
    ("half_life", "A half-life of 4 hours has not been established.", "undetermined_statement"),
    ("absorption", "Tmax was not 2 hours.", "negated_value"),
    ("half_life", "The half-life of 4 hours reported earlier could not be confirmed.", "undetermined_statement"),
])
def test_d1_negated_or_undetermined_value_is_not_a_measurement(field, text, reason):
    fp = parse_field(field, S + text, stored_max_length=1000 if field == "half_life" else None)
    assert fp.values == []
    assert reason in _reasons(fp)
    assert fp.status == "unparsed_needs_review"


def test_d1_hedged_value_is_kept_but_never_clean():
    # 'unknown' belongs to another clause; 'may be' hedges the value itself
    fp = _hl("The half-life is unknown but may be about 4 hours.")
    (v,) = fp.values
    assert "hedged_value" in v.review_reasons
    assert _derived(fp)[0]["status"] == "not_computed"


@pytest.mark.parametrize("text,kind,bound", [
    ("The half-life is not less than 10 hours.", "lower_bound", 10.0),
    ("The half-life is no more than 3 hours.", "upper_bound", 3.0),
    ("The half-life is no longer than 3 hours.", "upper_bound", 3.0),
])
def test_d1_bound_phrases_are_not_negations(text, kind, bound):
    (v,) = _hl(text).values
    assert v.hours.kind == kind and v.review_reasons == []
    assert (v.hours.lower if kind == "lower_bound" else v.hours.upper) == bound


def test_d1_negation_in_another_clause_does_not_reject_a_clear_value():
    (t,) = _ab("Absorption is not affected by food, and Tmax is 2 hours.").values
    assert t.hours.value == 2.0 and t.review_reasons == []


def test_d1_negated_condition_keeps_its_meaning_and_blocks_5x():
    fp = _hl("The half-life is 4 hours in patients without renal impairment.")
    (v,) = fp.values
    assert v.conditions["population"] == ["without renal impairment"]
    assert "negated_condition" in v.review_reasons
    (d,) = _derived(fp)
    assert d["status"] == "not_computed"
    # near: the positive condition is still a plain condition
    (w,) = _hl("The half-life is 9 hours in patients with renal impairment.").values
    assert w.conditions["population"] == ["patients with renal impairment"] and w.review_reasons == []


# ---------------------------------------------------------------- M02-D2 --
@pytest.mark.parametrize("text,reason", [
    ("These measurements were obtained in dogs. The elimination half-life is 4 hours.", "field_context_unattributed"),
    ("These data apply to the extended-release formulation. The half-life is 4 hours.", "field_context_unattributed"),
    ("The half-life is 4 hours. These values come from studies in rats.", "field_context_unattributed"),
    ("The half-life in dogs is 2 hours. The half-life is 4 hours.", "non_human_context_in_field"),
])
def test_d2_context_outside_the_value_sentence_is_not_dropped(text, reason):
    fp = _hl(text)
    unflagged = [v for v in fp.values if v.hours.value == 4.0 and not v.review_reasons]
    assert unflagged == []
    assert reason in _reasons(fp)
    assert all(d["status"] == "not_computed" for d in _derived(fp) if d["hours"] is None or True)


def test_d2_unknown_group_in_the_same_clause_is_carried():
    (v,) = _hl("In burn patients, the elimination half-life is 4 hours.").values
    assert v.conditions["population"] == ["burn patients"]


def test_d2_own_context_and_context_change_are_respected():
    # the value states its own species: the other sentence's species is not inherited
    fp = _hl("These data were obtained in dogs. In humans, the half-life is 4 hours.")
    (v,) = fp.values
    assert v.conditions["other"] == ["humans"] and v.review_reasons == []
    # different formulations stated with their own values stay separate and clean
    fp = _hl("The half-life of the tablet is 4 hours. The half-life of the extended-release capsule is 9 hours.")
    a, b = fp.values
    assert a.conditions["formulation"] == ["tablet"] and a.review_reasons == []
    assert "extended-release" in b.conditions["formulation"] and b.review_reasons == []
    # a value-less sentence without a condition does not flag anything
    (v,) = _hl("Elimination is mainly renal. The half-life is 4 hours.").values
    assert v.review_reasons == []
    # simple positives keep working
    (v,) = _hl("The elimination half-life is 4 hours.").values
    assert v.review_reasons == [] and calc.five_half_lives(v, [])["status"] == "computed"


def test_d2_paragraph_heading_context_is_flagged():
    fp = parse_field("half_life", S + "Dogs:\nThe half-life is 4 hours.", stored_max_length=1000)
    assert _clean(fp) == []


# ---------------------------------------------------------------- M02-D3 --
@pytest.mark.parametrize("text", [
    "Unlike Drug B, which has a half-life of 10 hours, the half-life of Drug A has not been established.",
    "Unlike Drug B, which has a half-life of 10 hours, Drug A is cleared within minutes.",
    "Similar to other agents of this class, the half-life is 6 hours.",
])
def test_d3_comparison_subject_value_is_not_the_record_drug(text):
    fp = _hl(text, names=["[SYNTHETIC] Drug A"])
    assert _clean(fp) == []
    assert _reasons(fp) & {"subject_unresolved_comparison", "undetermined_statement", "comparison_in_clause"}


def test_d3_named_other_subject_is_refused_record_name_is_kept():
    fp = _hl("The half-life of Drug B is 10 hours.", names=["[SYNTHETIC] Drug A"])
    assert fp.values == [] and "subject_not_record_drug" in _reasons(fp)
    (v,) = _hl("The half-life of Drug A is 10 hours.", names=["[SYNTHETIC] Drug A"]).values
    assert v.hours.value == 10.0 and v.review_reasons == []
    fp = _ab("Tmax is 2 hours for Drug B.", names=["[SYNTHETIC] Drug A"])
    assert fp.values == [] and "subject_not_record_drug" in _reasons(fp)


def test_d3_metabolite_and_coadministered_product_are_not_foreign_subjects():
    fp = _hl("The half-life of the active metabolite M1 is 20 hours.", names=["[SYNTHETIC] Drug A"])
    (v,) = fp.values
    assert v.conditions["analyte"] == "metabolite"
    fp = _hl("When co-administered with Drug C, the half-life is 6 hours.", names=["[SYNTHETIC] Drug A"])
    (v,) = fp.values
    assert v.conditions["other"] and v.hours.value == 6.0
    # conditions that look like names are not subjects
    (v,) = _ab("Tmax is 4 hours for ER tablets.", names=["[SYNTHETIC] Drug A"]).values
    assert v.review_reasons == []


# ---------------------------------------------------------------- M02-D4 --
@pytest.mark.parametrize("text", [
    "The half-life is 4 hours; the duration of effect is 9 hours.[A2]",
    "The half-life is 4 hours; adverse events are described elsewhere.[A2]",
])
def test_d4_token_closing_another_clause_is_not_attributed(text):
    (v,) = _hl(text).values
    assert v.reference_scope == "sentence_other_clause"
    assert v.reference_tokens == [] and v.nearby_reference_tokens == ["A2"]


def test_d4_shared_claims_in_one_clause_are_not_exclusive():
    # R2: was 'sentence_shared' with A2 still in the value's token list; another
    # claim follows the value, so A2 is now only 'nearby' and not attributed.
    (v,) = _hl("The half-life is 4 hours and adverse events are described elsewhere.[A2]").values
    assert v.reference_scope == "sentence_other_clause"
    assert v.reference_tokens == [] and v.nearby_reference_tokens == ["A2"]
    fp = _hl("The half-life is 4 hours (range 2-6 hours).[A2]")
    assert fp.values and all(v.reference_scope == "sentence_shared" for v in fp.values)


def test_d4_positive_and_value_window_tokens():
    fp = _hl("The half-life is 4 hours.[A1] The duration of effect is 9 hours.[A2]")
    (v,) = fp.values
    assert v.reference_tokens == ["A1"] and v.reference_scope == "sentence_single_value"
    assert "A2" not in v.nearby_reference_tokens
    (v,) = _hl("The elimination half-life is 4 hours following oral administration.[A1]").values
    assert v.reference_scope == "sentence_single_value"
    # a token written inside the value's own clause stays with it; the closing
    # token of the other ';' clause is only 'nearby'
    (v,) = _hl("The half-life is 5 h [A1] in adults; the duration of effect is 9 hours.[A2]").values
    assert v.reference_tokens == ["A1"] and v.reference_scope == "value_window"
    assert v.nearby_reference_tokens == ["A2"]


def test_d4_negation_subject_and_scope_together():
    fp = _hl("Unlike Drug B, the half-life is not 4 hours; Tmax is 2 hours.[A1]", names=["[SYNTHETIC] Drug A"])
    assert fp.values == []


# ---------------------------------------------------------------- M02-D5 --
def test_d5_plus_minus_is_carried_to_derived_without_interpretation():
    fp = _hl("The elimination half-life is 4 ± 1 hours.")
    (v,) = fp.values
    d = calc.five_half_lives(v, fp.flags)
    assert d["status"] == "computed" and d["hours"].value == 20.0
    assert d["dispersion"] == {"value_hours": 5.0, "source_value_hours": 1.0}
    # mixed units: the spread keeps its own unit conversion
    (v,) = _hl("The half-life was 1.5 h ± 20 min.").values
    d = calc.five_half_lives(v, [])
    assert d["dispersion"]["source_value_hours"] == pytest.approx(1 / 3, abs=1e-6)
    assert d["dispersion"]["value_hours"] == pytest.approx(5 / 3, abs=1e-5)
    # no spread -> no dispersion object
    (v,) = _hl("The elimination half-life is 4 hours.").values
    assert calc.five_half_lives(v, [])["dispersion"] is None


@pytest.mark.parametrize("text,reason", [
    ("The half-life is 4 ± " + "9" * 308 + " days.", "invalid_value"),
    ("The half-life is 4 hours ± 0.0000001 seconds.", "value_below_precision"),
])
def test_d5_non_finite_or_vanishing_spread_is_never_silent(text, reason):
    fp = _hl(text)
    assert fp.values == [] and reason in _reasons(fp)


def test_d5_derived_refuses_non_finite_spread_defensively():
    (v,) = _hl("The elimination half-life is 4 ± 1 hours.").values
    v.dispersion = (1.0, float("inf"), "hours")
    d = calc.five_half_lives(v, [])
    assert d["status"] == "not_computed" and d["not_computed_reasons"] == ["invalid_dispersion"]


# ---------------------------------------------------------------- M02-D6 --
SYNTH = "postgresql://synth@127.0.0.1:55432/medicallm_demo_synth"


@pytest.mark.parametrize("env,fragment", [
    ({}, "not set in this terminal"),
    ({"DO_POSTGRES_URL": ""}, "not set in this terminal"),
    ({"DO_POSTGRES_URL": "postgresql://app@127.0.0.1:5432/medicallm", "M02_DEMO_CONFIRM": "medicallm"},
     "does not end with '_synth'"),
    ({"DO_POSTGRES_URL": "postgresql://app@db.example.invalid:5432/x_synth", "M02_DEMO_CONFIRM": "x_synth"},
     "not a loopback"),
    ({"DO_POSTGRES_URL": SYNTH}, "M02_DEMO_CONFIRM"),
    ({"DO_POSTGRES_URL": SYNTH, "M02_DEMO_CONFIRM": "other_synth"}, "M02_DEMO_CONFIRM"),
    ({"DO_POSTGRES_URL": SYNTH + "?host=elsewhere", "M02_DEMO_CONFIRM": "medicallm_demo_synth"}, "query options"),
    ({"DO_POSTGRES_URL": "sqlite:///demo_synth", "M02_DEMO_CONFIRM": "demo_synth"}, "not postgresql"),
])
def test_d6_guard_refuses_missing_or_wrong_targets(env, fragment):
    ok, messages = demo_guard.check_target(env, connect=False)
    assert ok is False and any(fragment in m for m in messages), messages


def test_d6_guard_accepts_static_synthetic_target():
    ok, _ = demo_guard.check_target({"DO_POSTGRES_URL": SYNTH, "M02_DEMO_CONFIRM": "medicallm_demo_synth"},
                                    connect=False)
    assert ok is True


def test_d6_new_terminal_without_variable_stops_and_never_reads_dotenv(tmp_path):
    """A fresh process (like a new terminal) without DO_POSTGRES_URL, started in
    a folder whose .env points at an application database: the guard exits 2."""
    (tmp_path / ".env").write_text("DO_POSTGRES_URL=postgresql://app@127.0.0.1:5432/app_db_synth\n"
                                   "M02_DEMO_CONFIRM=app_db_synth\n", encoding="utf-8")
    backend = Path(__file__).resolve().parents[2]
    env = {k: v for k, v in os.environ.items()
           if k not in ("DO_POSTGRES_URL", "POSTGRES_URL", "M02_DEMO_CONFIRM")}
    env["PYTHONPATH"] = str(backend)
    proc = subprocess.run([sys.executable, "-m", "src.timing.demo_guard"], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "not set in this terminal" in proc.stdout
    assert "app_db" not in proc.stdout


def test_d6_readme_step_runs_the_guard_before_the_app():
    readme = (Path(__file__).resolve().parents[3] / "README.md").read_text(encoding="utf-8")
    section = readme.split("## M-02 zaman verisi API'si", 1)[1].split("\n## ", 1)[0]
    assert "$env:DO_POSTGRES_URL = $env:DEMO_URL" not in section
    guard = section.index("uv run python -m src.timing.demo_guard")
    start = section.index("uv run python run.py")
    assert guard < start
    assert "if ($LASTEXITCODE -eq 0) { uv run python run.py }" in section
