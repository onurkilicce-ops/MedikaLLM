"""``POST /api/timing/compare`` - read-only, sourced Tmax / half-life view.

Authorisation reuses the existing Bearer scheme (``auth.dependencies.security``)
and token check (``auth.service.verify_token``) and the existing professional
definition (a doctor profile in the database = ``is_doctor``). It does not use
``auth.dependencies.get_current_user`` because that path turns a database
error into "user not found" (401); here a database error is 503.
"""
from __future__ import annotations

from logging import getLogger

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.security import HTTPAuthorizationCredentials

from ..auth.dependencies import security
from ..auth.service import verify_token
from ..middleware.rate_limiter import SEARCH_LIMIT, limiter, user_key
from . import repository, service
from .models import TimingCompareRequest, TimingCompareResponse
from . import advice
from .advice_models import AdviceRequest, AdviceResponse, SearchItem, SearchResponse

logger = getLogger(__name__)

UNAVAILABLE_DETAIL = "Timing data is temporarily unavailable; no result was produced."

router = APIRouter(prefix="/api/timing", tags=["timing"])

_ERROR_RESPONSES = {
    401: {"description": "Missing, invalid or expired Bearer token, or the user no longer exists."},
    403: {"description": "Signed in, but the account has no healthcare-professional (doctor) profile."},
    422: {"description": "Body is not 2-10 distinct DrugBank ids ('DB' + 5 digits), or has extra fields."},
    429: {"description": "Rate limit (shared SEARCH_LIMIT, default 60/minute per user).",
          "content": {"application/json": {"example": {"error": "Rate limit exceeded: 60 per 1 minute"}}}},
    503: {"description": "The database could not be read. Not 'drug not found', not an empty success.",
          "content": {"application/json": {"example": {"detail": UNAVAILABLE_DETAIL}}}},
}


def require_professional(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    try:
        user_id = verify_token(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        is_professional = repository.read_professional_flag(user_id)
    except repository.TimingDataUnavailable as exc:
        logger.error("[M-02] user lookup failed: %s", exc)
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL)
    if is_professional is None:
        raise HTTPException(status_code=401, detail="User not found",
                            headers={"WWW-Authenticate": "Bearer"})
    if not is_professional:
        raise HTTPException(status_code=403, detail="A healthcare-professional account is required")
    return user_id


@router.post("/compare", response_model=TimingCompareResponse, responses=_ERROR_RESPONSES)
@limiter.limit(SEARCH_LIMIT, key_func=user_key)
def compare_timing(
    request: Request,
    body: TimingCompareRequest,
    _user_id: str = Depends(require_professional),
) -> TimingCompareResponse:
    """Sourced Tmax and half-life statements for 2-10 drugs, in request order.

    Each found drug lists its stored source text, the measurements the rules
    could structure (with quote, offsets, conditions and matched references),
    text kept for review, and a separate approx. 5 x half-life object per
    half-life value. Unknown ids are reported per drug (200). Nothing is
    written; no LLM or external source is called. ``timing_advice`` is
    ``not_evaluated`` in this version.
    """
    try:
        return service.compare(body.drug_ids)
    except repository.TimingDataUnavailable as exc:
        logger.error("[M-02] timing read failed: %s", exc)
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL)


@router.get("/drugs", response_model=SearchResponse, responses=_ERROR_RESPONSES)
@limiter.limit(SEARCH_LIMIT, key_func=user_key)
def search_timing_drugs(request: Request, q: str = Query(min_length=2, max_length=100),
                        _user_id: str = Depends(require_professional)) -> SearchResponse:
    if len(q.strip()) < 2:
        raise HTTPException(status_code=422, detail="At least two non-space characters are required")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in q):
        # NUL/control characters would otherwise fail inside the DB driver as a 500
        raise HTTPException(status_code=422, detail="Control characters are not allowed in the search text")
    try:
        rows = repository.search_drugs(q.strip())
        return SearchResponse(items=[SearchItem(drug_id=r.drug_id, name=r.name,
                              profiles=advice.profiles_for(r.name)) for r in rows[:20]], limited=len(rows) > 20)
    except repository.TimingDataUnavailable:
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL)


@router.post("/advice", response_model=AdviceResponse, responses=_ERROR_RESPONSES)
@limiter.limit(SEARCH_LIMIT, key_func=user_key)
def timing_advice(request: Request, body: AdviceRequest,
                  _user_id: str = Depends(require_professional)) -> AdviceResponse:
    try:
        return advice.evaluate(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except repository.TimingDataUnavailable:
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL)
