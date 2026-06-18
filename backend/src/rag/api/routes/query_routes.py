import asyncio
from collections.abc import Iterator
from contextlib import suppress
from datetime import UTC, datetime
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from ...auth.abac import normalize_group_path
from ...auth.context import UserContext
from ...auth.dependencies import require_csrf, require_current_user
from ...auth.permissions import can_query, has_exact_group_scope, is_global_admin
from ...repositories.identity import IdentityRepository, UserRecord, get_identity_repository
from ...repositories.chat_history import ChatHistoryRepository, get_chat_history_repository
from ...repositories.chat_history_models import ChatSessionRecord
from ...repositories.documents import DocumentRepository, get_document_repository
from ...repositories.generated_artifacts import GeneratedArtifactRepository, get_generated_artifact_repository
from ...query.cancellation import QueryCancellationToken, QueryCancelled, call_with_optional_cancellation
from ...query.http import ServiceRequestError
from ...query.service import LocalRagService, get_local_rag_service
from ...query.query_stream import format_sse
from ...schemas.query import ChatSession, ChatSessionListResponse, ChatSessionSummary, QueryRequest, QueryStreamEvent, RAGResponse
from ...services.generated_artifact_storage import GeneratedArtifactStorage, get_generated_artifact_storage

router = APIRouter(prefix="/query", tags=["query"])


@router.get(
    "/artifacts/{artifact_id}/content",
    summary="Download a generated query artifact",
)
async def get_generated_artifact_content(
    artifact_id: str,
    user: UserRecord = Depends(require_current_user),
    artifact_repo: GeneratedArtifactRepository = Depends(get_generated_artifact_repository),
    artifact_storage: GeneratedArtifactStorage = Depends(get_generated_artifact_storage),
    audit_repo: DocumentRepository = Depends(get_document_repository),
) -> StreamingResponse:
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None or artifact.user_id != user.id or artifact.permission_version != user.permission_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "artifact_not_found", "message": "Generated artifact was not found."},
        )
    try:
        stored = artifact_storage.read(artifact.object_path)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "artifact_file_not_found", "message": "Generated artifact file was not found."},
        ) from exc
    audit_repo.append_audit_event(
        event_type="query.artifact_downloaded",
        actor_id=user.id,
        target_type="generated_artifact",
        target_id=artifact.id,
        payload={
            "session_id": artifact.session_id,
            "trace_id": artifact.trace_id,
            "format": artifact.format,
            "filename": artifact.filename,
        },
    )
    filename = artifact.filename or stored.filename
    return StreamingResponse(
        iter([stored.content]),
        media_type=artifact.content_type or stored.content_type,
        headers={
            "Content-Disposition": _attachment_content_disposition(filename),
            "Content-Length": str(len(stored.content)),
        },
    )


@router.get(
    "/sessions",
    response_model=ChatSessionListResponse,
    summary="List saved chat sessions for the current permission version",
)
async def list_chat_sessions(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: UserRecord = Depends(require_current_user),
    repo: ChatHistoryRepository = Depends(get_chat_history_repository),
) -> ChatSessionListResponse:
    _require_query_user(user)
    sessions = repo.list_sessions(user_id=user.id, permission_version=user.permission_version, limit=limit, offset=offset)
    total = repo.count_sessions(user_id=user.id, permission_version=user.permission_version)
    return ChatSessionListResponse(
        items=[_chat_session_summary_response(session) for session in sessions],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSession,
    summary="Read a saved chat session",
)
async def get_chat_session(
    session_id: str,
    user: UserRecord = Depends(require_current_user),
    repo: ChatHistoryRepository = Depends(get_chat_history_repository),
) -> ChatSession:
    _require_query_user(user)
    session = repo.get_session(session_id=session_id, user_id=user.id, permission_version=user.permission_version)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "chat_session_not_found", "message": "Chat session was not found."},
        )
    return _chat_session_response(session)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved chat session",
)
async def delete_chat_session(
    session_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    repo: ChatHistoryRepository = Depends(get_chat_history_repository),
) -> None:
    require_csrf(request)
    _require_query_user(user)
    repo.delete_session(session_id=session_id, user_id=user.id, permission_version=user.permission_version)
    return None


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
    chat_history_repo: ChatHistoryRepository = Depends(get_chat_history_repository),
    rag_service: LocalRagService = Depends(get_local_rag_service),
) -> RAGResponse:
    require_csrf(request)
    payload = _query_request_for_user(payload, user, identity_repo)
    try:
        response = rag_service.answer_query(payload, _user_context(user, identity_repo))
        _save_completed_query(chat_history_repo, user=user, payload=payload, response=response)
        return response
    except ServiceRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": f"{exc.service}_unavailable", "message": f"{exc.service} unavailable: {exc.message}"},
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
    chat_history_repo: ChatHistoryRepository = Depends(get_chat_history_repository),
    rag_service: LocalRagService = Depends(get_local_rag_service),
):
    require_csrf(request)
    payload = _query_request_for_user(payload, user, identity_repo)
    user_context = _user_context(user, identity_repo)

    async def stream():
        cancellation_token = QueryCancellationToken()
        iterator = call_with_optional_cancellation(
            rag_service.stream_query,
            cancellation_token,
            payload,
            user_context,
        )
        next_task: asyncio.Task[QueryStreamEvent | None] | None = None
        try:
            while True:
                if await request.is_disconnected():
                    cancellation_token.cancel()
                    return

                next_task = asyncio.create_task(asyncio.to_thread(_next_stream_event, iterator))
                event = await next_task
                next_task = None
                if event is None:
                    return
                if event.event == "done":
                    response = RAGResponse.model_validate(event.data)
                    _save_completed_query(chat_history_repo, user=user, payload=payload, response=response)
                elif event.event == "verified":
                    response = RAGResponse.model_validate(event.data)
                    chat_history_repo.update_assistant_response(
                        user_id=user.id,
                        permission_version=user.permission_version,
                        session_id=response.session_id,
                        trace_id=response.trace_id,
                        response=response.model_dump(mode="json"),
                    )
                yield format_sse(event)
        except QueryCancelled:
            return
        except asyncio.CancelledError:
            cancellation_token.cancel()
            raise
        except ServiceRequestError as exc:
            yield format_sse(QueryStreamEvent(
                event="error",
                data={"code": f"{exc.service}_unavailable", "message": f"{exc.service} unavailable: {exc.message}"},
            ))
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


