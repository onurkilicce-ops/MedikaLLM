from fastapi import APIRouter, Depends, HTTPException, Query, Request

from . import service
from ..auth.dependencies import get_current_user, get_current_user_id
from ..auth.models import UserBase
from ..middleware.rate_limiter import SEARCH_LIMIT, limiter, user_key
from .models import (
    AnalyzePatientRequest,
    AnalyzePatientResponse,
    CheckDrugInteractionRequest,
    CheckDrugInteractionResponse,
    DrugSearchRequest,
    DrugSearchResponse,
)

from logging import getLogger

logger = getLogger(__name__)

# All drug endpoints now require authentication (audit S6). The previous
# version exposed the entire drug catalogue and interaction graph to anonymous
# clients, which leaks the curated DrugBank data set the project is built on.
router = APIRouter(
    prefix="/api/drugs",
    tags=["drugs"],
    dependencies=[Depends(get_current_user_id)],
)


@router.get("/search/{query}")
@limiter.limit(SEARCH_LIMIT, key_func=user_key)
async def endpoint_search_drugs(
    request: Request,
    query: str,
    include_semantic_search: bool = False,
    min_similarity: float = 0.3,
):
    try:
        drug_search_request = DrugSearchRequest(
            query=query,
            include_semantic_search=include_semantic_search,
            min_similarity=min_similarity,
        )
        result: DrugSearchResponse = service.search_drugs(drug_search_request)
        return result
    except Exception:
        logger.error(f"Error searching drugs with query '{query}'", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to search drugs")


@router.get("/interaction/{drug1_id}/{drug2_id}")
@limiter.limit(SEARCH_LIMIT, key_func=user_key)
async def endpoint_check_pair_interaction_by_ids(
    request: Request,
    drug1_id: str,
    drug2_id: str,
):
    """Check for interactions between two drugs by their IDs."""
    try:
        check_request = CheckDrugInteractionRequest(drug_ids=[drug1_id, drug2_id])
        result: CheckDrugInteractionResponse = service.check_drug_interactions(check_request)
        return result
    except Exception:
        logger.error(
            f"Error checking interaction between '{drug1_id}' and '{drug2_id}'",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to check interaction")


# Audit I17: a GET with a JSON body is non-standard and many proxies will
# silently drop the body. Switched to POST so the multi-drug interaction check
# behaves consistently across deployments.
@router.post("/interactions")
@limiter.limit(SEARCH_LIMIT, key_func=user_key)
async def endpoint_check_multiple_interactions_by_id(
    request: Request,
    body: CheckDrugInteractionRequest,
):
    """Check for interactions between multiple drug IDs (2-10)."""
    try:
        result: CheckDrugInteractionResponse = service.check_drug_interactions(body)
        return result
    except Exception:
        logger.error(
            f"Error checking interactions for drugs '{body.drug_ids}'", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to check interactions")


@router.post("/analyze-patient", response_model=AnalyzePatientResponse)
@limiter.limit(SEARCH_LIMIT, key_func=user_key)
async def endpoint_analyze_patient(
    request: Request,
    body: AnalyzePatientRequest,
    current_user: UserBase = Depends(get_current_user),
):
    """Analyze a patient's recorded medications for interactions.

    Access follows the shared patient-record policy
    (``users.service.resolve_patient_access``): the patient's own record, or
    a patient assigned to the calling doctor. The analysis service is only
    called after that check succeeded. Nothing is written to the patient's
    medication list.
    """
    from ..db.sql_client import get_session
    from ..users.service import PATIENT_ACCESS_GRANTED, PATIENT_NOT_FOUND, resolve_patient_access

    session = get_session()
    try:
        _, outcome = resolve_patient_access(session, body.patient_id, current_user.user_id)
    except Exception:
        logger.error("Patient access check failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to analyze patient medications")
    finally:
        session.close()

    if outcome == PATIENT_NOT_FOUND:
        raise HTTPException(status_code=404, detail="Patient not found")
    if outcome not in PATIENT_ACCESS_GRANTED:
        raise HTTPException(status_code=403, detail="Not authorized to analyze this patient's medications")

    try:
        result = service.analyze_patient(body)
        return result
    except Exception:
        logger.error(f"Error analyzing patient '{body.patient_id}'", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to analyze patient medications")


# NOTE: This catch-all must remain LAST — any GET /api/drugs/{x} route defined
# after this point would be shadowed by the {drug_id} parameter.
@router.get("/{drug_id}")
@limiter.limit(SEARCH_LIMIT, key_func=user_key)
async def endpoint_get_drug_by_id(
    request: Request,
    drug_id: str,
    detail: str = Query(
        default="high",
        pattern="^(low|moderate|high)$",
        description="Level of detail: low, moderate, or high",
    ),
):
    """Get drug information by drug ID."""
    try:
        result = service.get_drug(drug_id, detail=detail)
        if not result:
            raise HTTPException(status_code=404, detail=f"Drug '{drug_id}' not found")
        return result
    except HTTPException:
        raise
    except Exception:
        logger.error(f"Error fetching drug info for '{drug_id}'", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch drug info")
