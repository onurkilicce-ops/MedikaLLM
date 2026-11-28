from __future__ import annotations
import json
import re
from typing import List, Optional, Union
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload, selectinload

# NOTE: calculate_severity (text-pattern scoring) is intentionally no longer
# used here. Its scores are not clinical labels (e.g. "This combination is not
# contraindicated." scores 1.0 = contraindicated) and must not drive what the
# user sees or which alternatives are offered. See models.SEVERITY_NOT_RATED.
from ..db.sql_client import get_session
from ..db.sql_models import (
    Drug as DrugORM,
    DrugSynonym,
    DrugGroup,
    DrugCategory,
    DrugProduct,
    DrugInternationalBrand,
    DrugMixture,
    DrugInteraction,
    DrugFoodInteraction,
    DrugDosage,
    DrugTarget,
    DrugEnzyme,
    DrugCarrier,
    DrugTransporter,
    DrugAtcCode,
    PatientRecord,
    UserRecord,
)
from .models import (
    Drug,
    DrugBase,
    DrugDescription,
    DrugSearchRequest,
    DrugSearchResponse,
    DrugSearchResult,
    CheckDrugInteractionRequest,
    CheckDrugInteractionResponse,
    DrugInteractionDetail,
    DrugFoodInteraction as DrugFoodInteractionModel,
    DrugSearchByIndicationRequest,
    DrugSearchByIndicationResponse,
    DrugSearchByCategoryRequest,
    DrugSearchByCategoryResponse,
    DrugAlternative,
    AnalyzePatientRequest,
    AnalyzePatientResponse,
    AnalyzePatientFoodInteractionsRequest,
    AnalyzePatientFoodInteractionsResponse,
    DrugDosage as DrugDosageModel,
    DrugTarget as DrugTargetModel,
    DrugEnzyme as DrugEnzymeModel,
    DrugCarrier as DrugCarrierModel,
    DrugTransporter as DrugTransporterModel,
    DrugInteraction as DrugInteractionModel,
    CheckOverdoseRiskResponse,
    OverdoseRiskDetail,
    AlternativeCandidatesResult,
    DrugFoodInteractionResult,
    LookupErrorInfo,
    ResolvedDrugRef,
    MedicationMatch,
    SEVERITY_NOT_RATED,
)

from logging import getLogger

logger = getLogger(__name__)

DRUGBANK_DRUG_URL = "https://go.drugbank.com/drugs/{drug_id}"

# Safe messages for lookup failures. Exception details stay in the server log.
_DB_ERROR = LookupErrorInfo(
    code="database_error",
    message="The drug database could not be queried; the result is unknown.",
)


def drugbank_url(drug_id: str | None) -> str:
    return DRUGBANK_DRUG_URL.format(drug_id=drug_id) if drug_id else ""


def _unique(items: List[str]) -> List[str]:
    """De-duplicate while keeping the caller's order."""
    return list(dict.fromkeys(i for i in items if i))

def _orm_to_drug_base(drug_orm: DrugORM) -> DrugBase:
    synonyms = [s.synonym for s in drug_orm.synonyms]
    
    return DrugBase(
        drug_id=drug_orm.drug_id, # type: ignore
        name=drug_orm.name, # type: ignore
        drug_type=drug_orm.drug_type, # type: ignore
        description=drug_orm.description, # type: ignore
        indication=drug_orm.indication, # type: ignore
        mechanism_of_action=drug_orm.mechanism_of_action, # type: ignore
        pharmacodynamics=drug_orm.pharmacodynamics, # type: ignore
        synonyms=synonyms,
    )


def _orm_to_drug_full(drug_orm: DrugORM, related: dict | None = None) -> Drug:
    """Convert an ORM drug to the full model.

    ``related`` holds pre-loaded (limited) rows for large relationships, keyed
    by relationship name; they are used instead of the ORM collections, which
    must not be reassigned (see get_drug).
    """
    related = related or {}

    def rel(name: str):
        return related[name] if name in related else getattr(drug_orm, name)

    # Basic fields
    drug = Drug(
        drug_id=drug_orm.drug_id, # type: ignore
        name=drug_orm.name, # type: ignore
        drug_type=drug_orm.drug_type, # type: ignore
        description=drug_orm.description, # type: ignore
        indication=drug_orm.indication, # type: ignore
        mechanism_of_action=drug_orm.mechanism_of_action, # type: ignore
        pharmacodynamics=drug_orm.pharmacodynamics, # type: ignore
        toxicity=drug_orm.toxicity, # type: ignore
        metabolism=drug_orm.metabolism, # type: ignore
        absorption=drug_orm.absorption, # type: ignore
        half_life=drug_orm.half_life, # type: ignore
        protein_binding=drug_orm.protein_binding, # type: ignore
        route_of_elimination=drug_orm.route_of_elimination, # type: ignore
        volume_of_distribution=drug_orm.volume_of_distribution, # type: ignore
        clearance=drug_orm.clearance, # type: ignore
        created_date=drug_orm.created_date, # type: ignore
        updated_date=drug_orm.updated_date, # type: ignore
    )
    
    # Relationships
    drug.synonyms = [s.synonym for s in drug_orm.synonyms]
    drug.groups = [g.group_name for g in drug_orm.groups]
    drug.categories = [c.category for c in drug_orm.categories]
    drug.atc_codes = [a.code for a in drug_orm.atc_codes]
    drug.food_interactions = [f.interaction for f in drug_orm.food_interactions]
    
    # Complex relationships
    drug.products = [ # type: ignore
        {
            "product_name": p.product_name,
            "labeller": p.labeller,
            "dosage_form": p.dosage_form,
            "strength": p.strength,
            "route": p.route,
            "country": p.country,
            "generic": p.generic,
            "over_the_counter": p.over_the_counter,
            "approved": p.approved,
        }
        for p in rel("products")
    ]
    
    drug.international_brands = [ # type: ignore
        {"brand_name": b.brand_name, "company": b.company}
        for b in rel("international_brands")
    ]
    
    drug.dosages = [ # type: ignore
        {"form": d.form, "route": d.route, "strength": d.strength}
        for d in drug_orm.dosages
    ]
    
    drug.mixtures = [ # type: ignore
        {
            "mixture_name": m.mixture_name,
            "ingredients": m.ingredients,
            "supplemental_ingredients": m.supplemental_ingredients,
        }
        for m in rel("mixtures")
    ]
    
    drug.targets = [ # type: ignore
        {
            "target_id": t.target_id,
            "name": t.name,
            "organism": t.organism,
            "known_action": t.known_action,
            "actions": t.actions,
        }
        for t in rel("targets")
    ]
    
    drug.enzymes = [ # type: ignore
        {
            "enzyme_id": e.enzyme_id,
            "name": e.name,
            "organism": e.organism,
            "known_action": e.known_action,
            "actions": e.actions,
            "inhibition_strength": e.inhibition_strength,
            "induction_strength": e.induction_strength,
        }
        for e in rel("enzymes")
    ]
    
    drug.carriers = [ # type: ignore
        {
            "carrier_id": c.carrier_id,
            "name": c.name,
            "organism": c.organism,
            "known_action": c.known_action,
            "actions": c.actions,
        }
        for c in rel("carriers")
    ]
    
    drug.transporters = [ # type: ignore
        {
            "transporter_id": t.transporter_id,
            "name": t.name,
            "organism": t.organism,
            "known_action": t.known_action,
            "actions": t.actions,
        }
        for t in rel("transporters")
    ]
    
    drug.interactions = [ # type: ignore
        {
            "drug2_drugbank_id": i.drug2_drugbank_id,
            "drug2_name": i.drug2_name,
            "description": i.description,
        }
        for i in rel("interactions_as_drug1")
    ]
    
    return drug


