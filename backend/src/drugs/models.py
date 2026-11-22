from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Literal

# ---------------------------------------------------------------------------
# Lookup result status — shared by the drug service, the agent tools, the REST
# API and the UI. The distinction is clinically relevant: "no_record" is a
# successful query whose answer is that the database holds no record (NOT
# evidence of safety), while "unresolved" and "error" mean the question was
# not (fully) answered.
#
#   found       query succeeded, every input resolved, >= 1 documented record
#   no_record   query succeeded, every input resolved, no documented record
#   incomplete  query succeeded only for the resolved inputs; the inputs listed
#               as unresolved were NOT checked (records may still be present)
#   unresolved  too few inputs could be resolved to run any check
#   error       the lookup failed; the result is unknown
# ---------------------------------------------------------------------------
LookupStatus = Literal["found", "no_record", "incomplete", "unresolved", "error"]

# Severity of an interaction is only reported when it comes from a source
# label or an expert review. Neither exists yet: DrugBank's interaction table
# has no severity field and no reviewer has labelled the records. The former
# text-pattern score (calculate_severity) is NOT a clinical label and is no
# longer exposed.
SEVERITY_NOT_RATED = "not_rated"

ALTERNATIVES_NOTE = (
    "Unverified candidates: drugs that share a DrugBank category with the "
    "drug being replaced and have no DrugBank interaction record with the "
    "checked medications. They are NOT checked for therapeutic equivalence, "
    "indication, contraindications, allergies, conditions or dosing and are "
    "not proven safe; a clinician must review them."
)


class LookupErrorInfo(BaseModel):
    """Safe, user-facing error summary (never contains exception text)."""
    code: str
    message: str


class ResolvedDrugRef(BaseModel):
    drug_id: str
    name: str


class MedicationMatch(BaseModel):
    """How a free-text medication name was matched to a database drug."""
    input: str
    drug_id: str
    name: str
    similarity: float | None = None
    # "name" | "brand" | "synonym" (exact) | "mixture" (combination product,
    # only one ingredient used) | "approximate" | "semantic"
    match_type: str | None = None


class DrugDescription(BaseModel):
    drug_id: str
    name: str
    description: str = ""

class DrugBase(DrugDescription):
    drug_type: str = ""  # eg "biotech" | "small molecule"
    indication: str = "" # eg "non-small cell lung cancer", "hypertension", "depression"
    mechanism_of_action: str = "" # eg "kinase inhibitor"
    pharmacodynamics: str = "" # eg "inhibits EGFR phosphorylation"
    synonyms: List[str] = [] # eg for "Tylenol": ["Acetaminophen", "Paracetamol"]

class Drug(DrugBase):
    toxicity: str = ""
    metabolism: str = ""
    absorption: str = ""
    half_life: str = ""
    protein_binding: str = ""
    route_of_elimination: str = ""
    volume_of_distribution: str = ""
    clearance: str = "" # eg "renal", "hepatic", "other"
    created_date: str = ""
    updated_date: str = ""

    # these lists might be too large
    interactions: List[DrugInteraction] = []
    food_interactions: List[str] = []
    products: List[DrugProduct] = []
    international_brands: List[DrugInternationalBrand] = []
    
    groups: List[str] = []
    categories: List[str] = []
    dosages: List[DrugDosage] = []
    mixtures: List[DrugMixture] = []
    atc_codes: List[str] = []
    targets: List[DrugTarget] = []
    enzymes: List[DrugEnzyme] = []
    carriers: List[DrugCarrier] = []
    transporters: List[DrugTransporter] = []
    
#section: Drug related models

class DrugSynonym(BaseModel):
    synonym: str

class DrugGroup(BaseModel):
    group_name: str # eg "approved", "investigational", "withdrawn", "illicit", "nutraceutical"

class DrugCategory(BaseModel):
    category: str # eg "antibiotic", "antidepressant", "antihypertensive", "analgesic", "antiviral", etc.

class DrugProduct(BaseModel):
    product_name: str # eg "Tylenol Extra Strength"
    labeller: str = ""
    ndc_id: str = ""
    ndc_product_code: str = ""
    dpd_id: str = ""
    ema_product_code: str = ""
    ema_ma_number: str = ""
    fda_application_number: str = ""
    dosage_form: str = ""
    strength: str = ""
    route: str = ""
    country: str = ""
    source: str = ""
    generic: bool = False
    over_the_counter: bool = False
    approved: bool = False
    started_marketing_on: str = ""
    ended_marketing_on: str = ""

