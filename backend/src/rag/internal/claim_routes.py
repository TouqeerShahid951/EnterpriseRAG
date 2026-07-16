from fastapi import APIRouter, Depends, Query

from ..documents.claim_dependencies import get_claim_repository
from ..documents.claim_models import ClaimRepository
from rag.documents.internal_schemas import (
    ClaimsLookupResponse,
    ClaimsIngestResponse,
    ClaimsSaveRequest,
    ClaimsSaveResponse,
    ConflictSaveRequest,
    ConflictSaveResponse,
    ConflictCheckRequest,
    ConflictCheckResponse,
)
from rag.internal.schemas import ServiceTokenContext
from .service_token_auth import require_service_token

router = APIRouter(tags=["internal-claims"])


@router.post("/claims", response_model=ClaimsSaveResponse, summary="Save extracted claims")
async def save_claims(
    payload: ClaimsSaveRequest,
    claim_repo: ClaimRepository = Depends(get_claim_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> ClaimsSaveResponse:
    _ = service
    return ClaimsSaveResponse(saved_count=claim_repo.save_claims(payload.claims))


@router.post("/claims/ingest", response_model=ClaimsIngestResponse, summary="Save extracted claims and create ingest conflicts")
async def save_ingest_claims(
    payload: ClaimsSaveRequest,
    claim_repo: ClaimRepository = Depends(get_claim_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> ClaimsIngestResponse:
    _ = service
    if payload.doc_id:
        result = claim_repo.replace_claims_and_detect_conflicts(payload.doc_id, payload.claims)
    else:
        result = claim_repo.save_claims_and_detect_conflicts(payload.claims)
    return ClaimsIngestResponse(
        saved_count=result.saved_count,
        conflict_count=result.conflict_count,
        conflicted_claim_ids=list(result.conflicted_claim_ids),
    )


@router.get("/claims", response_model=ClaimsLookupResponse, summary="Lookup claims by entity and attribute")
async def lookup_claims(
    entity: str = Query(...),
    attribute: str = Query(...),
    claim_repo: ClaimRepository = Depends(get_claim_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> ClaimsLookupResponse:
    _ = service
    return ClaimsLookupResponse(claims=claim_repo.lookup_claims(entity=entity, attribute=attribute))


@router.post(
    "/claims/check-conflicts",
    response_model=ConflictCheckResponse,
    summary="Check retrieved chunk claims for known conflicts",
)
async def check_claim_conflicts(
    payload: ConflictCheckRequest,
    claim_repo: ClaimRepository = Depends(get_claim_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> ConflictCheckResponse:
    _ = service
    return ConflictCheckResponse(conflicts=claim_repo.check_conflicts(payload.claims))


@router.post("/conflicts", response_model=ConflictSaveResponse, summary="Save detected conflicts")
async def save_conflicts(
    payload: ConflictSaveRequest,
    claim_repo: ClaimRepository = Depends(get_claim_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> ConflictSaveResponse:
    _ = service
    return ConflictSaveResponse(saved_count=claim_repo.save_conflicts(payload.conflicts))