def _resolve_drug_id(session, drug_id: str) -> Optional[DrugORM]:
    return session.query(DrugORM).filter(DrugORM.drug_id == drug_id).first()


# ============================================================================
# 1. GET DRUG - Full drug information by ID
# ============================================================================

def get_drug(drug_id: str, detail: str = "moderate") -> Optional[Union[Drug, DrugBase, DrugDescription]]:
    """
    Get drug information by drug_id with configurable detail level.
    
    Args:
        drug_id: DrugBank ID (e.g., "DB00945")
        detail: Level of detail - "low", "moderate", or "high"
            - low: DrugDescription (drug_id, name, description)
            - moderate: DrugBase (+ drug_type, indication, mechanism, pharmacodynamics, synonyms)
            - high: Drug (full information including interactions, products, targets, etc.)
    
    Returns:
        DrugDescription | DrugBase | Drug: Drug information based on detail level
    """
    logger.debug(f"[DRUG SERVICE] get_drug called with drug_id: {drug_id}, detail: {detail}")
    session = get_session()
    try:
        logger.debug(f"[DRUG SERVICE] Querying database for drug {drug_id}")
        
        if detail == "low":
            # Low detail: Only basic fields, no relationships
            drug_orm = (
                session.query(DrugORM.drug_id, DrugORM.name, DrugORM.description)
                .filter(DrugORM.drug_id == drug_id)
                .first()
            )
            
            if not drug_orm:
                logger.warning(f"[DRUG SERVICE] Drug not found: {drug_id}")
                return None
            
            logger.info(f"[DRUG SERVICE] Retrieved drug (low detail): {drug_orm.name} ({drug_id})")
            return DrugDescription(
                drug_id=drug_orm.drug_id,
                name=drug_orm.name,
                description=drug_orm.description or "",
            )
        
        elif detail == "moderate":
            # Moderate detail: DrugBase fields + synonyms
            drug_orm = (
                session.query(DrugORM)
                .options(joinedload(DrugORM.synonyms))
                .filter(DrugORM.drug_id == drug_id)
                .first()
            )
            
            if not drug_orm:
                logger.warning(f"[DRUG SERVICE] Drug not found: {drug_id}")
                return None
            
            logger.info(f"[DRUG SERVICE] Retrieved drug (moderate detail): {drug_orm.name} ({drug_id})")
            
            synonyms = [s.synonym for s in drug_orm.synonyms]
            
            return DrugBase(
                drug_id=drug_orm.drug_id, # type: ignore
                name=drug_orm.name, # type: ignore
                description=drug_orm.description or "", # type: ignore
                drug_type=drug_orm.drug_type or "", # type: ignore
                indication=drug_orm.indication or "", # type: ignore
                mechanism_of_action=drug_orm.mechanism_of_action or "", # type: ignore
                pharmacodynamics=drug_orm.pharmacodynamics or "", # type: ignore
                synonyms=synonyms,
            )
        
        else:  # detail == "high"
            # High detail: Full Drug model with all relationships.
            # selectinload (one extra query per collection) instead of
            # joinedload: joining six collections in one SELECT returns the
            # product of their sizes (synonyms x groups x categories x ...),
            # which made a single high-detail lookup take minutes.
            drug_orm = (
                session.query(DrugORM)
                .options(
                    selectinload(DrugORM.synonyms),
                    selectinload(DrugORM.groups),
                    selectinload(DrugORM.categories),
                    selectinload(DrugORM.atc_codes),
                    selectinload(DrugORM.food_interactions),
                    selectinload(DrugORM.dosages),
                )
                .filter(DrugORM.drug_id == drug_id)
                .first()
            )
            
            if not drug_orm:
                logger.warning(f"[DRUG SERVICE] Drug not found: {drug_id}")
                return None
            
            logger.info(f"[DRUG SERVICE] Retrieved drug (high detail): {drug_orm.name} ({drug_id})")
            
            # Load large relationships separately with limits to avoid memory
            # issues. Keep them in a dict: assigning a limited subset to an ORM
            # relationship (delete-orphan cascade) replaced the collection, and
            # the next query's autoflush then issued DELETE for every related
            # row beyond the limit (rolled back only because this session is
            # never committed; refused outright in a read-only transaction).
            drug_pk = drug_orm.id
            related = {
                "products": session.query(DrugProduct).filter(DrugProduct.drug_pk == drug_pk).limit(100).all(),
                "international_brands": session.query(DrugInternationalBrand).filter(DrugInternationalBrand.drug_pk == drug_pk).limit(100).all(),
                "mixtures": session.query(DrugMixture).filter(DrugMixture.drug_pk == drug_pk).limit(50).all(),
                "targets": session.query(DrugTarget).filter(DrugTarget.drug_pk == drug_pk).limit(50).all(),
                "enzymes": session.query(DrugEnzyme).filter(DrugEnzyme.drug_pk == drug_pk).limit(50).all(),
                "carriers": session.query(DrugCarrier).filter(DrugCarrier.drug_pk == drug_pk).limit(50).all(),
                "transporters": session.query(DrugTransporter).filter(DrugTransporter.drug_pk == drug_pk).limit(50).all(),
                "interactions_as_drug1": session.query(DrugInteraction).filter(DrugInteraction.drug1_id == drug_pk).limit(500).all(),
            }

            logger.debug(
                f"[DRUG SERVICE] High detail - loaded {len(related['targets'])} targets, "
                f"{len(related['enzymes'])} enzymes, {len(related['interactions_as_drug1'])} interactions (limited)"
            )

            return _orm_to_drug_full(drug_orm, related)
    
    except Exception as e:
        logger.error(f"[DRUG SERVICE] Error getting drug {drug_id}: {e}", exc_info=True)
        return None
    finally:
        session.close()

