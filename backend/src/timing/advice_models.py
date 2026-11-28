"""Explicit product-context evidence; independent of PK-derived durations."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .models import TimingCompareRequest, _Out, Quantity


class ProductContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drug_id: str
    profile_id: str = Field(min_length=1, max_length=80)


Food = Literal["breakfast", "dairy_alone", "calcium_drink_alone", "dairy_in_meal"]


class AdviceRequest(TimingCompareRequest):
    contexts: list[ProductContext] = Field(default_factory=list, max_length=10)
    foods: list[Food] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def context_ids(self):
        ids = [x.drug_id for x in self.contexts]
        if len(set(ids)) != len(ids) or not set(ids) <= set(self.drug_ids):
            raise ValueError("context ids must be distinct and included in drug_ids")
        if len(set(self.foods)) != len(self.foods):
            raise ValueError("foods must be distinct")
        return self


class ProductProfile(_Out):
    profile_id: str
    label: str
    route: str
    formulation: str
    jurisdiction: str


class SearchItem(_Out):
    drug_id: str
    name: str
    profiles: list[ProductProfile]


class SearchResponse(_Out):
    items: list[SearchItem]
    limited: bool


class EvidenceSource(_Out):
    source_ref: str
    url: str
    title: str
    section: str
    excerpt: str
    label_updated: str
    checked_on: str = "2026-11-26"
    verification: str = "official_label_opened; expert_acceptance_pending"


class EvidenceAdvice(_Out):
    rule_id: str
    subject_drug_id: str
    other_kind: Literal["drug", "food"]
    other_id: str
    other_name: str
    direction: Literal["before", "after"]
    interval_hours: Quantity
    conditions: list[str]
    source: EvidenceSource


class AdviceCoverage(_Out):
    item_ids: list[str]
    status: Literal["matched", "conditions_required", "not_in_catalog", "not_applicable", "drug_not_found"]
    reason: str


class AdviceResponse(_Out):
    schema_version: str = "m02-timing-advice/1"
    catalog_version: str = "2026-11-26.1"
    status: Literal["evaluated", "partially_evaluated", "not_evaluated"]
    advice: list[EvidenceAdvice]
    coverage: list[AdviceCoverage]
    note: str = (
        "Only this small, versioned label catalog was checked, not all clinical literature. "
        "No matching recommendation does not mean no interaction or safe use. "
        "Spacing does not resolve every interaction; professional review is required. "
        "UK/US product contexts are not automatically equivalent to products used in Türkiye."
    )
