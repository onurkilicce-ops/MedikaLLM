"""Typed contract of ``POST /api/mechanism/compare`` (M-03, first delivery).

Read-only data derived from what DrugBank stores for each drug: the enzyme,
transporter and carrier lists (with the actions DrugBank records) and the
free-text elimination / metabolism / clearance fields. Nothing here is a
dose, a severity grade or a statement that a combination is safe.

Null / array rules: every list is always present ([] when empty); ``drug``
is ``null`` only for an unknown id.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..timing.models import DRUGBANK_ID_RE

SCHEMA_VERSION = "m03-mechanism/1"
RULES_VERSION = "m03-mechanism-rules/1"
MAX_DRUGS = 10

ProteinKind = Literal["enzyme", "transporter", "carrier"]
Role = Literal["substrate", "inhibitor", "inducer", "other"]
Organ = Literal["kidney", "liver", "bile_feces", "lungs"]
SourceField = Literal["route_of_elimination", "metabolism", "clearance"]
OrganNote = Literal["negated_or_minor", "uncertain_statement", "condition_context", "condition_also_mentioned",
                    "metabolite_mentioned", "metabolite_route", "other_subject_possible", "other_drug_named",
                    "animal_study"]
Mechanism = Literal["inhibition", "induction", "shared_substrate"]
Effect = Literal[
    "victim_exposure_may_increase",      # enzyme inhibited -> victim builds up
    "victim_exposure_may_decrease",      # enzyme induced -> victim cleared faster
    "victim_transport_may_decrease",     # transporter inhibited; direction of exposure depends on it
    "victim_transport_may_increase",     # transporter induced
    "carrier_binding_may_change",        # plasma/binding protein; direction of the free level not established
    "competition_possible_not_established",
]
PairStatus = Literal["explained_by_shared_protein", "shared_substrate_only", "shared_protein_no_direction",
                     "no_shared_protein_in_record", "drug_not_found"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MechanismRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drug_ids: List[str] = Field(min_length=1, max_length=MAX_DRUGS)

    @field_validator("drug_ids")
    @classmethod
    def _ids(cls, v):
        if any(not isinstance(x, str) or not DRUGBANK_ID_RE.fullmatch(x) for x in v):
            raise ValueError("every id must be 'DB' followed by 5 ASCII digits")
        if len(set(v)) != len(v):
            raise ValueError("drug ids must be distinct")
        return v


class ProteinEntry(_Out):
    kind: ProteinKind
    protein_id: str
    name: str
    organism: str
    human: bool
    roles: List[Role]
    raw_actions: str
    known_action: str            # DrugBank 'yes' | 'no' | 'unknown' | '' (as stored)
    inhibition_strength: str     # enzymes only, as stored ('' when absent)
    induction_strength: str


class OrganMention(_Out):
    organ: Organ
    source_field: SourceField
    quote: str
    quote_start: int
    quote_end: int
    notes: List[OrganNote]
    quote_truncated: bool
    quote_cut_before: bool       # the window starts after the sentence start
    quote_cut_after: bool        # the window ends before the sentence end
    other_drugs: List[str]       # other DrugBank drugs named in the sentence, as written there


class DrugText(_Out):
    source_field: SourceField
    stored_text: str
    truncated: bool


class DrugInfo(_Out):
    drug_id: str
    name: str


class DrugMechanism(_Out):
    requested_id: str
    lookup_status: Literal["found", "not_found"]
    drug: Optional[DrugInfo]
    proteins: List[ProteinEntry]
    organs: List[OrganMention]
    organs_truncated: bool
    proteins_truncated: bool     # display list capped; pair explanations use every entry
    texts: List[DrugText]


class RoleEvidence(_Out):
    drug_id: str
    roles: List[Role]
    raw_actions: str
    known_action: str
    strength: str


class Explanation(_Out):
    protein_kind: ProteinKind
    protein_id: str
    protein_name: str
    mechanism: Mechanism
    perpetrator_id: Optional[str]   # null for shared_substrate
    victim_id: Optional[str]
    effect: Effect
    evidence: List[RoleEvidence]
    caveats: List[str]
    directional: bool              # false: carrier binding or an inhibitor+inducer conflict; no net direction


class RecordedInteraction(_Out):
    from_drug_id: str
    to_drug_id: str
    description: str


class PairMechanism(_Out):
    drug_ids: List[str]
    status: PairStatus
    explanations: List[Explanation]
    shared_proteins_without_direction: List[str]
    recorded_interactions: List[RecordedInteraction]


class MechanismResponse(_Out):
    schema_version: str = SCHEMA_VERSION
    rules_version: str = RULES_VERSION
    drugs: List[DrugMechanism]
    pairs: List[PairMechanism]
    notice: str = ("Derived from DrugBank protein lists and stored text only. A missing shared protein does not "
                   "mean there is no interaction; an explanation is not a severity grade or a dosing advice.")
