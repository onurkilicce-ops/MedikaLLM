"""``POST /api/mechanism/compare`` - read-only organ / protein view (M-03).

Uses the same Bearer token and healthcare-professional check as M-02
(``timing.router.require_professional``); a database error is 503.
"""
from __future__ import annotations

from logging import getLogger

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

from ..auth.dependencies import security
from ..middleware.rate_limiter import SEARCH_LIMIT, limiter, user_key
from ..timing import router as timing_router
from ..timing.router import _ERROR_RESPONSES
from . import repository, service
from .models import MechanismRequest, MechanismResponse

logger = getLogger(__name__)

router = APIRouter(prefix="/api/mechanism", tags=["mechanism"])

UNAVAILABLE_DETAIL = "Mechanism data is temporarily unavailable; no result was produced."



def require_professional(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """M-02's check, with this feature's own 503 text (a user lookup that cannot
    reach the database is not reported as 'Timing data ...')."""
    try:
        return timing_router.require_professional(credentials)
    except HTTPException as exc:
        if exc.status_code == 503:
            raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL)
        raise


_RESPONSES = dict(_ERROR_RESPONSES)
_RESPONSES[503] = {"description": "The database could not be read. Not 'no proteins', not an empty success.",
                  "content": {"application/json": {"example": {"detail": UNAVAILABLE_DETAIL}}}}
_RESPONSES[422] = {"description": "Body is not 1-10 distinct DrugBank ids ('DB' + 5 digits), or has extra fields."}


@router.post("/compare", response_model=MechanismResponse, responses=_RESPONSES)
@limiter.limit(SEARCH_LIMIT, key_func=user_key)
def compare_mechanism(request: Request, body: MechanismRequest,
                      _user_id: str = Depends(require_professional)) -> MechanismResponse:
    """For 1-10 drugs, in request order: the enzymes, transporters and carriers
    DrugBank lists (with the recorded action: substrate / inhibitor / inducer),
    organ-route sentences quoted from the elimination / metabolism / clearance
    text, and for every pair the explanations through a shared human protein
    plus DrugBank's own interaction records between them. Nothing is written;
    no LLM or external source is called."""
    try:
        return service.compare(body.drug_ids)
    except repository.TimingDataUnavailable as exc:
        logger.error("[M-03] mechanism read failed: %s", exc)
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL)
