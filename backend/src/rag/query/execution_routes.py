"""Public HTTP routes for synchronous and streaming query execution."""

import asyncio
from collections.abc import Iterator
from contextlib import suppress
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from ..artifact_jobs.service import ArtifactJobActionError
from ..auth.dependencies import require_csrf, require_current_user
from ..auth.identity_models import IdentityRepository, UserRecord
from ..auth.identity_repository import get_identity_repository
from ..connectors.repositories import (
    ConnectorProfileRepository,
    get_connector_profile_repository,
)
from ..ingestion.folders.dependencies import get_folder_schedule_repository
from ..ingestion.folders.models import FolderScheduleRepository
from .cancellation import (
    QueryCancellationToken,
    QueryCancelled,
    call_with_optional_cancellation,
)
from .chat_history_models import ChatHistoryRequestConflict
from .http import ServiceRequestError
from .query_stream import format_sse
from .route_access import authorize_query_request
from .schemas import QueryRequest, QueryStreamEvent, RAGResponse
from .service import LocalRagService, get_local_rag_service


router = APIRouter()
_STREAM_KEEPALIVE_SECONDS = 15.0


@router.post(
    "",
    responses={
        status.HTTP_200_OK: {"model": RAGResponse},
    },
    summary="Run a retrieval-augmented query",
)
async def run_query(
    payload: QueryRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
    connector_profile_repo: ConnectorProfileRepository = Depends(
        get_connector_profile_repository
    ),
    rag_service: LocalRagService = Depends(get_local_rag_service),
) -> RAGResponse:
    require_csrf(request)
    payload, scoped_user = authorize_query_request(
        payload, request, user, identity_repo, schedule_repo, connector_profile_repo,
    )
    try:
        response = rag_service.answer_query(
            payload,
            scoped_user,
        )
        return response
    except ServiceRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": f"{exc.service}_unavailable",
                "message": f"{exc.service} unavailable: {exc.message}",
            },
        ) from exc
    except ArtifactJobActionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except ChatHistoryRequestConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "query_request_conflict", "message": str(exc)},
        ) from exc


@router.post(
    "/stream",
    response_class=StreamingResponse,
    summary="Run a streaming retrieval-augmented query",
)
async def stream_query(
    payload: QueryRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
    connector_profile_repo: ConnectorProfileRepository = Depends(
        get_connector_profile_repository
    ),
    rag_service: LocalRagService = Depends(get_local_rag_service),
):
    require_csrf(request)
    payload, scoped_user = authorize_query_request(
        payload, request, user, identity_repo, schedule_repo, connector_profile_repo,
    )

    async def stream():
        cancellation_token = QueryCancellationToken()
        iterator = call_with_optional_cancellation(
            rag_service.stream_query,
            cancellation_token,
            payload,
            scoped_user,
        )
        next_task: asyncio.Task[QueryStreamEvent | None] | None = None
        next_task_completed = False
        loop = asyncio.get_running_loop()
        last_sent = loop.time()
        try:
            while True:
                if await request.is_disconnected():
                    cancellation_token.cancel()
                    return

                next_task = asyncio.create_task(
                    asyncio.to_thread(_next_stream_event, iterator)
                )
                while not next_task.done():
                    if await request.is_disconnected():
                        cancellation_token.cancel()
                        with suppress(QueryCancelled, asyncio.CancelledError, TimeoutError):
                            await asyncio.wait_for(asyncio.shield(next_task), timeout=1.0)
                        next_task_completed = next_task.done()
                        return
                    await asyncio.sleep(0.05)
                    if loop.time() - last_sent >= _STREAM_KEEPALIVE_SECONDS:
                        yield ": keepalive\n\n"
                        last_sent = loop.time()
                try:
                    event = await next_task
                finally:
                    next_task_completed = True
                next_task = None
                if event is None:
                    return
                yield format_sse(event)
                last_sent = loop.time()
        except QueryCancelled:
            return
        except asyncio.CancelledError:
            cancellation_token.cancel()
            raise
        except ServiceRequestError as exc:
            yield format_sse(
                QueryStreamEvent(
                    event="error",
                    data={
                        "code": f"{exc.service}_unavailable",
                        "message": f"{exc.service} unavailable: {exc.message}",
                    },
                )
            )
        except ArtifactJobActionError as exc:
            yield format_sse(
                QueryStreamEvent(
                    event="error",
                    data={"code": exc.code, "message": exc.message},
                )
            )
        except ChatHistoryRequestConflict as exc:
            yield format_sse(
                QueryStreamEvent(
                    event="error",
                    data={"code": "query_request_conflict", "message": str(exc)},
                )
            )
        finally:
            cancellation_token.cancel()
            if next_task is not None and not next_task.done():
                next_task.cancel()
                with suppress(asyncio.CancelledError, TimeoutError):
                    await asyncio.wait_for(next_task, timeout=1.0)
            if next_task is None or next_task_completed:
                close = getattr(iterator, "close", None)
                if close is not None:
                    with suppress(Exception):
                        close()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _next_stream_event(
    iterator: Iterator[QueryStreamEvent],
) -> QueryStreamEvent | None:
    try:
        return next(iterator)
    except StopIteration:
        return None
