"""Public HTTP routes for saved query sessions."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.dependencies import require_csrf, require_current_user
from ..auth.identity_models import UserRecord
from .chat_history_models import ChatHistoryRepository, ChatSessionRecord
from .chat_history_repository import get_chat_history_repository
from .route_access import require_query_user
from .schemas import ChatSession, ChatSessionListResponse, ChatSessionSummary


session_list_router = APIRouter()
session_detail_router = APIRouter()


@session_list_router.get(
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
    require_query_user(user)
    sessions = repo.list_sessions(
        user_id=user.id,
        permission_version=user.permission_version,
        limit=limit,
        offset=offset,
    )
    total = repo.count_sessions(
        user_id=user.id,
        permission_version=user.permission_version,
    )
    return ChatSessionListResponse(
        items=[_chat_session_summary_response(session) for session in sessions],
        total=total,
        limit=limit,
        offset=offset,
    )


@session_detail_router.get(
    "/sessions/{session_id}",
    response_model=ChatSession,
    summary="Read a saved chat session",
)
async def get_chat_session(
    session_id: str,
    user: UserRecord = Depends(require_current_user),
    repo: ChatHistoryRepository = Depends(get_chat_history_repository),
) -> ChatSession:
    require_query_user(user)
    session = repo.get_session(
        session_id=session_id,
        user_id=user.id,
        permission_version=user.permission_version,
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "chat_session_not_found",
                "message": "Chat session was not found.",
            },
        )
    return _chat_session_response(session)


@session_detail_router.delete(
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
    require_query_user(user)
    repo.delete_session(
        session_id=session_id,
        user_id=user.id,
        permission_version=user.permission_version,
    )
    return None


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
        question_count=(
            session.question_count
            if session.question_count is not None
            else _question_count(session.turns)
        ),
    )


def _isoformat(value: datetime | None) -> str:
    return (value or datetime.now(UTC)).isoformat()


def _question_count(turns: tuple[dict[str, object], ...]) -> int:
    return sum(1 for turn in turns if turn.get("role") == "user")
