"""Expectations fixed before the implementation. All texts are synthetic."""
import pytest
from src.timing.parser import parse_field

NEGATIVE = [
    "drug b, a synthetic agent, has a half-life of 10 hours.",
    "drug b, given orally, has a half-life of 10 hours.",
    "The tablet (drug b) has a half-life of 10 hours.",
    "For the tablet (drug b), the half-life is 10 hours.",
    "The tablet, which contains drug b, has a half-life of 10 hours.",
    "The formulation of drug b was studied and it has a half-life of 10 hours.",
    "The formulation of drug b was studied. Its half-life is 10 hours.",
    "Regarding drug b, the half-life is 10 hours.",
    "As for drug b, the half-life is 10 hours.",
    "drug b: the half-life is 10 hours.",
    "drug b half-life is 10 hours.",
    "Regarding drug b, Tmax is 2 hours.",
    "drug b, a synthetic agent, has a Tmax of 2 hours.",
]
POSITIVE = [
    "Drug A, a synthetic agent, has a half-life of 4 hours.",
    "Drug A, given orally, has a half-life of 4 hours.",
    "The drug, which is cleared by the kidney, has a half-life of 4 hours.",
    "The tablet (oral) has a half-life of 4 hours.",
    "In healthy adults (n=12), the half-life is 4 hours.",
    "The half-life is 4 hours.",
    "For 20% drug a, the half-life is 4 hours.",
    "Drug A has a half-life of 4 hours.",
]
# Decision boundaries: same syntax with a different name, a condition instead
# of a name, a cleared antecedent, and an unresolved antecedent.
BOUNDARIES = [
    ("Regarding Drug A, Tmax is 2 hours.", True),
    ("The tablet (Drug A) has a half-life of 4 hours.", True),
    ("The tablet, which contains Drug A, has a half-life of 4 hours.", True),
    ("The formulation of Drug A was studied. Its half-life is 4 hours.", True),
    ("The formulation of drug b was studied. Drug A has a half-life of 4 hours.", True),
    ("Concerning zoralen, the half-life is 10 hours.", False),
    ("zoralen: Tmax is 2 hours.", False),
    ("The capsule (zoralen) has a half-life of 10 hours.", False),
    ("The formulation of zoralen was studied. Its half-life is 10 hours.", False),
    ("The tablet (n=12) has a half-life of 4 hours.", True),
]

@pytest.mark.parametrize("text", NEGATIVE)
def test_no_foreign_measurement(text):
    result = parse_field("absorption" if "Tmax" in text else "half_life", text,
                         subject_names=["[SYNTHETIC] Drug A"])
    assert not result.values
    assert any(x.reason == "subject_unresolved" for x in result.reviews)

@pytest.mark.parametrize("text", POSITIVE)
def test_supported_ownership_stays_clean(text):
    result = parse_field("half_life", text, subject_names=["[SYNTHETIC] Drug A"])
    assert len(result.values) == 1
    assert result.values[0].hours.value == 4
    assert result.values[0].review_reasons == []

@pytest.mark.parametrize("text,clean", BOUNDARIES)
def test_ownership_boundary(text, clean):
    result = parse_field("absorption" if "Tmax" in text else "half_life", text,
                         subject_names=["[SYNTHETIC] Drug A"])
    assert bool(result.values) is clean
    if clean:
        assert not result.values[0].review_reasons
