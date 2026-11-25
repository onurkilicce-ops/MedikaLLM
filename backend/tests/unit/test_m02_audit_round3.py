"""Independent review of the M02-O1-D1 fixes (round 3; 19 findings, all
reproduced by a separate verifier). Two directions are checked:

* over-rejection: clear, common sentences must stay CLEAN values;
* bypass: near variants of the audit sentences must NOT become clean values.

All texts are SYNTHETIC; 'Zorvatinib' / 'Drug A' are invented record names.
"""
from __future__ import annotations

import pytest

from src.timing import calc, demo_guard
from src.timing.parser import parse_field

S = "[SYNTHETIC] "
NAMES = ["[SYNTHETIC] Zorvatinib"]


def _p(field, text, names=NAMES):
    return parse_field(field, S + text, stored_max_length=1000 if field == "half_life" else None,
                       subject_names=names)


def _clean(fp):
    return [v for v in fp.values if not v.review_reasons]


def _derived(fp):
    return [calc.five_half_lives(v, fp.flags) for v in fp.values if v.measure_type == "half_life"]


# ------------------------------------------------------- over-rejection --
@pytest.mark.parametrize("field,text,value", [
    ("half_life", "The elimination half-life is 4 hours. Coadministration with ketoconazole increased "
                  "exposure twofold.", 4.0),
    ("absorption", "Zorvatinib has a Tmax of 2 hours. Coadministration with food does not alter Tmax.", 2.0),
    ("half_life", "No dose adjustment is required as the half-life is 4 hours in elderly patients.", 4.0),
    ("half_life", "Dose adjustment is not required since the elimination half-life is 6 hours.", 6.0),
    ("half_life", "Zorvatinib does not accumulate because its half-life is only 2 hours.", 2.0),
    ("absorption", "Peak plasma concentrations occur within 2 hours, although absolute bioavailability is unknown.",
     2.0),
    ("half_life", "The half-life is 5 hours, and the relevance of this in elderly patients is unclear.", 5.0),
    ("half_life", "The mean half-life for Japanese subjects was 5 hours.", 5.0),
    ("absorption", "Tmax for Japanese subjects was 2 hours.", 2.0),
    ("half_life", "The half-life is about 3 hours. Safety and efficacy in pediatric patients have not been "
                  "established.", 3.0),
    ("half_life", "The half-life is 4 hours. No dose adjustment is needed in the elderly.", 4.0),
    ("half_life", "The half-life is 5 hours. The pharmacokinetics in hepatic impairment are unknown.", 5.0),
    ("half_life", "Zorvatinib is available as an extended-release tablet. The half-life is 9 hours.", 9.0),
    ("absorption", "Zorvatinib is supplied as a film-coated tablet. Tmax is 2 hours.", 2.0),
    ("absorption", "Absolute bioavailability is 90% in healthy volunteers. Tmax is 1 hour.", 1.0),
    ("absorption", "In vitro studies indicate that Zorvatinib is a P-gp substrate. Peak plasma concentrations "
                   "are reached in 2 hours.", 2.0),
    ("half_life", "Zorvatinib has a half-life of 4 hours, which is shorter than that of other drugs in its class.",
     4.0),
    ("half_life", "The half-life does not exceed 4 hours.", 4.0),
    ("half_life", "The half-life is 4 hours. It is available as tablets.", 4.0),
    ("absorption", "Bioavailability is 90% in humans. Tmax is 2 hours.", 2.0),
])
def test_clear_sentences_stay_clean(field, text, value):
    fp = _p(field, text)
    clean = _clean(fp)
    assert clean, [(v.hours, v.review_reasons) for v in fp.values] + [r.reason for r in fp.reviews]
    h = clean[0].hours
    assert value in (h.value, h.lower, h.upper)


@pytest.mark.parametrize("text,kind,bound", [
    ("The half-life does not exceed 4 hours.", "upper_bound", 4.0),
    ("The half-life is not above 4 hours.", "upper_bound", 4.0),
    ("The half-life is not under 4 hours.", "lower_bound", 4.0),
])
def test_negated_bounds_are_bounds(text, kind, bound):
    (v,) = _p("half_life", text).values
    assert v.hours.kind == kind and v.hours.inclusive is True


def test_negated_condition_forms_keep_the_value():
    for text in ("The half-life of Zorvatinib in patients with no hepatic impairment is 4 hours.",
                 "In patients not receiving hemodialysis the half-life is 4 hours."):
        (v,) = _p("half_life", text).values
        assert "negated_condition" in v.review_reasons
    a = _p("half_life", "The half-life is 4 hours in nonsmokers.").values[0]
    b = _p("half_life", "The half-life is 4 hours in non-smokers.").values[0]
    assert a.conditions["population"] == ["nonsmokers"] and b.conditions["population"] == ["non-smokers"]
    assert a.review_reasons == b.review_reasons == []