def search_drugs(request: DrugSearchRequest) -> DrugSearchResponse:
    """
    Hybrid search: combines TRGM fuzzy matching with semantic vector search.
    
    - TRGM: Good for typos, abbreviations, exact name matching
    - Semantic: Good for conceptual queries like "blood pressure medication"
    
    Args:
        request: Search parameters
    
    Returns:
        DrugSearchResponse: List of matching drugs with similarity scores
    """
    logger.debug(f"[DRUG SERVICE] search_drugs called with query: '{request.query}', limit: {request.limit}, semantic: {request.include_semantic_search}")
    logger.debug(f"[DRUG SERVICE] Search options - synonyms: {request.include_synonyms}, products: {request.include_products}, brands: {request.include_brands}")
    
    session = get_session()
    try:        
        search_term = request.query.lower().strip()
        if not search_term:
            logger.warning(f"[DRUG SERVICE] Empty search term provided")
            return DrugSearchResponse(
                success=True,
                query=request.query,
                results=[],
                count=0,
            )
        
        logger.debug(f"[DRUG SERVICE] Normalized search term: '{search_term}'")
        drug_map = {}  # drug_id -> {drug_orm, similarity_score, source}
        semantic_failed = False

        # ===== EXACT-MATCH SHORT-CIRCUIT =====
        # If the user query exactly matches a drug name, synonym, or brand
        # (case-insensitive, ignoring dashes/whitespace), return it immediately
        # with similarity=1.0. This avoids cases like "a-ferin" (whose A-Ferin
        # brand has TRGM 0.5) being beaten by "Adaferin" (TRGM 0.6).
        def _norm(s: str) -> str:
            return re.sub(r"[\s\-]+", "", (s or "").lower())

        norm_query = _norm(search_term)
        if norm_query:
            exact_drug_id = None
            exact_name = None
            exact_desc = None
            exact_dtype = None
            exact_kind = None

            # 1) Drug name exact (raw or dash-stripped)
            for d in (
                session.query(
                    DrugORM.drug_id, DrugORM.name, DrugORM.description, DrugORM.drug_type, DrugORM.name_lower
                )
                .filter(
                    or_(
                        DrugORM.name_lower == search_term,
                        func.replace(func.replace(DrugORM.name_lower, "-", ""), " ", "") == norm_query,
                    )
                )
                .limit(5)
                .all()
            ):
                exact_drug_id, exact_name, exact_desc, exact_dtype, _ = d
                exact_kind = "name"
                break

            # 2) Brand exact
            if not exact_drug_id and request.include_brands:
                row = (
                    session.query(
                        DrugORM.drug_id, DrugORM.name, DrugORM.description, DrugORM.drug_type
                    )
                    .join(DrugInternationalBrand, DrugORM.id == DrugInternationalBrand.drug_pk)
                    .filter(
                        or_(
                            DrugInternationalBrand.brand_name_lower == search_term,
                            func.replace(func.replace(DrugInternationalBrand.brand_name_lower, "-", ""), " ", "") == norm_query,
                        )
                    )
                    .first()
                )
                if row:
                    exact_drug_id, exact_name, exact_desc, exact_dtype = row
                    exact_kind = "brand"

            # 3) Synonym exact
            if not exact_drug_id and request.include_synonyms:
                row = (
                    session.query(
                        DrugORM.drug_id, DrugORM.name, DrugORM.description, DrugORM.drug_type
                    )
                    .join(DrugSynonym, DrugORM.id == DrugSynonym.drug_pk)
                    .filter(
                        or_(
                            DrugSynonym.synonym_lower == search_term,
                            func.replace(func.replace(DrugSynonym.synonym_lower, "-", ""), " ", "") == norm_query,
                        )
                    )
                    .first()
                )
                if row:
                    exact_drug_id, exact_name, exact_desc, exact_dtype = row
                    exact_kind = "synonym"

            # 4) Mixture exact (multi-ingredient TR brands like A-Ferin codeine combo)
            if not exact_drug_id:
                row = (
                    session.query(
                        DrugORM.drug_id, DrugORM.name, DrugORM.description, DrugORM.drug_type
                    )
                    .join(DrugMixture, DrugORM.id == DrugMixture.drug_pk)
                    .filter(
                        or_(
                            DrugMixture.mixture_name_lower == search_term,
                            func.replace(func.replace(DrugMixture.mixture_name_lower, "-", ""), " ", "") == norm_query,
                        )
                    )
                    .first()
                )
                if row:
                    exact_drug_id, exact_name, exact_desc, exact_dtype = row
                    exact_kind = "mixture"

            if exact_drug_id:
                logger.info(
                    f"[DRUG SERVICE] Exact match for '{request.query}' -> {exact_name} ({exact_drug_id})"
                )
                return DrugSearchResponse(
                    success=True,
                    query=request.query,
                    results=[
                        DrugSearchResult(
                            drug_id=exact_drug_id,
                            name=exact_name,
                            description=exact_desc or "",
                            similarity_score=1.0,
                            match_type=exact_kind,
                        )
                    ],
                    count=1,
                )

        # ===== LEXICAL SEARCH (TRGM) =====
        
        # 1. Search by drug name (TRGM similarity)
        if True:  # Always search names
            logger.debug(f"[DRUG SERVICE] Searching by drug name (TRGM)")
            name_results = (
                session.query(
                    DrugORM.drug_id,
                    DrugORM.name,
                    DrugORM.description,
                    DrugORM.drug_type,
                    func.similarity(DrugORM.name_lower, search_term).label("similarity"),
                )
                .filter(func.similarity(DrugORM.name_lower, search_term) > request.min_similarity)
                .order_by(func.similarity(DrugORM.name_lower, search_term).desc())
                .limit(request.limit * 2)
                .all()
            )
            
            logger.debug(f"[DRUG SERVICE] Found {len(name_results)} name matches")
            
            for drug_id, name, desc, dtype, sim in name_results:
                if drug_id not in drug_map or drug_map[drug_id]["similarity"] < sim:
                    drug_map[drug_id] = {
                        "drug_id": drug_id,
                        "name": name,
                        "description": desc,
                        "drug_type": dtype,
                        "similarity": sim,
                        "source": "name",
                    }
        
        # 2. Search by synonym
        if request.include_synonyms:
            logger.debug(f"[DRUG SERVICE] Searching by synonyms (TRGM)")
            syn_results = (
                session.query(
                    DrugORM.drug_id,
                    DrugORM.name,
                    DrugORM.description,
                    DrugORM.drug_type,
                    func.similarity(DrugSynonym.synonym_lower, search_term).label("similarity"),
                )
                .join(DrugSynonym, DrugORM.id == DrugSynonym.drug_pk)
                .filter(func.similarity(DrugSynonym.synonym_lower, search_term) > request.min_similarity)
                .order_by(func.similarity(DrugSynonym.synonym_lower, search_term).desc())
                .limit(request.limit)
                .all()
            )
            
            logger.debug(f"[DRUG SERVICE] Found {len(syn_results)} synonym matches")
            
            for drug_id, name, desc, dtype, sim in syn_results:
                if drug_id not in drug_map or drug_map[drug_id]["similarity"] < sim:
                    drug_map[drug_id] = {
                        "drug_id": drug_id,
                        "name": name,
                        "description": desc,
                        "drug_type": dtype,
                        "similarity": sim,
                        "source": "synonym",
                    }
        
        # 3. Search by product name
        if request.include_products:
            logger.debug(f"[DRUG SERVICE] Searching by products (TRGM)")
            prod_results = (
                session.query(
                    DrugORM.drug_id,
                    DrugORM.name,
                    DrugORM.description,
                    DrugORM.drug_type,
                    func.similarity(DrugProduct.product_name_lower, search_term).label("similarity"),
                )
                .join(DrugProduct, DrugORM.id == DrugProduct.drug_pk)
                .filter(func.similarity(DrugProduct.product_name_lower, search_term) > request.min_similarity)
                .order_by(func.similarity(DrugProduct.product_name_lower, search_term).desc())
                .limit(request.limit)
                .all()
            )
            
            logger.debug(f"[DRUG SERVICE] Found {len(prod_results)} product matches")
            
            for drug_id, name, desc, dtype, sim in prod_results:
                if drug_id not in drug_map or drug_map[drug_id]["similarity"] < sim * 0.9:  # Slight penalty
                    drug_map[drug_id] = {
                        "drug_id": drug_id,
                        "name": name,
                        "description": desc,
                        "drug_type": dtype,
                        "similarity": sim * 0.9,
                        "source": "product",
                    }
        
        # 4. Search by international brand
        if request.include_brands:
            logger.debug(f"[DRUG SERVICE] Searching by brands (TRGM)")
            brand_results = (
                session.query(
                    DrugORM.drug_id,
                    DrugORM.name,
                    DrugORM.description,
                    DrugORM.drug_type,
                    func.similarity(DrugInternationalBrand.brand_name_lower, search_term).label("similarity"),
                )
                .join(DrugInternationalBrand, DrugORM.id == DrugInternationalBrand.drug_pk)
                .filter(func.similarity(DrugInternationalBrand.brand_name_lower, search_term) > request.min_similarity)
                .order_by(func.similarity(DrugInternationalBrand.brand_name_lower, search_term).desc())
                .limit(request.limit)
                .all()
            )
            
            logger.debug(f"[DRUG SERVICE] Found {len(brand_results)} brand matches")
            
            for drug_id, name, desc, dtype, sim in brand_results:
                if drug_id not in drug_map or drug_map[drug_id]["similarity"] < sim * 0.9:
                    drug_map[drug_id] = {
                        "drug_id": drug_id,
                        "name": name,
                        "description": desc,
                        "drug_type": dtype,
                        "similarity": sim * 0.9,
                        "source": "brand",
                    }
        
        # ===== SEMANTIC SEARCH (VECTOR) =====

        # Short-circuit: if lexical search already has a strong hit
        # (sim >= 0.7), skip semantic search entirely. Semantic search is
        # CPU-bound (PyTorch forward pass, ~300-500ms + lock contention) and
        # for drug-name lookups it often drags in unrelated-but-topically-
        # adjacent drugs that dilute a perfectly good TRGM match.
        _STRONG_LEXICAL_THRESHOLD = 0.7
        strong_lexical = any(
            r["similarity"] >= _STRONG_LEXICAL_THRESHOLD for r in drug_map.values()
        )
        if request.include_semantic_search and strong_lexical:
            logger.debug(
                f"[DRUG SERVICE] Skipping semantic search — lexical top score "
                f">= {_STRONG_LEXICAL_THRESHOLD}"
            )

        if request.include_semantic_search and not strong_lexical:
            logger.debug(f"[DRUG SERVICE] Performing semantic search")
            try:
                from .embedding_service import get_embedding_service
                embedding_service = get_embedding_service()
                
                # Semantic search with slightly lower threshold
                semantic_results = embedding_service.search_similar_drugs(
                    query=request.query,
                    limit=request.limit * 2,
                    min_similarity=max(0.3, request.min_similarity - 0.1)  # Slightly lower threshold
                )
                
                logger.debug(f"[DRUG SERVICE] Found {len(semantic_results)} semantic matches")
                
                # Merge semantic results with a weight factor
                # Semantic scores are typically lower, so we boost them slightly
                semantic_weight = 0.85  # Semantic results get 85% weight vs lexical
                
                for drug_id, name, desc, sim in semantic_results:
                    weighted_sim = sim * semantic_weight
                    
                    if drug_id not in drug_map:
                        # New result from semantic search only
                        drug_map[drug_id] = {
                            "drug_id": drug_id,
                            "name": name,
                            "description": desc,
                            "drug_type": "",  # Not available from semantic search
                            "similarity": weighted_sim,
                            "source": "semantic",
                        }
                    else:
                        # Drug found in both lexical and semantic search
                        # Boost the score (hybrid boost)
                        existing_sim = drug_map[drug_id]["similarity"]
                        # Take max of existing and semantic, then add small boost for appearing in both
                        boosted_sim = max(existing_sim, weighted_sim) + 0.05
                        drug_map[drug_id]["similarity"] = min(1.0, boosted_sim)  # Cap at 1.0
                        drug_map[drug_id]["source"] = "hybrid"
                
                logger.info(f"[DRUG SERVICE] Hybrid search: {len(drug_map)} total unique drugs after merging")
                
            except Exception as e:
                logger.error(f"[DRUG SERVICE] Semantic search failed: {e}", exc_info=True)
                # Continue with lexical results only; if there are none, the
                # search failed rather than "found nothing" (see below).
                semantic_failed = True
        
        # Sort by similarity and limit
        results = sorted(
            drug_map.values(),
            key=lambda x: x["similarity"],
            reverse=True,
        )[:request.limit]
        
        # Convert to response models
        search_results = [
            DrugSearchResult(
                drug_id=r["drug_id"],
                name=r["name"],
                description=r["description"],
                similarity_score=r["similarity"],
                match_type="semantic" if r.get("source") == "semantic" else "approximate",
            )
            for r in results
        ]
        
        logger.info(f"[DRUG SERVICE] Search '{request.query}' found {len(search_results)} results (semantic: {request.include_semantic_search})")
        
        if semantic_failed and not search_results:
            return DrugSearchResponse(success=False, query=request.query, results=[], count=0)

        return DrugSearchResponse(
            success=True,
            query=request.query,
            results=search_results,
            count=len(search_results),
        )
    
    except Exception as e:
        logger.error(f"[DRUG SERVICE] Error searching drugs: {e}", exc_info=True)
        return DrugSearchResponse(
            success=False,
            query=request.query,
            results=[],
            count=0,
        )
    finally:
        session.close()

