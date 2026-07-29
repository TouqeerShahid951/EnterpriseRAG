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
from .route_access import (
    query_request_for_user,
    user_context,
    validate_query_source_for_user,
)
from .schemas import QueryRequest, QueryStreamEvent, RAGResponse
from .service import LocalRagService, get_local_rag_service


router = APIRouter()


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
    payload = query_request_for_user(payload, user, identity_repo)
    validate_query_source_for_user(
        payload,
        user_context(user, identity_repo),
        schedule_repo,
        connector_profile_repo,
    )
    try:
        response = rag_service.answer_query(
            payload,
            user_context(user, identity_repo),
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
    payload = query_request_for_user(payload, user, identity_repo)
    scoped_user = user_context(user, identity_repo)
    validate_query_source_for_user(
        payload,
        scoped_user,
        schedule_repo,
        connector_profile_repo,
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
        try:
            while True:
                if await request.is_disconnected():
                    cancellation_token.cancel()
                    return

                next_task = asyncio.create_task(
                    asyncio.to_thread(_next_stream_event, iterator)
                )
                event = await next_task
                next_task = None
                if event is None:
                    return
                yield format_sse(event)
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
            if next_task is None or next_task.done():
                close = getattr(iterator, "close", None)
                if close is not None:
                    with suppress(Exception):
                        close()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
    )


def _next_stream_event(
    iterator: Iterator[QueryStreamEvent],
) -> QueryStreamEvent | None:
    try:
        return next(iterator)
    except StopIteration:
        return None