def test_metabolite_code_and_brand_are_not_silently_clean_or_dropped():
    (v,) = _p("half_life", "The half-life of M1 is 6 hours.").values
    assert "subject_code_unresolved" in v.review_reasons


# ---------------------------------------------------------------- bypass --
@pytest.mark.parametrize("field,text", [
    ("half_life", "Drug B has a half-life of 10 hours; the half-life of Zorvatinib is unknown."),
    ("half_life", "Drug B has a half-life of 10 hours."),
    ("half_life", "Drug B's half-life is 10 hours."),
    ("half_life", "For Drug B, the half-life is 10 hours."),
    ("half_life", "Drug B: half-life 10 hours."),
    ("half_life", "Half-life (Drug B): 10 hours."),
    ("half_life", "The half-life of Zorvatinib-N-oxide is 10 hours."),
    ("half_life", "The half-life isn't 4 hours."),
    ("half_life", "A half-life of 4 hours hasn't been established."),
    ("absorption", "Tmax wasn't 2 hours."),
    ("half_life", "A half-life of 4 hours was not observed."),
    ("half_life", "A half-life of 4 hours has not been demonstrated."),
    ("half_life", "A half-life of 4 hours has yet to be established."),
    ("half_life", "A half-life of 4 hours is not well-established."),
    ("half_life", "A half-life of 4 hours has not yet been reliably established."),
    ("half_life", "The half-life may be 4 hours, but this is unproven."),
    ("half_life", "The half-life was reported as 4 hours, which was later refuted."),
    ("half_life", "The half-life is 4 hours; however, this has not been established."),
    ("half_life", "The half-life is reported to be 4 hours. This has not been established."),
    ("half_life", "The half-life is 4 hours in patients lacking renal impairment."),
    ("half_life", "The half-life is 4 hours in patients free from renal impairment."),
    ("half_life", "These measurements were obtained in beagles. The elimination half-life is 4 hours."),
    ("half_life", "These data come from murine studies. The elimination half-life is 4 hours."),
    ("half_life", "Studies were done in isolated hepatocytes. The elimination half-life is 4 hours."),
    ("half_life", "The study enrolled only cancer patients. The half-life is 4 hours."),
    ("half_life", "These data apply to the long-acting formulation. The half-life is 4 hours."),
    ("half_life", "The half-life is 4 ± 1 to 6 hours."),
    ("half_life", "The half-life is 4 to 6 ± 1 hours."),
    ("half_life", "The half-life is 4 plus or minus 1 hours."),
    ("half_life", "The half-life is 4 + / - 1 hours."),
    ("half_life", "The half-life is 4 hours (± 1)."),
    ("half_life", "The half-life is 4 hours, with a standard deviation of 1 hour."),
    ("half_life", "The half-life is 4 hours (95% CI 3 to 5 hours)."),
])
def test_bypass_variants_never_give_a_clean_value_or_5x(field, text):
    fp = _p(field, text)
    assert _clean(fp) == [], [(v.hours, v.review_reasons) for v in fp.values]
    assert all(d["status"] == "not_computed" for d in _derived(fp))


@pytest.mark.parametrize("text,term", [
    ("The elimination half-life in canines is 4 hours.", "canines"),
    ("The elimination half-life is 4 hours (canine data).", "canine"),
])
def test_own_species_is_carried_and_blocks_5x(text, term):
    fp = _p("half_life", text)
    (v,) = fp.values
    assert term in v.conditions["other"]
    (d,) = _derived(fp)
    assert d["status"] == "not_computed" and "non_human_or_in_vitro" in d["not_computed_reasons"]


def test_brand_or_other_capitalised_subject_is_not_credited_silently():
    # a brand name cannot be told from another drug without name data: kept for review
    fp = _p("absorption", "The Tmax for Zorvix tablets is 1 hour.")
    assert _clean(fp) == []


def test_guard_refuses_libpq_redirects():
    base = {"DO_POSTGRES_URL": "postgresql://u@127.0.0.1:5432/a_synth", "M02_DEMO_CONFIRM": "a_synth"}
    for extra in ({"PGHOSTADDR": "192.0.2.10"}, {"PGSERVICE": "prod"}):
        ok, msgs = demo_guard.check_target({**base, **extra}, connect=False)
        assert ok is False and any(list(extra)[0] in m for m in msgs)


def test_guard_refuses_redirect_keys_in_dotenv(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("PGHOSTADDR=192.0.2.10\n", encoding="utf-8")
    monkeypatch.setattr(demo_guard, "_dotenv_paths", lambda: [env_file])
    ok, msgs = demo_guard.check_target({"DO_POSTGRES_URL": "postgresql://u@127.0.0.1:5432/a_synth",
                                        "M02_DEMO_CONFIRM": "a_synth"}, connect=False)
    assert ok is False and any("PGHOSTADDR" in m and ".env" in m for m in msgs)
    assert "192.0.2.10" not in " ".join(msgs)