def check_drug_interactions(request: CheckDrugInteractionRequest) -> CheckDrugInteractionResponse:
    """
    Check every pair of the requested drugs for a documented DrugBank interaction.

    The response always carries an explicit ``status`` (see models.LookupStatus):
    a database failure, an unknown drug id and a successful query without
    records are distinguishable, and drugs that could not be found are listed
    in ``unresolved_drug_ids`` instead of being dropped silently. Severity is
    reported as not rated (no source label / expert review exists).
    """
    drug_ids = _unique(list(request.drug_ids))
    n = len(drug_ids)
    pairs_total = n * (n - 1) // 2
    logger.debug(f"[DRUG SERVICE] check_drug_interactions called with {n} drugs: {drug_ids}")

    session = None
    try:
        session = get_session()
        drugs = session.query(DrugORM).filter(DrugORM.drug_id.in_(drug_ids)).all()
        drug_map = {d.drug_id: d for d in drugs}
        resolved_ids = [d for d in drug_ids if d in drug_map]
        unresolved_ids = [d for d in drug_ids if d not in drug_map]
        checked = [
            ResolvedDrugRef(drug_id=drug_map[d].drug_id, name=drug_map[d].name)  # type: ignore[arg-type]
            for d in resolved_ids
        ]
        if unresolved_ids:
            logger.warning(f"[DRUG SERVICE] Unresolved drug ids (not checked): {unresolved_ids}")

        if len(resolved_ids) < 2:
            return CheckDrugInteractionResponse(
                status="unresolved",
                checked_drugs=checked,
                unresolved_drug_ids=unresolved_ids,
                pairs_checked=0,
                pairs_total=pairs_total,
            )

        interactions: List[DrugInteractionDetail] = []
        pairs_checked = 0
        for i, drug1_id in enumerate(resolved_ids):
            for drug2_id in resolved_ids[i + 1:]:
                drug1 = drug_map[drug1_id]
                drug2 = drug_map[drug2_id]
                pairs_checked += 1
                # A record may be stored under either drug.
                interaction = (
                    session.query(DrugInteraction)
                    .filter(
                        or_(
                            (DrugInteraction.drug1_id == drug1.id)
                            & (DrugInteraction.drug2_drugbank_id == drug2.drug_id),
                            (DrugInteraction.drug1_id == drug2.id)
                            & (DrugInteraction.drug2_drugbank_id == drug1.drug_id),
                        )
                    )
                    .first()
                )
                if not interaction:
                    continue
                owner = drug1 if interaction.drug1_id == drug1.id else drug2
                interactions.append(
                    DrugInteractionDetail(
                        drug1_id=drug1.drug_id,  # type: ignore[arg-type]
                        drug1_name=drug1.name,  # type: ignore[arg-type]
                        drug2_id=drug2.drug_id,  # type: ignore[arg-type]
                        drug2_name=drug2.name,  # type: ignore[arg-type]
                        description=interaction.description or "",  # type: ignore[arg-type]
                        severity=None,
                        severity_status=SEVERITY_NOT_RATED,
                        source="DrugBank",
                        source_url=drugbank_url(owner.drug_id),  # type: ignore[arg-type]
                    )
                )

        if unresolved_ids:
            status = "incomplete"
        elif interactions:
            status = "found"
        else:
            status = "no_record"
        logger.info(
            f"[DRUG SERVICE] Interaction check status={status}: {len(interactions)} record(s), "
            f"{pairs_checked}/{pairs_total} pairs checked"
        )
        return CheckDrugInteractionResponse(
            status=status,
            interactions=interactions,
            count=len(interactions),
            overall_severity=None,
            checked_drugs=checked,
            unresolved_drug_ids=unresolved_ids,
            pairs_checked=pairs_checked,
            pairs_total=pairs_total,
        )

    except Exception as e:
        logger.error(f"[DRUG SERVICE] Error checking drug interactions: {e}", exc_info=True)
        return CheckDrugInteractionResponse(
            status="error",
            pairs_total=pairs_total,
            error=_DB_ERROR,
        )
    finally:
        if session is not None:
            session.close()


