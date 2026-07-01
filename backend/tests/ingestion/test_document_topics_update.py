from __future__ import annotations

import asyncio
from uuid import uuid4

from fastapi import Request

from rag.api.routes import document_routes
from rag.core.config import settings
from rag.repositories.document_memory import InMemoryDocumentRepository
from rag.repositories.identity import UserRecord
from rag.schemas.docs import DocumentTopicsUpdateRequest


class FakeQdrant:
    def __init__(self) -> None:
        self.topic_updates: list[tuple[str, list[str]]] = []

    def set_document_topics(self, doc_id: str, *, topics: list[str]) -> None:
        self.topic_updates.append((doc_id, topics))


def test_update_document_topics_persists_curated_topics_and_syncs_qdrant() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=user)
    repo.update_document_topics(document.id, topics=["Old"], llm_topics=["LLM Old"])
    qdrant = FakeQdrant()

    response = asyncio.run(
        document_routes.update_document_topics(
            document.id,
            DocumentTopicsUpdateRequest(topics=["OCR", "ocr", "Handwriting"], llm_topics=[]),
            _csrf_request(),
            user=user,
            repo=repo,
            qdrant=qdrant,  # type: ignore[arg-type]
        )
    )

    assert response.topics == ["OCR", "Handwriting"]
    assert response.llm_topics == []
    assert qdrant.topic_updates == [(document.id, ["OCR", "Handwriting"])]
    assert repo.audit_events[-1]["event_type"] == "documents.topics_update"
    assert repo.audit_events[-1]["payload"]["old_llm_topics"] == ["LLM Old"]


def _csrf_request() -> Request:
    token = "csrf-test-token"
    return Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": "/",
            "headers": [
                (b"cookie", f"{settings.csrf_cookie_name}={token}".encode("ascii")),
                (b"x-csrf-token", token.encode("ascii")),
            ],
        }
    )


def _document(repo: InMemoryDocumentRepository, *, user: UserRecord):
    return repo.create_document(
        title="Document.pdf",
        source_id=f"upload:{uuid4()}",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type=None,
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by=user.id,
        file_path="memory://document.pdf",
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status="complete",
    )


def _user(account_type: str, *, group_paths: tuple[str, ...]) -> UserRecord:
    return UserRecord(
        id=str(uuid4()),
        email=f"{uuid4()}@example.test",
        name="Test User",
        password_hash="hash",
        is_active=True,
        account_type=account_type,  # type: ignore[arg-type]
        clearance_level="NATO_RESTRICTED",
        must_change_password=False,
        permission_version=1,
        group_paths=group_paths,
    )
