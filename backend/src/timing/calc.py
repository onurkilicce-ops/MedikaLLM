"""Derived values and reference linking for M-02 (pure functions).

``five_half_lives`` never modifies the source measurement; it returns a new,
separate object that points back to it. Tmax is never part of it.
"""
from __future__ import annotations

import math
from typing import Iterable, List, Optional, Tuple

from .parser import (
    ELIMINATION_PHASES,
    HALF_LIFE,
    NON_ELIMINATION_PHASES,
    NON_HUMAN_TERM,
    NON_PLASMA_MATRIX,
    PHYSICAL_DECAY_OTHER,
    ParsedQuantity,
    ParsedValue,
)

MULTIPLIER = 5
_PHASE_NAMES = (
    ("terminal", ("terminal",)), ("elimination", ("elimination",)), ("distribution", ("distribution",)),
    ("absorption", ("absorption",)), ("initial", ("initial",)), ("alpha", ("alpha", "α")),
    ("beta", ("beta", "β")), ("gamma", ("gamma", "γ")), ("multiphasic", ("phasic",)),
)

ASSUMPTIONS = [
    "single_constant_half_life",
    "first_order_exponential_decline",
    "approximate_duration_not_complete_elimination",
    "tmax_not_added",
]
INTERPRETATION = (
    "About 5 x the stated half-life. Only under a single, constant half-life "
    "(first-order decline) about 3% of the amount present at the start would "
    "remain after this time. It is an approximate duration derived from the "
    "source value, not a time point after a dose. It must not be read as "
    "complete elimination, as the end of the drug's effect or as clearance to "
    "give another drug, and it is not a personal drug level, dose or clinical "
    "interval."
)


def reference_status(tokens: Iterable[str], ref_ids: Iterable[str]) -> Tuple[str, List[str], List[str]]:
    """Exact-match inline tokens against the SAME drug's reference ids."""
    tokens = list(tokens)
    known = set(ref_ids)
    matched = [t for t in tokens if t in known]
    unmatched = [t for t in tokens if t not in known]
    if not tokens:
        return "no_inline_reference", [], []
    if not unmatched:
        return "matched", matched, []
    if matched:
        return "partially_matched", matched, unmatched
    return "unmatched", [], unmatched


def _times(q: ParsedQuantity) -> ParsedQuantity:
    def m(x: Optional[float]) -> Optional[float]:
        return None if x is None else round(x * MULTIPLIER, 6)

    return ParsedQuantity(kind=q.kind, value=m(q.value), lower=m(q.lower), upper=m(q.upper),
                          inclusive=q.inclusive)


def not_computed_reasons(v: ParsedValue, field_flags: Iterable[str]) -> List[str]:
    flags = set(field_flags)
    reasons: List[str] = []
    if v.measure_type != HALF_LIFE:
        return ["not_a_half_life"]
    if v.review_reasons:
        reasons.append("measurement_requires_review")
        reasons.extend(r for r in v.review_reasons if r not in reasons)
    c = v.conditions
    if c.get("analyte") == "metabolite":
        reasons.append("metabolite_not_parent")
    elif c.get("analyte") == "not_stated" and "metabolite_mentioned" in flags:
        reasons.append("analyte_ambiguous_metabolite_mentioned")
    named = set()
    for term in c.get("phase", []):
        t = term.lower()
        for name, words in _PHASE_NAMES:
            if any(w in t for w in words):
                named.add(name)
    if named & NON_ELIMINATION_PHASES:
        reasons.append("non_elimination_phase")
    elif named - ELIMINATION_PHASES:
        # beta/gamma/biphasic/... : which phase the value belongs to is not unambiguous
        reasons.append("phase_ambiguous_multiphasic")
    elif not named and "multiphasic_description" in flags:
        reasons.append("phase_ambiguous_multiphasic")
    if "nonlinear_or_dose_dependent_kinetics_mentioned" in flags or c.get("kinetics"):
        reasons.append("nonlinear_or_dose_dependent_kinetics")
    if any(any(word in m for word in NON_PLASMA_MATRIX) for m in c.get("matrix", [])):
        reasons.append("non_plasma_matrix")
    if any(NON_HUMAN_TERM.search(o) for o in c.get("other", [])):  # word match, not substring
        reasons.append("non_human_or_in_vitro")
    if any(any(word in o for word in PHYSICAL_DECAY_OTHER) for o in c.get("other", [])):
        reasons.append("physical_decay_not_elimination")
    members = [x for x in (v.hours.value, v.hours.lower, v.hours.upper) if x is not None]
    if not members or any((not math.isfinite(x)) or x <= 0 for x in members):
        reasons.append("invalid_value")  # defensive: the parser never emits these
    out: List[str] = []
    for r in reasons:
        if r not in out:
            out.append(r)
    return out


def five_half_lives(v: ParsedValue, field_flags: Iterable[str]) -> dict:
    reasons = not_computed_reasons(v, field_flags)
    if reasons:
        return {"status": "not_computed", "hours": None, "not_computed_reasons": reasons}
    out = _times(v.hours)
    if any(x is not None and not math.isfinite(x) for x in (out.value, out.lower, out.upper)):
        return {"status": "not_computed", "hours": None, "not_computed_reasons": ["invalid_value"]}
    spread = None
    if v.dispersion is not None:
        # The '±' spread scales with the value (x5) whatever statistic it is;
        # the statistic itself is not stated and not inferred.
        source_h = v.dispersion[1]
        scaled = source_h * MULTIPLIER
        if not (math.isfinite(source_h) and math.isfinite(scaled)) or source_h < 0:
            return {"status": "not_computed", "hours": None, "not_computed_reasons": ["invalid_dispersion"]}
        spread = {"value_hours": round(scaled, 6), "source_value_hours": source_h}
    return {"status": "computed", "hours": out, "not_computed_reasons": [], "dispersion": spread}