def lookup_drug_food_interactions(drug_id: str) -> DrugFoodInteractionResult:
    """
    Food-interaction records for one drug, with an explicit status.

    ``unresolved``: no drug with that id; ``no_record``: the drug exists but
    DrugBank lists no food interaction (not evidence that there is none);
    ``error``: the lookup failed and the answer is unknown.
    """
    session = None
    try:
        session = get_session()
        drug = _resolve_drug_id(session, drug_id)
        if not drug:
            logger.warning(f"Drug not found: {drug_id}")
            return DrugFoodInteractionResult(status="unresolved")

        interactions = [
            DrugFoodInteractionModel(interaction=fi.interaction)
            for fi in drug.food_interactions
        ]
        logger.info(f"Found {len(interactions)} food interactions for {drug.name}")
        return DrugFoodInteractionResult(
            status="found" if interactions else "no_record",
            drug=ResolvedDrugRef(drug_id=drug.drug_id, name=drug.name),  # type: ignore[arg-type]
            interactions=interactions,
            count=len(interactions),
            source_url=drugbank_url(drug.drug_id),  # type: ignore[arg-type]
        )
    except Exception as e:
        logger.error(f"Error getting food interactions: {e}", exc_info=True)
        return DrugFoodInteractionResult(status="error", error=_DB_ERROR)
    finally:
        if session is not None:
            session.close()


def check_drug_food_interactions(drug_id: str) -> List[DrugFoodInteractionModel]:
    """
    Legacy list-only accessor kept for existing callers.

    It cannot distinguish a failed lookup from "no record" — new code must use
    ``lookup_drug_food_interactions``.
    """
    return lookup_drug_food_interactions(drug_id).interactions

def search_drugs_by_indication(request: DrugSearchByIndicationRequest) -> DrugSearchByIndicationResponse:
    """
    Search drugs by medical indication/condition.
    Supports both lexical (TRGM) and semantic (vector) search.
    
    Args:
        request: Indication search parameters
    
    Returns:
        DrugSearchByIndicationResponse: Drugs matching the indication
    """
    session = get_session()
    try:
        search_term = request.indication.lower().strip()
        drug_map = {}  # drug_id -> {drug_id, name, description, similarity}
        
        # ===== LEXICAL SEARCH (TRGM) =====
        logger.debug(f"[DRUG SERVICE] Searching by indication (TRGM): '{search_term}'")
        
        # Search in indication field using TRGM similarity
        results = (
            session.query(
                DrugORM.drug_id,
                DrugORM.name,
                DrugORM.description,
                func.similarity(func.lower(DrugORM.indication), search_term).label("similarity"),
            )
            .filter(func.similarity(func.lower(DrugORM.indication), search_term) > 0.2)
            .order_by(func.similarity(func.lower(DrugORM.indication), search_term).desc())
            .limit(request.limit * 2)
            .all()
        )
        
        logger.debug(f"[DRUG SERVICE] Found {len(results)} TRGM matches for indication")
        
        for drug_id, name, description, sim in results:
            drug_map[drug_id] = {
                "drug_id": drug_id,
                "name": name,
                "description": description,
                "similarity": sim,
            }
        
        # ===== SEMANTIC SEARCH (VECTOR) =====
        if request.include_semantic_search:
            logger.debug(f"[DRUG SERVICE] Performing semantic search for indication")
            try:
                from .embedding_service import get_embedding_service
                embedding_service = get_embedding_service()
                
                # Semantic search on indication field
                semantic_results = embedding_service.search_similar_drugs(
                    query=request.indication,
                    limit=request.limit * 2,
                    min_similarity=0.3
                )
                
                logger.debug(f"[DRUG SERVICE] Found {len(semantic_results)} semantic matches")
                
                semantic_weight = 0.85
                
                for drug_id, name, desc, sim in semantic_results:
                    weighted_sim = sim * semantic_weight
                    
                    if drug_id not in drug_map:
                        drug_map[drug_id] = {
                            "drug_id": drug_id,
                            "name": name,
                            "description": desc,
                            "similarity": weighted_sim,
                        }
                    else:
                        # Hybrid boost
                        existing_sim = drug_map[drug_id]["similarity"]
                        boosted_sim = max(existing_sim, weighted_sim) + 0.05
                        drug_map[drug_id]["similarity"] = min(1.0, boosted_sim)
                
                logger.info(f"[DRUG SERVICE] Hybrid indication search: {len(drug_map)} total unique drugs")
                
            except Exception as e:
                logger.error(f"[DRUG SERVICE] Semantic search failed: {e}", exc_info=True)
        
        # Sort by similarity and limit
        sorted_results = sorted(
            drug_map.values(),
            key=lambda x: x["similarity"],
            reverse=True,
        )[:request.limit]
        
        drug_results = [
            DrugDescription(
                drug_id=r["drug_id"],
                name=r["name"],
                description=r["description"],
            )
            for r in sorted_results
        ]
        
        logger.info(f"Found {len(drug_results)} drugs for indication '{request.indication}' (semantic: {request.include_semantic_search})")
        
        return DrugSearchByIndicationResponse(
            success=True,
            indication=request.indication,
            results=drug_results,
            count=len(drug_results),
        )
    
    except Exception as e:
        logger.error(f"Error searching by indication: {e}", exc_info=True)
        return DrugSearchByIndicationResponse(
            success=False,
            indication=request.indication,
            results=[],
            count=0,
        )
    finally:
        session.close()

