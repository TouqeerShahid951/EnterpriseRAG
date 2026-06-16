"""Public chat history repository dependency."""

from __future__ import annotations

from functools import lru_cache

from ..core.config import settings
from .chat_history_memory import InMemoryChatHistoryRepository
from .chat_history_models import ChatHistoryRepository, ChatSessionRecord
from .chat_history_postgres import PostgresChatHistoryRepository


@lru_cache
def default_chat_history_repository() -> ChatHistoryRepository:
    if settings.document_repository == "memory":
        return InMemoryChatHistoryRepository()
    return PostgresChatHistoryRepository(settings.database_url)


def get_chat_history_repository() -> ChatHistoryRepository:
    return default_chat_history_repository()


__all__ = [
    "ChatHistoryRepository",
    "ChatSessionRecord",
    "InMemoryChatHistoryRepository",
    "PostgresChatHistoryRepository",
    "get_chat_history_repository",
]
