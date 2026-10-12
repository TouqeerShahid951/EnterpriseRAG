"""Platform-admin query analytics routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from ...auth.dependencies import require_platform_admin_user
from ...auth.identity_models import UserRecord
from ...shared.contracts.group_paths import normalize_group_path
from .models import (
    AnalyticsBucketSize,
    AnalyticsExecutionRepository,
    AnalyticsFilters,
    AnalyticsOrigin,
    AnalyticsOutcome,
    AnalyticsWorkKind,
)
from .repository import get_analytics_repository
from .schemas import (
    AnalyticsExecutionListResponse,
    AnalyticsExecutionResponse,
    AnalyticsDiagnosticsResponse,
    AnalyticsSeriesResponse,
    AnalyticsSummaryResponse,
    execution_response,
    execution_list_response,
    diagnostics_response,
    series_response,
    summary_response,
)

router = APIRouter(prefix="/admin/query-analytics", tags=["query-analytics"])
MAX_WINDOW = timedelta(days=30)


@router.get("/summary", response_model=AnalyticsSummaryResponse, summary="Summarize query execution analytics")
def summarize_query_analytics(
    filters: Annotated[AnalyticsFilters, Depends(_analytics_filters)],
    user: UserRecord = Depends(require_platform_admin_user),
    repository: AnalyticsExecutionRepository = Depends(get_analytics_repository),
) -> AnalyticsSummaryResponse:
    _ = user
    return summary_response(
        repository.summarize_executions(filters=filters),
        created_from=filters.created_from,
        created_to=filters.created_to,
        as_of=filters.as_of or datetime.now(UTC),
    )


@router.get("/executions", response_model=AnalyticsExecutionListResponse, summary="List query execution analytics")
def list_query_analytics(
    filters: Annotated[AnalyticsFilters, Depends(_analytics_filters)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: UserRecord = Depends(require_platform_admin_user),
    repository: AnalyticsExecutionRepository = Depends(get_analytics_repository),
) -> AnalyticsExecutionListResponse:
    _ = user
    page = repository.list_executions(filters=filters, limit=limit, offset=offset)
    return AnalyticsExecutionListResponse(
        items=[execution_list_response(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
        created_from=filters.created_from,
        created_to=filters.created_to,
        as_of=filters.as_of or datetime.now(UTC),
    )


@router.get("/series", response_model=AnalyticsSeriesResponse, summary="Build query analytics time series")
def series_query_analytics(
    filters: Annotated[AnalyticsFilters, Depends(_analytics_filters)],
    user: UserRecord = Depends(require_platform_admin_user),
    repository: AnalyticsExecutionRepository = Depends(get_analytics_repository),
) -> AnalyticsSeriesResponse:
    _ = user
    bucket_size: AnalyticsBucketSize = "hour" if filters.created_to - filters.created_from <= timedelta(days=2) else "day"
    return series_response(
        repository.series_executions(filters=filters, bucket_size=bucket_size),
        created_from=filters.created_from,
        created_to=filters.created_to,
        as_of=filters.as_of or datetime.now(UTC),
    )


@router.get("/diagnostics", response_model=AnalyticsDiagnosticsResponse, summary="Summarize retained retrieval and performance diagnostics")
def diagnostics_query_analytics(
    filters: Annotated[AnalyticsFilters, Depends(_analytics_filters)],
    user: UserRecord = Depends(require_platform_admin_user),
    repository: AnalyticsExecutionRepository = Depends(get_analytics_repository),
) -> AnalyticsDiagnosticsResponse:
    _ = user
    return diagnostics_response(repository.diagnose_executions(filters=filters))


@router.get("/executions/{execution_id}", response_model=AnalyticsExecutionResponse, summary="Get one query execution analytics record")
def get_query_analytics_execution(
    execution_id: str,
    user: UserRecord = Depends(require_platform_admin_user),
    repository: AnalyticsExecutionRepository = Depends(get_analytics_repository),
) -> AnalyticsExecutionResponse:
    _ = user
    record = repository.get_execution(execution_id)
    if record is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "query_analytics_execution_not_found", "message": "Query execution analytics record was not found."},
        )
    return execution_response(record)


def _analytics_filters(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    origin: AnalyticsOrigin | Literal["all"] = Query(default="chat"),
    work_kind: AnalyticsWorkKind | Literal["all"] = Query(default="answer"),
    as_of: datetime | None = Query(default=None),
    user_id: str | None = Query(default=None, min_length=1, max_length=120),
    group_path: str | None = Query(default=None, min_length=1, max_length=240),
    outcome: AnalyticsOutcome | None = Query(default=None),
    source_mode: str | None = Query(default=None, min_length=1, max_length=40),
    intent: str | None = Query(default=None, min_length=1, max_length=80),
    model_cohort: str | None = Query(default=None, min_length=1, max_length=80),
    configuration_digest: str | None = Query(default=None, min_length=1, max_length=80),
) -> AnalyticsFilters:
    now = datetime.now(UTC)
    created_to = _aware(to or now)
    created_from = _aware(from_ or created_to - timedelta(days=7))
    if created_from >= created_to:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_analytics_window", "message": "Analytics window must have from before to."})
    if created_to - created_from > MAX_WINDOW:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "analytics_window_too_large", "message": "Analytics window cannot exceed 30 days."})
    normalized_group = None
    if group_path:
        try:
            normalized_group = normalize_group_path(group_path)
        except ValueError as exc:
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_analytics_group", "message": "Analytics Knowledge Space is invalid."}) from exc
    return AnalyticsFilters(
        created_from=created_from,
        created_to=created_to,
        origin=None if origin == "all" else origin,
        work_kind=None if work_kind == "all" else work_kind,
        as_of=min(_aware(as_of), now) if as_of is not None else now,
        actor_id=user_id,
        group_path=normalized_group,
        outcome=outcome,
        source_mode=source_mode,
        intent=intent,
        model_cohort=model_cohort.strip() if model_cohort else None,
        configuration_digest=configuration_digest.strip() if configuration_digest else None,
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