class DrugDosage(BaseModel):
    form: str = ""
    route: str = ""
    strength: str = ""

class DrugInternationalBrand(BaseModel):
    brand_name: str # eg "Tylenol"
    company: str = "" # eg "Johnson & Johnson"

class DrugMixture(BaseModel):
    mixture_name: str # eg "Tylenol Extra Strength"
    ingredients: str = ""
    supplemental_ingredients: str = ""

class DrugAtcCode(BaseModel):
    code: str

class DrugExternalIdentifier(BaseModel):
    resource: str
    identifier: str

class DrugReference(BaseModel):
    ref_type: str  # eg "article", "textbook", "link"
    pubmed_id: str = "" # for articles
    isbn: str = ""
    citation: str = ""
    title: str = ""
    url: str = ""
    ref_id: str = "" # unique identifier for this reference

class DrugTarget(BaseModel):
    target_id: str = ""
    name: str = "" # eg "EGFR" | "Epidermal Growth Factor Receptor"
    organism: str = ""
    known_action: str = ""
    actions: str = ""


class DrugEnzyme(BaseModel):
    enzyme_id: str = ""
    name: str = "" # eg "CYP3A4" | "Cytochrome P450 3A4"
    organism: str = ""
    known_action: str = ""
    actions: str = ""
    inhibition_strength: str = ""
    induction_strength: str = ""


class DrugCarrier(BaseModel):
    carrier_id: str = ""
    name: str = "" # eg "P-glycoprotein" | "P-gp" | "ABCB1"
    organism: str = ""
    known_action: str = ""
    actions: str = ""


class DrugTransporter(BaseModel):
    transporter_id: str = ""
    name: str = "" # eg "P-glycoprotein" | "P-gp" | "ABCB1"
    organism: str = ""
    known_action: str = ""
    actions: str = ""


class DrugInteraction(BaseModel):
    drug2_drugbank_id: str
    drug2_name: str
    description: str = ""


class DrugFoodInteraction(BaseModel):
    interaction: str # eg "Avoid grapefruit juice"

#section: app models
class DrugSearchRequest(BaseModel):
    """
    Search drugs by name, synonym, product name, or brand name.
    """
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=100)
    include_synonyms: bool = True
    include_products: bool = True
    include_brands: bool = True
    
    # whether to include results that match semantically but not lexically
    # (eg "high blood pressure" should match drugs indicated for "hypertension")
    include_semantic_search: bool = False 
    
    min_similarity: float = Field(default=0.3, ge=0.0, le=1.0)

class DrugSearchResponse(BaseModel):
    success: bool = True
    query: str
    results: List[DrugSearchResult]
    count: int
    search_time_ms: float | None = None

class DrugSearchResult(DrugDescription):
    similarity_score: float | None = None  # For fuzzy search, range from 0.0 to 1.0
    # How the query matched: "name" | "brand" | "synonym" (exact), "mixture"
    # (exact name of a combination product -> only ONE of its ingredients is
    # returned), "approximate" (trigram) or "semantic" (embedding).
    match_type: str | None = None

class CheckDrugInteractionRequest(BaseModel):
    drug_ids: List[str] = Field(..., min_length=2, max_length=10)

class CheckDrugInteractionResponse(BaseModel):
    # See LookupStatus. Defaults to "error" so a response built without an
    # explicit status can never read as "no interaction".
    status: LookupStatus = "error"
    interactions: List[DrugInteractionDetail] = []
    count: int = 0

    # Kept for API compatibility. Always None: there is no validated severity
    # source (see SEVERITY_NOT_RATED).
    overall_severity: float | None = None

    # Which requested drugs were found and checked, and which were not.
    checked_drugs: List[ResolvedDrugRef] = []
    unresolved_drug_ids: List[str] = []
    pairs_checked: int = 0
    pairs_total: int = 0
    error: LookupErrorInfo | None = None

class DrugInteractionDetail(BaseModel):
    drug1_id: str
    drug1_name: str
    drug2_id: str
    drug2_name: str
    description: str  # original DrugBank interaction text

    # None = no validated severity (source has no label, no expert review).
    severity: float | None = None
    severity_status: str = SEVERITY_NOT_RATED
    source: str = "DrugBank"
    # DrugBank page of the drug whose record lists this interaction.
    source_url: str = ""


class DrugFoodInteractionResult(BaseModel):
    """Food-interaction lookup with an explicit status (see LookupStatus)."""
    status: LookupStatus = "error"
    drug: ResolvedDrugRef | None = None
    interactions: List[DrugFoodInteraction] = []
    count: int = 0
    source: str = "DrugBank"
    source_url: str = ""
    error: LookupErrorInfo | None = None


