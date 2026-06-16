"""Public admin APIs for RAG evaluation datasets and runs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ...auth.abac import normalize_group_path
from ...auth.context import UserContext
from ...auth.dependencies import require_platform_admin_user
from ...repositories.identity import IdentityRepository, UserRecord, get_identity_repository
from ...schemas.evaluations import (
    EvaluationDatasetDetail,
    EvaluationDatasetImportRequest,
    EvaluationDatasetListResponse,
    EvaluationRunCreateRequest,
    EvaluationRunDetail,
    EvaluationRunListResponse,
    EvaluationRunMutationResponse,
    EvaluationRunSummary,
)
from ...evaluations.service import EvaluationActionError, EvaluationService, get_evaluation_service


router = APIRouter(prefix="/rag-evaluations", tags=["rag-evaluations"])


@router.get("/datasets", response_model=EvaluationDatasetListResponse, summary="List RAG evaluation datasets")
def list_evaluation_datasets(
    user: UserRecord = Depends(require_platform_admin_user),
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationDatasetListResponse:
    _ = user
    items = service.list_datasets()
    return EvaluationDatasetListResponse(items=items, total=len(items))


@router.post("/datasets", response_model=EvaluationDatasetDetail, summary="Import a RAG evaluation dataset")
def import_evaluation_dataset(
    payload: EvaluationDatasetImportRequest,
    user: UserRecord = Depends(require_platform_admin_user),
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationDatasetDetail:
    try:
        return service.import_dataset(
            content=payload.content,
            source_format=payload.source_format,
            name=payload.name,
            user_id=user.id,
        )
    except EvaluationActionError as exc:
        raise _http_error(exc) from exc


@router.get("/datasets/{dataset_id}", response_model=EvaluationDatasetDetail, summary="Read a RAG evaluation dataset")
def get_evaluation_dataset(
    dataset_id: str,
    user: UserRecord = Depends(require_platform_admin_user),
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationDatasetDetail:
    _ = user
    try:
        return service.get_dataset(dataset_id)
    except EvaluationActionError as exc:
        raise _http_error(exc) from exc


@router.get("/runs", response_model=EvaluationRunListResponse, summary="List RAG evaluation runs")
def list_evaluation_runs(
    user: UserRecord = Depends(require_platform_admin_user),
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationRunListResponse:
    _ = user
    items = service.list_runs()
    return EvaluationRunListResponse(items=items, total=len(items))


@router.post("/runs", response_model=EvaluationRunSummary, summary="Launch a RAG evaluation run")
def create_evaluation_run(
    payload: EvaluationRunCreateRequest,
    user: UserRecord = Depends(require_platform_admin_user),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationRunSummary:
    try:
        group_path = _validated_group_path(payload.group_path, identity_repo)
        return service.submit_run(
            dataset_id=payload.dataset_id,
            user=_admin_context(user, identity_repo),
            group_path=group_path,
            document_ids=payload.document_ids,
            case_ids=payload.case_ids,
            limit=payload.limit,
        )
    except EvaluationActionError as exc:
        raise _http_error(exc) from exc


@router.get("/runs/{run_id}", response_model=EvaluationRunDetail, summary="Read a RAG evaluation run")
def get_evaluation_run(
    run_id: str,
    user: UserRecord = Depends(require_platform_admin_user),
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationRunDetail:
    _ = user
    try:
        return service.get_run(run_id)
    except EvaluationActionError as exc:
        raise _http_error(exc) from exc


@router.post("/runs/{run_id}/cancel", response_model=EvaluationRunMutationResponse, summary="Cancel a RAG evaluation run")
def cancel_evaluation_run(
    run_id: str,
    user: UserRecord = Depends(require_platform_admin_user),
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationRunMutationResponse:
    _ = user
    try:
        return EvaluationRunMutationResponse(run=service.cancel(run_id))
    except EvaluationActionError as exc:
        raise _http_error(exc) from exc


@router.post("/runs/{run_id}/retry", response_model=EvaluationRunMutationResponse, summary="Retry a RAG evaluation run")
def retry_evaluation_run(
    run_id: str,
    user: UserRecord = Depends(require_platform_admin_user),
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationRunMutationResponse:
    _ = user
    try:
        return EvaluationRunMutationResponse(run=service.retry(run_id))
    except EvaluationActionError as exc:
        raise _http_error(exc) from exc


def _validated_group_path(group_path: str | None, repo: IdentityRepository) -> str | None:
    if group_path is None:
        return None
    try:
        normalized = normalize_group_path(group_path)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_evaluation_group", "message": "Evaluation Knowledge Space is invalid."},
        ) from exc
    known_groups = {group.path for group in repo.list_groups()}
    if normalized not in known_groups:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "evaluation_group_not_found", "message": "Evaluation Knowledge Space does not exist."},
        )
    return normalized


def _admin_context(user: UserRecord, repo: IdentityRepository) -> UserContext:
    return UserContext(
        user_id=user.id,
        email=user.email,
        account_type=user.account_type,
        group_paths=tuple(group.path for group in repo.list_groups()),
        clearance_level=user.clearance_level,
        permission_version=user.permission_version,
    )


def _http_error(exc: EvaluationActionError) -> HTTPException:
    response_status = status.HTTP_404_NOT_FOUND if exc.code.endswith("_not_found") else status.HTTP_400_BAD_REQUEST
    if exc.code in {"evaluation_run_not_retryable", "evaluation_retry_exhausted"}:
        response_status = status.HTTP_409_CONFLICT
    return HTTPException(status_code=response_status, detail={"code": exc.code, "message": exc.message})