def search_drugs_by_category(request: DrugSearchByCategoryRequest) -> DrugSearchByCategoryResponse:
    """
    Search drugs by therapeutic category.
    Supports both lexical (TRGM) and semantic (vector) search.
    
    Args:
        request: Category search parameters
    
    Returns:
        DrugSearchByCategoryResponse: Drugs in the category
    """
    session = get_session()
    try:
        search_term = request.category.lower().strip()
        drug_map = {}  # drug_id -> {drug_id, name, description, similarity}
        
        # ===== LEXICAL SEARCH (TRGM) =====
        logger.debug(f"[DRUG SERVICE] Searching by category (TRGM): '{search_term}'")
        
        # Search categories using TRGM similarity
        category_matches = (
            session.query(
                DrugCategory.drug_pk,
                func.similarity(DrugCategory.category_lower, search_term).label("similarity")
            )
            .filter(func.similarity(DrugCategory.category_lower, search_term) > 0.3)
            .order_by(func.similarity(DrugCategory.category_lower, search_term).desc())
            .limit(request.limit * 2)
            .all()
        )
        
        logger.debug(f"[DRUG SERVICE] Found {len(category_matches)} TRGM category matches")
        
        if category_matches:
            drug_pks_with_sim = {pk: sim for pk, sim in category_matches}
            drug_pks = list(drug_pks_with_sim.keys())
            
            # Get drugs
            drugs = (
                session.query(DrugORM.drug_id, DrugORM.name, DrugORM.description)
                .filter(DrugORM.id.in_(drug_pks))
                .all()
            )
            
            for drug_id, name, description in drugs:
                # Find the drug_pk to get similarity score
                drug_pk = session.query(DrugORM.id).filter(DrugORM.drug_id == drug_id).scalar()
                similarity = drug_pks_with_sim.get(drug_pk, 0.5)
                
                drug_map[drug_id] = {
                    "drug_id": drug_id,
                    "name": name,
                    "description": description,
                    "similarity": similarity,
                }
        
        # ===== SEMANTIC SEARCH (VECTOR) =====
        if request.include_semantic_search:
            logger.debug(f"[DRUG SERVICE] Performing semantic search for category")
            try:
                from .embedding_service import get_embedding_service
                embedding_service = get_embedding_service()
                
                # Semantic search
                semantic_results = embedding_service.search_similar_drugs(
                    query=request.category,
                    limit=request.limit * 2,
                    min_similarity=0.3
                )
                
                logger.debug(f"[DRUG SERVICE] Found {len(semantic_results)} semantic matches")
                
                semantic_weight = 0.85
                
                for drug_id, name, desc, sim in semantic_results:
                    weighted_sim = sim * semantic_weight
                    
                    if drug_id not in drug_map:
                        drug_map[drug_id] = {
                            "drug_id": drug_id,
                            "name": name,
                            "description": desc,
                            "similarity": weighted_sim,
                        }
                    else:
                        # Hybrid boost
                        existing_sim = drug_map[drug_id]["similarity"]
                        boosted_sim = max(existing_sim, weighted_sim) + 0.05
                        drug_map[drug_id]["similarity"] = min(1.0, boosted_sim)
                
                logger.info(f"[DRUG SERVICE] Hybrid category search: {len(drug_map)} total unique drugs")
                
            except Exception as e:
                logger.error(f"[DRUG SERVICE] Semantic search failed: {e}", exc_info=True)
        
        # Sort by similarity and limit
        sorted_results = sorted(
            drug_map.values(),
            key=lambda x: x["similarity"],
            reverse=True,
        )[:request.limit]
        
        drug_results = [
            DrugDescription(drug_id=r["drug_id"], name=r["name"], description=r["description"])
            for r in sorted_results
        ]
        
        logger.info(f"Found {len(drug_results)} drugs in category '{request.category}' (semantic: {request.include_semantic_search})")
        
        return DrugSearchByCategoryResponse(
            success=True,
            category=request.category,
            results=drug_results,
            count=len(drug_results),
        )
    
    except Exception as e:
        logger.error(f"Error searching by category: {e}", exc_info=True)
        return DrugSearchByCategoryResponse(
            success=False,
            category=request.category,
            results=[],
            count=0,
        )
    finally:
        session.close()

def find_alternative_candidates(current_drugs: List[str], for_drug_id: str) -> AlternativeCandidatesResult:
    """
    Same-category candidates for replacing ``for_drug_id`` (UNVERIFIED).

    Candidate generation is unchanged (drugs sharing one of the target's first
    five DrugBank categories). What changed: a candidate is dropped when
    DrugBank holds ANY interaction record with a checked current medication —
    the old filter kept records whose text-pattern score was <= 0.5, i.e. it
    kept documented interactions such as "may increase the risk of bleeding"
    and then described the candidate as having "no significant interactions".
    Current medications that cannot be found are reported, not dropped.
    """
    current_ids = _unique(list(current_drugs))
    session = None
    try:
        session = get_session()
        target_drug = _resolve_drug_id(session, for_drug_id)
        if not target_drug:
            logger.warning(f"Target drug not found: {for_drug_id}")
            return AlternativeCandidatesResult(status="unresolved")
        target_ref = ResolvedDrugRef(drug_id=target_drug.drug_id, name=target_drug.name)  # type: ignore[arg-type]

        resolved_current: list[DrugORM] = []
        unresolved_current: list[str] = []
        for cid in current_ids:
            d = _resolve_drug_id(session, cid)
            if d:
                resolved_current.append(d)
            else:
                unresolved_current.append(cid)
        checked_current = [
            ResolvedDrugRef(drug_id=d.drug_id, name=d.name)  # type: ignore[arg-type]
            for d in resolved_current
        ]

        target_categories = [c.category for c in target_drug.categories][:5]
        candidates: list[DrugORM] = []
        if target_categories:
            candidate_pk_rows = (
                session.query(DrugCategory.drug_pk)
                .filter(
                    DrugCategory.category.in_(target_categories),
                    DrugCategory.drug_pk != target_drug.id,
                )
                .limit(100)
                .all()
            )
            candidate_pks = list({pk for (pk,) in candidate_pk_rows})
            if candidate_pks:
                candidates = (
                    session.query(DrugORM)
                    .options(joinedload(DrugORM.groups), joinedload(DrugORM.categories))
                    .filter(DrugORM.id.in_(candidate_pks))
                    .all()
                )

        # One bulk query for interaction records between candidates and the
        # checked current medications (either storage direction).
        excluded_bids: set[str] = set()
        if candidates and resolved_current:
            candidate_pk_to_bid = {c.id: c.drug_id for c in candidates}
            candidate_bids = set(candidate_pk_to_bid.values())
            current_pks = [d.id for d in resolved_current]
            current_bids = [d.drug_id for d in resolved_current]
            records = (
                session.query(DrugInteraction.drug1_id, DrugInteraction.drug2_drugbank_id)
                .filter(
                    or_(
                        (DrugInteraction.drug1_id.in_(list(candidate_pk_to_bid.keys())))
                        & (DrugInteraction.drug2_drugbank_id.in_(current_bids)),
                        (DrugInteraction.drug1_id.in_(current_pks))
                        & (DrugInteraction.drug2_drugbank_id.in_(list(candidate_bids))),
                    )
                )
                .all()
            )
            for drug1_pk, drug2_bid in records:
                if drug1_pk in candidate_pk_to_bid:
                    excluded_bids.add(candidate_pk_to_bid[drug1_pk])
                if drug2_bid in candidate_bids:
                    excluded_bids.add(drug2_bid)

        target_cat_set = set(target_categories)
        alternatives: list[DrugAlternative] = []
        approved_ids: set[str] = set()
        current_bid_set = {d.drug_id for d in resolved_current}
        for candidate in candidates:
            if candidate.drug_id in excluded_bids or candidate.drug_id in current_bid_set:
                continue
            if any(g.group_name.lower() == "approved" for g in candidate.groups):
                approved_ids.add(candidate.drug_id)  # type: ignore[arg-type]
            shared = sorted({c.category for c in candidate.categories} & target_cat_set)
            alternatives.append(
                DrugAlternative(
                    old_drug_id=target_drug.drug_id,  # type: ignore[arg-type]
                    old_drug_name=target_drug.name,  # type: ignore[arg-type]
                    new_drug_id=candidate.drug_id,  # type: ignore[arg-type]
                    new_drug_name=candidate.name,  # type: ignore[arg-type]
                    reason=(
                        f"Shares DrugBank category: {', '.join(shared[:2]) or 'n/a'}. "
                        + (
                            "No DrugBank interaction record with the checked medications. "
                            if resolved_current
                            else "Not checked against any current medication (none given or found). "
                        )
                        + "Unverified candidate — not assessed for equivalence or safety."
                    ),
                )
            )
        alternatives.sort(key=lambda a: (a.new_drug_id not in approved_ids, a.new_drug_name))
        alternatives = alternatives[:10]

        if unresolved_current:
            status = "incomplete"
        elif alternatives:
            status = "found"
        else:
            status = "no_record"
        logger.info(
            f"Alternative candidates for {target_drug.name}: status={status}, "
            f"{len(alternatives)} kept, {len(excluded_bids)} excluded (interaction record)"
        )
        return AlternativeCandidatesResult(
            status=status,
            target=target_ref,
            candidates=alternatives,
            checked_current_drugs=checked_current,
            unresolved_current_drug_ids=unresolved_current,
            excluded_with_interaction_record=len(excluded_bids),
        )

    except Exception as e:
        logger.error(f"Error finding alternatives: {e}", exc_info=True)
        return AlternativeCandidatesResult(status="error", error=_DB_ERROR)
    finally:
        if session is not None:
            session.close()