class AlternativeCandidatesResult(BaseModel):
    """Same-category candidates for replacing a drug (unverified, see note)."""
    status: LookupStatus = "error"
    target: ResolvedDrugRef | None = None
    candidates: List[DrugAlternative] = []
    checked_current_drugs: List[ResolvedDrugRef] = []
    unresolved_current_drug_ids: List[str] = []
    # Candidates dropped because DrugBank holds an interaction record with one
    # of the checked medications (regardless of the record's wording).
    excluded_with_interaction_record: int = 0
    note: str = ALTERNATIVES_NOTE
    error: LookupErrorInfo | None = None

class DrugSearchByIndicationRequest(BaseModel):
    indication: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=20, ge=1, le=100)
    include_semantic_search: bool = False

class DrugSearchByIndicationResponse(BaseModel):
    success: bool = True
    indication: str
    results: List[DrugDescription]
    count: int
    search_time_ms: float | None = None
    
class DrugSearchByCategoryRequest(BaseModel):
    category: str = Field(..., min_length=1, max_length=100)
    limit: int = Field(default=20, ge=1, le=100)
    include_semantic_search: bool = False
    
class DrugSearchByCategoryResponse(BaseModel):
    success: bool = True
    category: str
    results: List[DrugDescription]
    count: int
    search_time_ms: float | None = None

class DrugAlternative(BaseModel):
    old_drug_id: str
    old_drug_name: str
    new_drug_id: str
    new_drug_name: str
    reason: str = "" # eg "safer for patients with renal impairment"

class AnalyzePatientRequest(BaseModel):
    """
    Analyze a patient's current + additional medications for interactions, and Patient Profile details.
    """
    patient_id: str
    
    # proposed additional medications to analyze along with the patient's current medications.
    additional_drug_ids: List[str] = []

class AnalyzePatientResponse(BaseModel):
    patient_id: str
    # Status of the drug-drug check over the patient's medications.
    status: LookupStatus = "error"
    current_drugs: List[DrugBase] = []
    interactions: List[DrugInteractionDetail] = []
    count: int = 0
    # Medication names from the patient record (or requested drug ids) that
    # could not be matched to a database drug and were therefore NOT checked.
    unresolved_medications: List[str] = []
    # How each recorded medication name was matched (approximate and
    # combination-product matches must be confirmed by the clinician).
    medication_matches: List[MedicationMatch] = []
    # Matched drugs beyond the 10-drug limit of one check (NOT checked).
    not_checked_over_limit: List[ResolvedDrugRef] = []
    pairs_checked: int = 0
    pairs_total: int = 0
    error: LookupErrorInfo | None = None
    # Kept for API compatibility; no longer filled automatically. Without a
    # validated severity there is no evidence-based way to decide which
    # interaction needs a substitute (see alternatives_note).
    safe_alternatives: List[DrugAlternative] = []
    alternatives_note: str = (
        "No replacement candidates are generated automatically: interaction "
        "severity is not rated by a source or an expert, so the need for a "
        "substitute cannot be established. Candidates can be requested "
        "explicitly and are unverified."
    )
    
class AnalyzePatientFoodInteractionsRequest(BaseModel):
    patient_id: str
    food_items: List[str] = []
    
    # current and proposed medications to check for interactions with the food items.
    additional_drug_ids: List[str] = []

class AnalyzePatientFoodInteractionsResponse(BaseModel):
    patient_id: str
    current_drugs: List[DrugBase] = []
    interactions: List[DrugFoodInteraction] = []
    count: int = 0
    
    # drugs that may not interact, or have very low severity interactions
    safe_alternatives: List[DrugAlternative] = []

class OverdoseRiskDetail(BaseModel):
    """Details about a potential overdose risk between two drugs."""
    drug1_id: str
    drug1_name: str
    drug2_id: str
    drug2_name: str
    reason: str  # Explanation of why there's an overdose risk
    shared_ingredients: List[str] = []  # List of shared active ingredients

class CheckOverdoseRiskResponse(BaseModel):
    """Response for overdose risk check."""
    # "found" = shared ingredient detected, "no_record" = none detected,
    # "unresolved" = fewer than two drugs found, "error" = lookup failed.
    status: LookupStatus = "error"
    has_risk: bool = False
    risks: List[OverdoseRiskDetail] = []
    count: int = 0
    unresolved_drug_ids: List[str] = []
    error: LookupErrorInfo | None = None

# do this at the end to avoid circular imports
Drug.model_rebuild()
