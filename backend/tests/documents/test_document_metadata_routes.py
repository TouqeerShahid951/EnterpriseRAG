from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from rag.documents import routes as document_routes
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.schemas.docs import DocumentClearanceUpdateRequest, DocumentTopicsUpdateRequest

from document_route_characterization_support import (
    FakeQdrant,
    _csrf_request,
    _document,
    _metadata_service,
    _user,
)


def test_clearance_update_persists_indexes_and_audits_success() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor", clearance="NATO_SECRET")
    document = _document(repo, user=user)
    qdrant = FakeQdrant()

    response = asyncio.run(
        document_routes.update_document_clearance(
            document.id,
            DocumentClearanceUpdateRequest(clearance_level="NATO_CONFIDENTIAL"),
            _csrf_request("PATCH"),
            user=user,
            service=_metadata_service(repo, qdrant),
        )
    )

    assert response.clearance_level == "NATO_CONFIDENTIAL"
    assert repo.get_document(document.id).clearance_level == "NATO_CONFIDENTIAL"  # type: ignore[union-attr]
    assert qdrant.clearance_updates == [(document.id, "NATO_CONFIDENTIAL", 2)]
    assert repo.audit_events[-1]["payload"]["action_result"] == "success"


def test_same_clearance_is_idempotent_without_index_or_audit_side_effects() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)
    qdrant = FakeQdrant()

    response = asyncio.run(
        document_routes.update_document_clearance(
            document.id,
            DocumentClearanceUpdateRequest(clearance_level="NATO_RESTRICTED"),
            _csrf_request("PATCH"),
            user=user,
            service=_metadata_service(repo, qdrant),
        )
    )

    assert response.clearance_level == "NATO_RESTRICTED"
    assert qdrant.clearance_updates == []
    assert repo.audit_events == []


def test_topic_index_failure_rolls_back_metadata_and_audits_failure() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)
    repo.update_document_topics(document.id, topics=["Old"], llm_topics=["LLM Old"])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_routes.update_document_topics(
                document.id,
                DocumentTopicsUpdateRequest(topics=["New"], llm_topics=["LLM New"]),
                _csrf_request("PATCH"),
                user=user,
                service=_metadata_service(
                    repo,
                    FakeQdrant(fail_topics=True),
                ),
            )
        )

    current = repo.get_document(document.id)
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "document_topics_index_update_failed"
    assert current is not None
    assert current.topics == ("Old",)
    assert current.llm_topics == ("LLM Old",)
    assert repo.audit_events[-1]["payload"]["action_result"] == "failed"


def test_metadata_update_rejects_non_writer_before_external_calls() -> None:
    repo = InMemoryDocumentRepository()
    owner = _user("contributor")
    member = _user("member")
    document = _document(repo, user=owner)
    qdrant = FakeQdrant()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_routes.update_document_topics(
                document.id,
                DocumentTopicsUpdateRequest(topics=["New"]),
                _csrf_request("PATCH"),
                user=member,
                service=_metadata_service(repo, qdrant),
            )
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "document_forbidden"
    assert qdrant.topic_updates == []
