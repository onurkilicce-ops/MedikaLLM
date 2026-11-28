"""M-02 parser against the PRE-REGISTERED synthetic case tables.

``tests/fixtures/m02_cases_half_life.json`` and ``m02_cases_tmax.json`` were
written by two independent authors from ``src/timing/RULES.md`` and the typed
contract only, before the parser was run against them (see STATUS.md, M-02).
Every text is synthetic ("[SYNTHETIC] ..."), not DrugBank content.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.timing import calc
from src.timing.parser import parse_field

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_FILES = ["m02_cases_half_life.json", "m02_cases_tmax.json"]
HALF_LIFE_STORED_MAX = 1000


def _cases():
    out = []
    for name in _FILES:
        data = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
        for case in data["cases"]:
            out.append(pytest.param(case, id=f"{name.split('_')[2].split('.')[0]}:{case['id']}"))
    return out


def _hours_match(actual, expected):
    for key in ("kind", "value", "lower", "upper"):
        if key not in expected:
            continue
        exp = expected[key]
        act = getattr(actual, key)
        if exp is None or act is None:
            assert act == exp, f"hours.{key}: {act!r} != {exp!r}"
        else:
            assert act == pytest.approx(exp, abs=1e-6), f"hours.{key}: {act!r} != {exp!r}"


@pytest.mark.parametrize("case", _cases())
def test_preregistered_case(case):
    exp = case["expect"]
    max_len = HALF_LIFE_STORED_MAX if case["field"] == "half_life" else None
    fp = parse_field(case["field"], case["text"], stored_max_length=max_len)
    refs = set(case.get("drug_reference_ids", []))

    assert fp.status == exp["field_status"]
    assert len(fp.values) == exp["measurement_count"], [
        (v.measure_type, case["text"][v.value_span.start:v.value_span.end]) for v in fp.values]

    for actual, want in zip(fp.values, exp.get("measurements", [])):
        if "measure_type" in want:
            assert actual.measure_type == want["measure_type"]
        if "unit" in want:
            assert actual.unit == want["unit"] or (
                actual.lower_unit and f"{actual.lower_unit}" in want["unit"] and actual.unit in want["unit"])
        if "hours" in want:
            _hours_match(actual.hours, want["hours"])
        if "approximate" in want:
            assert actual.approximate is want["approximate"]
        if "review_required" in want:
            assert bool(actual.review_reasons) is want["review_required"], actual.review_reasons
        for key, terms in want.get("conditions_include", {}).items():
            have = actual.conditions[key]
            for term in terms:
                assert any(term in h for h in have), f"{key}: {term!r} not in {have!r}"
        for key, terms in want.get("conditions_exclude", {}).items():
            have = actual.conditions[key]
            for term in terms:
                assert not any(term in h for h in have), f"{key}: {term!r} unexpectedly in {have!r}"
        if "analyte" in want:
            assert actual.conditions["analyte"] == want["analyte"]
        if "time_reference" in want:
            assert actual.time_reference == want["time_reference"]
        if "reference_status" in want or "matched_ref_ids" in want:
            status, matched, _ = calc.reference_status(actual.reference_tokens, refs)
            if "reference_status" in want:
                assert status == want["reference_status"]
            if "matched_ref_ids" in want:
                assert matched == want["matched_ref_ids"]

    reasons = {r.reason for r in fp.reviews} | {x for v in fp.values for x in v.review_reasons}
    for code in exp.get("review_reasons_include", []):
        assert code in reasons, f"{code!r} not in {sorted(reasons)}"

    for forbidden in exp.get("forbidden_hours", []):
        for v in fp.values:
            for member in (v.hours.value, v.hours.lower, v.hours.upper):
                assert member is None or member != pytest.approx(forbidden), (forbidden, v.hours)

    if "derived" in exp:
        halves = [v for v in fp.values if v.measure_type == "half_life"]
        assert len(halves) == len(exp["derived"])
        for v, want in zip(halves, exp["derived"]):
            d = calc.five_half_lives(v, fp.flags)
            assert d["status"] == want["status"], d["not_computed_reasons"]
            if want.get("hours") is None:
                assert d["hours"] is None
            else:
                _hours_match(d["hours"], want["hours"])
            for code in want.get("reasons_include", []):
                assert code in d["not_computed_reasons"], d["not_computed_reasons"]
