"""Typed contract of ``POST /api/timing/compare`` (M-02, first delivery).

Everything here is read-only data derived from text already stored in the
``drugs`` table. Nothing in this contract is a dose, a personal schedule, a
clinical interval or a statement that a drug "has left the body", that its
effect "is over" or that taking another drug "is safe".

Null / array rules (fixed, also visible in OpenAPI):
  * every ``List[...]`` field is always present and is ``[]`` when empty;
  * a number that is not known is ``null`` - never ``0``;
  * ``drug`` / ``data_status`` are ``null`` only for an unknown drug id.
"""
from __future__ import annotations

import re
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "m02-timing-compare/2"

# Technical limit of this delivery (not a clinical rule of Form A).
MIN_DRUGS = 2
MAX_DRUGS = 10
DRUGBANK_ID_RE = re.compile(r"DB[0-9]{5}")  # ASCII digits only (fullmatch)

MeasureType = Literal["tmax", "half_life"]
SourceField = Literal["half_life", "absorption"]
ValueKind = Literal["point", "range", "upper_bound", "lower_bound"]
TimeReference = Literal["after_administration", "not_stated", "not_applicable_duration"]
ReferenceStatus = Literal["matched", "partially_matched", "unmatched", "no_inline_reference"]
ReferenceScope = Literal["value_window", "sentence_single_value", "sentence_shared", "sentence_other_clause", "none"]
FieldStatus = Literal[
    "empty",                # NULL / whitespace only
    "placeholder",          # e.g. "Not Available"
    "parsed",               # >=1 measurement without a review flag
    "parsed_needs_review",  # measurements exist, every one is review-flagged
    "unparsed_needs_review",  # text present, nothing could be structured safely
    "no_statement_found",   # text present, no statement of this measure in it
]


class TimingCompareRequest(BaseModel):
    """2-10 distinct DrugBank ids (``DB`` + 5 digits). Order is preserved.

    No fuzzy matching, no case folding, no trimming, no truncation of the list.
    Any other field (patient id, dose, time...) is rejected with 422.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"drug_ids": ["DB00006", "DB00316"]}]},
    )

    drug_ids: List[str] = Field(..., min_length=MIN_DRUGS, max_length=MAX_DRUGS)

    @field_validator("drug_ids")
    @classmethod
    def _valid_distinct_ids(cls, ids: List[str]) -> List[str]:
        bad = [i for i in ids if not isinstance(i, str) or not DRUGBANK_ID_RE.fullmatch(i)]
        if bad:
            raise ValueError("each drug id must be a DrugBank id: 'DB' followed by 5 digits")
        if len(set(ids)) != len(ids):
            raise ValueError("drug ids must be distinct")
        return ids


class _Out(BaseModel):
    """Response models: fields that always appear are listed as required in OpenAPI."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class ReferenceLink(_Out):
    """A ``drug_references`` row of the SAME drug whose ``ref_id`` equals an
    inline token (e.g. ``[A123]``) found in the quoted sentence."""

    ref_id: str
    ref_type: str
    pubmed_id: Optional[str] = None
    isbn: Optional[str] = None
    citation: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None


class SourceExcerpt(_Out):
    """Where a value comes from. Field names follow the C1 evidence item
    (``source_ref``, ``source_field``, ``quote``, ``truncated``) so the two
    can be mapped later; C1 itself is not changed or required."""

    source_ref: str = Field(..., description="'drugbank:<drug_id>' - the stored drug record")
    source_record_url: str
    source_field: SourceField
    quote: str = Field(..., description="Exact sentence of the stored text the value is in")
    quote_start: int
    quote_end: int
    value_text: str = Field(..., description="Exact substring the number(s) were read from")
    value_start: int
    value_end: int
    truncated: bool = Field(False, description="The quote itself is never shortened (always false)")
    stored_text_possibly_truncated: bool
    inline_reference_tokens: List[str] = Field(
        ..., description="Tokens attributed to this value (see reference_scope); [] when none")
    nearby_reference_tokens: List[str] = Field(
        ..., description="Other tokens in the same sentence that are NOT attributed to this value")
    references: List[ReferenceLink]
    unmatched_reference_tokens: List[str]
    reference_status: ReferenceStatus
    reference_scope: ReferenceScope = Field(
        ..., description="value_window: token written inside this value's own clause; sentence_single_value: "
                         "token at the end of a sentence that states only this value; sentence_shared: token at "
                         "the end of a sentence that also states other values or claims (not exclusive to this "
                         "value); sentence_other_clause: token closes another ';' clause and is not attributed "
                         "(see nearby_reference_tokens); none: no token")
    stored_reference_attributed: bool = Field(
        ..., description="True only when every attributed token matched a stored drug_references row of this "
                         "drug AND the token belongs to this value alone (scope value_window or "
                         "sentence_single_value). This is a stored mapping, NOT a check that the external "
                         "source was opened or that it supports the value."
    )