def _next_stream_event(iterator: Iterator[QueryStreamEvent]) -> QueryStreamEvent | None:
    try:
        return next(iterator)
    except StopIteration:
        return None


def _attachment_content_disposition(filename: str) -> str:
    safe_name = filename.replace('"', "'")
    encoded = quote(filename)
    return f'attachment; filename="{safe_name}"; filename*=UTF-8\'\'{encoded}'


def _query_request_for_user(payload: QueryRequest, user: UserRecord, repo: IdentityRepository) -> QueryRequest:
    _require_query_user(user)
    group_path = _validated_query_group_path(payload.group_path, user, repo)
    if group_path == payload.group_path:
        return payload
    return payload.model_copy(update={"group_path": group_path})


def _validated_query_group_path(group_path: str | None, user: UserRecord, repo: IdentityRepository) -> str | None:
    if group_path is None:
        return None
    try:
        normalized = normalize_group_path(group_path)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_query_group", "message": "Query Knowledge Space is invalid."},
        ) from exc
    if is_global_admin(user):
        known_groups = {group.path for group in repo.list_groups()}
        if normalized in known_groups:
            return normalized
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "query_group_not_found", "message": "Query Knowledge Space does not exist."},
        )
    if not has_exact_group_scope(user, normalized):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "query_group_forbidden", "message": "User cannot query this Knowledge Space."},
        )
    return normalized


def _user_context(user: UserRecord, repo: IdentityRepository) -> UserContext:
    group_paths = tuple(group.path for group in repo.list_groups()) if is_global_admin(user) else user.group_paths
    return UserContext(
        user_id=user.id,
        email=user.email,
        account_type=user.account_type,
        group_paths=group_paths,
        clearance_level=user.clearance_level,
        permission_version=user.permission_version,
    )


def _require_query_user(user: UserRecord) -> None:
    if not can_query(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "query_role_forbidden", "message": "User account type cannot query Knowledge Spaces."},
        )


def _save_completed_query(
    repo: ChatHistoryRepository,
    *,
    user: UserRecord,
    payload: QueryRequest,
    response: RAGResponse,
) -> None:
    created_at = _isoformat(datetime.now(UTC))
    question = payload.query.strip()
    user_turn = {
        "id": f"user-{uuid4()}",
        "role": "user",
        "content": question,
        "createdAt": created_at,
    }
    assistant_turn = {
        "id": f"assistant-{uuid4()}",
        "role": "assistant",
        "status": "complete",
        "question": question,
        "createdAt": created_at,
        "groupPath": payload.group_path,
        "documentIds": payload.document_ids,
        "progress": [],
        "response": response.model_dump(mode="json"),
    }
    repo.append_completed_turn(
        user_id=user.id,
        permission_version=user.permission_version,
        session_id=response.session_id,
        title=_compact_session_title(question),
        user_turn=user_turn,
        assistant_turn=assistant_turn,
    )


def _chat_session_response(session: ChatSessionRecord) -> ChatSession:
    return ChatSession(
        id=session.id,
        title=session.title,
        created_at=_isoformat(session.created_at),
        updated_at=_isoformat(session.updated_at),
        turns=list(session.turns),
    )


def _chat_session_summary_response(session: ChatSessionRecord) -> ChatSessionSummary:
    return ChatSessionSummary(
        id=session.id,
        title=session.title,
        created_at=_isoformat(session.created_at),
        updated_at=_isoformat(session.updated_at),
        question_count=session.question_count if session.question_count is not None else _question_count(session.turns),
    )


def _isoformat(value: datetime | None) -> str:
    return (value or datetime.now(UTC)).isoformat()


def _compact_session_title(value: str) -> str:
    return f"{value[:49].rstrip()}..." if len(value) > 52 else value


def _question_count(turns: tuple[dict[str, object], ...]) -> int:
    return sum(1 for turn in turns if turn.get("role") == "user")