def get_alternative_drugs(current_drugs: List[str], for_drug_id: str) -> List[DrugAlternative]:
    """Legacy list-only accessor; see ``find_alternative_candidates``."""
    return find_alternative_candidates(current_drugs, for_drug_id).candidates


def analyze_patient(request: AnalyzePatientRequest) -> AnalyzePatientResponse:
    """
    Analyze patient's medications for interactions and provide recommendations.
    
    Args:
        request: Patient analysis request
    
    Returns:
        AnalyzePatientResponse: Complete analysis with interactions and alternatives
    """
    session = None
    try:
        session = get_session()
        patient = session.query(PatientRecord).filter(
            PatientRecord.patient_id == request.patient_id
        ).first()

        if not patient:
            logger.warning(f"Patient not found: {request.patient_id}")
            return AnalyzePatientResponse(
                patient_id=request.patient_id,
                status="unresolved",
                error=LookupErrorInfo(code="patient_not_found", message="Patient record not found."),
            )

        # Current medications are stored as free-text names (e.g. "Metformin
        # 1000mg"); resolve them with the same search the agent tools use.
        current_med_names = json.loads(patient.current_medications) if patient.current_medications else []  # type: ignore

        resolved_ids: list[str] = []
        unresolved_meds: list[str] = []
        matches: list[MedicationMatch] = []
        for med_name in current_med_names:
            resp = search_drugs(DrugSearchRequest(
                query=med_name,
                limit=1,
                min_similarity=0.3,
                include_synonyms=True,
                include_products=True,
                include_brands=True,
            ))
            if not resp.success:
                # Name lookup failed (database error): the analysis cannot be trusted.
                raise RuntimeError("medication name lookup failed")
            if resp.results:
                top = resp.results[0]
                resolved_ids.append(top.drug_id)
                matches.append(MedicationMatch(
                    input=med_name, drug_id=top.drug_id, name=top.name,
                    similarity=top.similarity_score, match_type=top.match_type,
                ))
            else:
                logger.warning(f"analyze_patient: could not resolve '{med_name}'")
                unresolved_meds.append(med_name)

        all_drug_ids = _unique(resolved_ids + list(request.additional_drug_ids))

        drugs = (
            session.query(DrugORM).filter(DrugORM.drug_id.in_(all_drug_ids)).all()
            if all_drug_ids else []
        )
        drug_map = {d.drug_id: d for d in drugs}
        current_drug_bases = [
            _orm_to_drug_base(drug_map[drug_id])
            for drug_id in all_drug_ids
            if drug_id in drug_map
        ]
        unresolved_meds += [d for d in all_drug_ids if d not in drug_map]
        checkable = [d for d in all_drug_ids if d in drug_map]

        if len(checkable) < 2:
            return AnalyzePatientResponse(
                patient_id=request.patient_id,
                status="unresolved",
                current_drugs=current_drug_bases,
                unresolved_medications=unresolved_meds,
                medication_matches=matches,
            )

        # The pairwise check is capped at 10 drugs; the rest is reported as
        # not checked (with names and reason) instead of being dropped.
        to_check, overflow = checkable[:10], checkable[10:]
        over_limit = [
            ResolvedDrugRef(drug_id=d, name=drug_map[d].name)  # type: ignore[arg-type]
            for d in overflow
        ]
        interaction_response = check_drug_interactions(CheckDrugInteractionRequest(drug_ids=to_check))
        if interaction_response.status == "error":
            return AnalyzePatientResponse(
                patient_id=request.patient_id,
                status="error",
                current_drugs=current_drug_bases,
                unresolved_medications=unresolved_meds,
                medication_matches=matches,
                not_checked_over_limit=over_limit,
                error=interaction_response.error or _DB_ERROR,
            )

        status = interaction_response.status
        combination_matches = any(m.match_type == "mixture" for m in matches)
        if (unresolved_meds or over_limit or combination_matches) and status in ("found", "no_record"):
            status = "incomplete"

        logger.info(
            f"Analyzed patient {request.patient_id}: status={status}, "
            f"{interaction_response.count} interaction record(s), {len(unresolved_meds)} unresolved"
        )
        return AnalyzePatientResponse(
            patient_id=request.patient_id,
            status=status,
            current_drugs=current_drug_bases,
            interactions=interaction_response.interactions,
            count=interaction_response.count,
            unresolved_medications=unresolved_meds,
            medication_matches=matches,
            not_checked_over_limit=over_limit,
            pairs_checked=interaction_response.pairs_checked,
            # Coverage is reported against every checkable drug, not only the
            # first ten that were sent to the pairwise check.
            pairs_total=len(checkable) * (len(checkable) - 1) // 2,
            # Deliberately empty: see AnalyzePatientResponse.alternatives_note.
            safe_alternatives=[],
        )

    except Exception as e:
        logger.error(f"Error analyzing patient: {e}", exc_info=True)
        return AnalyzePatientResponse(
            patient_id=request.patient_id,
            status="error",
            error=_DB_ERROR,
        )
    finally:
        if session is not None:
            session.close()


# ============================================================================
# 10. ANALYZE PATIENT FOOD INTERACTIONS
# ============================================================================