class Quantity(_Out):
    """One duration. ``point`` uses ``value``; ``range`` uses ``lower``+``upper``;
    ``upper_bound`` uses ``upper``; ``lower_bound`` uses ``lower``. Unused
    members are ``null``. Ranges are never averaged."""

    kind: ValueKind
    value: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None
    inclusive: Optional[bool] = Field(None, description="Bounds only: '<=' vs '<'; null when not stated")


class OriginalQuantity(Quantity):
    unit: str = Field(..., description="Unit exactly as written, e.g. 'min', 'hours', 'days' "
                                       "(for a mixed-unit range: the unit of the upper value)")
    lower_unit: Optional[str] = Field(None, description="Mixed-unit range only: unit of the lower value")


class Dispersion(_Out):
    kind: Literal["plus_minus"]
    value_original: float
    unit: str = Field(..., description="Unit of the spread as written (may differ from the value unit)")
    value_hours: float


class Conditions(_Out):
    """Conditions stated in the text window of this value only. Empty list =
    not stated in that window. Nothing is added from product tables."""

    route: List[str] = []
    formulation: List[str] = []
    population: List[str] = []
    food_state: List[str] = []
    dosing: List[str] = []
    analyte: Literal["parent", "metabolite", "not_stated"] = "not_stated"
    analyte_terms: List[str] = []
    phase: List[str] = []
    matrix: List[str] = []
    kinetics: List[str] = []
    other: List[str] = Field([], description="Species / in vitro / co-administration terms")
    stereoisomer: List[str] = Field([], description="Enantiomer the value is stated for ('R-warfarin'); "
                                                   "R and S values are separate measurements")


class TimingMeasurement(_Out):
    measurement_id: str
    drug_id: str
    measure_type: MeasureType
    measure_basis: Literal["value_keyword", "sentence_keyword", "field_only"]
    source: SourceExcerpt
    original: OriginalQuantity
    hours: Quantity
    approximate: bool
    dispersion: Optional[Dispersion] = None
    conditions: Conditions
    time_reference: TimeReference
    review_required: bool
    review_reasons: List[str]
    conflict_group: Optional[str] = None
    parser_version: str


class DerivedDispersion(_Out):
    """The source '±' spread carried through the same x5 scaling. The kind of
    statistic (SD, SEM, range half-width, CI) is not stated in the source and
    is not inferred; the derived value is NOT turned into a min-max range."""

    kind: Literal["plus_minus"] = "plus_minus"
    statistic: Literal["not_stated"] = "not_stated"
    value_hours: float
    source_value_hours: float


class DerivedDuration(_Out):
    """About five half-lives, computed separately from (never merged into)
    the source measurement. Tmax is never added."""

    derived_id: str
    kind: Literal["approx_five_half_lives"] = "approx_five_half_lives"
    based_on_measurement_id: str
    status: Literal["computed", "not_computed"]
    multiplier: int = 5
    hours: Optional[Quantity] = None
    dispersion: Optional[DerivedDispersion] = Field(
        None, description="Only when the source value has a '±' spread; null otherwise")
    not_computed_reasons: List[str]
    includes_tmax: bool = False
    assumptions: List[str]
    interpretation: str


class ReviewItem(_Out):
    """Text kept for human review instead of being turned into a value."""

    source_field: SourceField
    quote: str
    quote_start: int
    quote_end: int
    value_text: Optional[str] = None
    reason: str


class FieldReport(_Out):
    source_field: SourceField
    field_status: FieldStatus
    stored_text: Optional[str] = Field(None, description="Stored text as read, unmodified")
    stored_text_length: int
    stored_text_possibly_truncated: bool
    measurement_ids: List[str]
    review_items: List[ReviewItem]
    field_flags: List[str]


class DrugIdentity(_Out):
    drug_id: str
    name: str
    source_record_url: str


class DataStatus(_Out):
    tmax: FieldStatus
    half_life: FieldStatus


class DrugTimingResult(_Out):
    position: int
    requested_id: str
    lookup_status: Literal["found", "not_found"]
    drug: Optional[DrugIdentity] = None
    data_status: Optional[DataStatus] = None
    fields: List[FieldReport]
    measurements: List[TimingMeasurement]
    derived: List[DerivedDuration]
    limitations: List[str]


class TimingAdvice(_Out):
    status: Literal["not_evaluated"] = "not_evaluated"
    advice: List[dict] = []
    note: str = (
        "This compare request does not evaluate timing-interval evidence; use /api/timing/advice "
        "with explicit product contexts. This is not a statement that no source exists or that there is no interaction."
    )


class Limitation(_Out):
    code: str
    message: str


class TimingCompareResponse(_Out):
    schema_version: str = SCHEMA_VERSION
    parser_version: str
    drugs: List[DrugTimingResult]
    timing_advice: TimingAdvice
    limitations: List[Limitation]
