"""Platform-admin streaming route for live retrieval-stage inspection."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import suppress

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from rag.artifact_jobs.service import ArtifactJobActionError
from rag.auth.dependencies import require_platform_admin_user
from rag.auth.identity_models import IdentityRepository, UserRecord
from rag.auth.identity_repository import get_identity_repository
from rag.connectors.repositories import ConnectorProfileRepository, get_connector_profile_repository
from rag.ingestion.folders.dependencies import get_folder_schedule_repository
from rag.ingestion.folders.models import FolderScheduleRepository
from rag.query.cancellation import QueryCancellationToken, QueryCancelled, call_with_optional_cancellation
from rag.query.chat_history_models import ChatHistoryRequestConflict
from rag.query.http import ServiceRequestError
from rag.query.query_stream import format_sse
from rag.query.route_access import authorize_query_request
from rag.query.schemas import QueryRequest, QueryStreamEvent
from rag.query.service import LocalRagService, get_local_rag_service


router = APIRouter()


@router.post(
    "/query-tracker/stream",
    response_class=StreamingResponse,
    summary="Run a query with live retrieval-stage diagnostics",
)
async def stream_query_tracker(
    payload: QueryRequest,
    request: Request,
    user: UserRecord = Depends(require_platform_admin_user),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
    connector_profile_repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
    rag_service: LocalRagService = Depends(get_local_rag_service),
) -> StreamingResponse:
    payload, scoped_user = authorize_query_request(
        payload, request, user, identity_repo, schedule_repo, connector_profile_repo,
        origin="query_tracker",
    )

    async def stream():
        cancellation_token = QueryCancellationToken()
        iterator = call_with_optional_cancellation(
            rag_service.stream_query,
            cancellation_token,
            payload,
            scoped_user,
            capture_retrieval_trace=True,
            analytics_origin="query_tracker",
        )
        next_task: asyncio.Task[QueryStreamEvent | None] | None = None
        try:
            while True:
                if await request.is_disconnected():
                    return
                next_task = asyncio.create_task(asyncio.to_thread(_next_event, iterator))
                event = await next_task
                next_task = None
                if event is None:
                    return
                yield format_sse(event)
        except QueryCancelled:
            return
        except asyncio.CancelledError:
            raise
        except ServiceRequestError as exc:
            yield _error_event(f"{exc.service}_unavailable", f"{exc.service} unavailable: {exc.message}")
        except ArtifactJobActionError as exc:
            yield _error_event(exc.code, exc.message)
        except ChatHistoryRequestConflict as exc:
            yield _error_event("query_request_conflict", str(exc))
        finally:
            cancellation_token.cancel()
            if next_task is not None and not next_task.done():
                next_task.cancel()
                with suppress(asyncio.CancelledError, TimeoutError):
                    await asyncio.wait_for(next_task, timeout=1.0)
            close = getattr(iterator, "close", None)
            if close is not None and (next_task is None or next_task.done()):
                with suppress(Exception):
                    close()

    return StreamingResponse(stream(), media_type="text/event-stream")


def _next_event(iterator: Iterator[QueryStreamEvent]) -> QueryStreamEvent | None:
    try:
        return next(iterator)
    except StopIteration:
        return None


def _error_event(code: str, message: str) -> str:
    return format_sse(QueryStreamEvent(event="error", data={"code": code, "message": message}))