def analyze_patient_food_interactions(
    request: AnalyzePatientFoodInteractionsRequest
) -> AnalyzePatientFoodInteractionsResponse:
    """
    Analyze patient's medications for food interactions.
    
    Args:
        request: Patient food interaction analysis request
    
    Returns:
        AnalyzePatientFoodInteractionsResponse: Food interactions and recommendations
    """
    session = get_session()
    try:
        # Get patient
        patient = session.query(PatientRecord).filter(
            PatientRecord.patient_id == request.patient_id
        ).first()
        
        if not patient:
            logger.warning(f"Patient not found: {request.patient_id}")
            return AnalyzePatientFoodInteractionsResponse(
                patient_id=request.patient_id,
                current_drugs=[],
                interactions=[],
                count=0,
                safe_alternatives=[],
            )
        
        # Parse current medications
        current_meds = json.loads(patient.current_medications) if patient.current_medications else [] # type: ignore
        all_drug_ids = current_meds + request.additional_drug_ids
        
        if not all_drug_ids:
            return AnalyzePatientFoodInteractionsResponse(
                patient_id=request.patient_id,
                current_drugs=[],
                interactions=[],
                count=0,
                safe_alternatives=[],
            )
        
        # Get drug details
        drugs = session.query(DrugORM).filter(DrugORM.drug_id.in_(all_drug_ids)).all()
        drug_map = {d.drug_id: d for d in drugs}
        
        current_drug_bases = [
            _orm_to_drug_base(drug_map[drug_id])
            for drug_id in all_drug_ids
            if drug_id in drug_map
        ]
        
        # Get all food interactions
        all_food_interactions = []
        for drug_id in all_drug_ids:
            if drug_id in drug_map:
                drug = drug_map[drug_id]
                for fi in drug.food_interactions:
                    all_food_interactions.append(
                        DrugFoodInteractionModel(interaction=fi.interaction)
                    )
        
        logger.info(f"Found {len(all_food_interactions)} food interactions for patient {request.patient_id}")
        
        return AnalyzePatientFoodInteractionsResponse(
            patient_id=request.patient_id,
            current_drugs=current_drug_bases,
            interactions=all_food_interactions,
            count=len(all_food_interactions),
            safe_alternatives=[],  # Could implement alternative suggestions
        )
    
    except Exception as e:
        logger.error(f"Error analyzing patient food interactions: {e}", exc_info=True)
        return AnalyzePatientFoodInteractionsResponse(
            patient_id=request.patient_id,
            current_drugs=[],
            interactions=[],
            count=0,
            safe_alternatives=[],
        )
    finally:
        session.close()


# ============================================================================
# 11. CHECK OVERDOSE RISK (SAME ACTIVE INGREDIENT)
# ============================================================================

def check_overdose_risk(drug_ids: List[str]) -> CheckOverdoseRiskResponse:
    """
    Check if multiple drugs contain the same active ingredient, which could lead to overdose.
    
    This function checks for:
    1. Drugs that are actually the same drug (same drug_id)
    2. Drugs that share the same name or synonyms (e.g., Tylenol and Acetaminophen)
    3. Combination drugs that share common ingredients
    
    Args:
        drug_ids: List of drug IDs to check
    
    Returns:
        CheckOverdoseRiskResponse: Overdose risks found
    """
    logger.debug(f"[DRUG SERVICE] check_overdose_risk called with {len(drug_ids)} drugs: {drug_ids}")
    # The same drug id listed more than once (e.g. a brand and its generic
    # resolved to one record) is the clearest duplicate-ingredient case; it
    # used to be lost by de-duplication before the pairwise check.
    duplicate_ids = [d for d in dict.fromkeys(drug_ids) if list(drug_ids).count(d) > 1]
    drug_ids = _unique(list(drug_ids))

    session = None
    try:
        session = get_session()
        if len(drug_ids) < 2 and not duplicate_ids:
            logger.warning(f"[DRUG SERVICE] Insufficient drugs provided: {len(drug_ids)}")
            return CheckOverdoseRiskResponse(status="unresolved", unresolved_drug_ids=[])

        # Get all drugs with their synonyms and mixtures
        logger.debug(f"[DRUG SERVICE] Fetching drug records with synonyms and mixtures")
        drugs = (
            session.query(DrugORM)
            .options(
                joinedload(DrugORM.synonyms),
                joinedload(DrugORM.mixtures)
            )
            .filter(DrugORM.drug_id.in_(drug_ids))
            .all()
        )
        
        found_ids = {d.drug_id for d in drugs}
        unresolved_ids = [d for d in drug_ids if d not in found_ids]
        duplicate_risks = [
            OverdoseRiskDetail(
                drug1_id=d.drug_id, drug1_name=d.name,  # type: ignore[arg-type]
                drug2_id=d.drug_id, drug2_name=d.name,  # type: ignore[arg-type]
                reason="The same medication appears more than once in the list (different names for one drug).",
                shared_ingredients=[d.name],  # type: ignore[list-item]
            )
            for d in drugs if d.drug_id in duplicate_ids
        ]
        if len(drugs) < 2:
            if duplicate_risks:
                return CheckOverdoseRiskResponse(
                    status="incomplete" if unresolved_ids else "found",
                    has_risk=True, risks=duplicate_risks, count=len(duplicate_risks),
                    unresolved_drug_ids=unresolved_ids,
                )
            logger.warning(f"[DRUG SERVICE] Only found {len(drugs)} drugs in database")
            return CheckOverdoseRiskResponse(status="unresolved", unresolved_drug_ids=unresolved_ids)

        logger.debug(f"[DRUG SERVICE] Found {len(drugs)} drugs in database")
        
        risks = list(duplicate_risks)

        # Check all pairs
        for i, drug1 in enumerate(drugs):
            for drug2 in drugs[i + 1:]:
                # Build sets of all names/synonyms for each drug
                drug1_names = {drug1.name.lower()}
                drug1_names.update(s.synonym.lower() for s in drug1.synonyms)
                
                drug2_names = {drug2.name.lower()}
                drug2_names.update(s.synonym.lower() for s in drug2.synonyms)
                
                # Check if they share any names (indicating same active ingredient)
                shared_names = drug1_names & drug2_names
                
                if shared_names:
                    logger.info(f"[DRUG SERVICE] Overdose risk: {drug1.name} and {drug2.name} share names: {shared_names}")
                    risks.append(
                        OverdoseRiskDetail(
                            drug1_id=drug1.drug_id, # type: ignore
                            drug1_name=drug1.name, # type: ignore
                            drug2_id=drug2.drug_id, # type: ignore
                            drug2_name=drug2.name, # type: ignore
                            reason=f"These are the same medication under different names. Taking both could result in an overdose.",
                            shared_ingredients=list(shared_names),
                        )
                    )
                    continue
                
                # Check if combination drugs share ingredients
                if drug1.mixtures and drug2.mixtures:
                    for mix1 in drug1.mixtures:
                        for mix2 in drug2.mixtures:
                            if mix1.ingredients and mix2.ingredients:
                                # Parse ingredients (comma-separated)
                                ingredients1 = {ing.strip().lower() for ing in mix1.ingredients.split(',')}
                                ingredients2 = {ing.strip().lower() for ing in mix2.ingredients.split(',')}
                                
                                shared_ingredients = ingredients1 & ingredients2
                                
                                if shared_ingredients:
                                    logger.info(f"[DRUG SERVICE] Overdose risk: {drug1.name} and {drug2.name} share ingredients: {shared_ingredients}")
                                    risks.append(
                                        OverdoseRiskDetail(
                                            drug1_id=drug1.drug_id, # type: ignore
                                            drug1_name=drug1.name, # type: ignore
                                            drug2_id=drug2.drug_id, # type: ignore
                                            drug2_name=drug2.name, # type: ignore
                                            reason=f"These combination medications contain the same active ingredient(s). Taking both could result in an overdose.",
                                            shared_ingredients=list(shared_ingredients),
                                        )
                                    )
                                    break
        
        logger.info(f"[DRUG SERVICE] Found {len(risks)} overdose risks among {len(drug_ids)} drugs")

        if unresolved_ids:
            status = "incomplete"
        elif risks:
            status = "found"
        else:
            status = "no_record"
        return CheckOverdoseRiskResponse(
            status=status,
            has_risk=len(risks) > 0,
            risks=risks,
            count=len(risks),
            unresolved_drug_ids=unresolved_ids,
        )

    except Exception as e:
        logger.error(f"[DRUG SERVICE] Error checking overdose risk: {e}", exc_info=True)
        return CheckOverdoseRiskResponse(status="error", error=_DB_ERROR)
    finally:
        if session is not None:
            session.close()
