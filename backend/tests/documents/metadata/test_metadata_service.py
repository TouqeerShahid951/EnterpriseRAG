from __future__ import annotations

from uuid import uuid4

import pytest

from rag.auth.identity_models import UserRecord
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.metadata.ports import DocumentMetadataIndexError
from rag.documents.metadata.service import (
    DocumentMetadataRejected,
    DocumentMetadataService,
)


class RecordingRepository(InMemoryDocumentRepository):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def update_document_clearance(self, document_id: str, clearance_level):
        self.events.append("repository.clearance")
        return super().update_document_clearance(document_id, clearance_level)

    def update_document_topics(
        self,
        document_id: str,
        *,
        topics: list[str],
        llm_topics: list[str],
    ):
        self.events.append("repository.topics")
        return super().update_document_topics(
            document_id,
            topics=topics,
            llm_topics=llm_topics,
        )


class FakeMetadataIndex:
    collection_name = "documents-test"

    def __init__(
        self,
        events: list[str],
        *,
        fail_clearance: bool = False,
        fail_topics: bool = False,
    ) -> None:
        self.events = events
        self.fail_clearance = fail_clearance
        self.fail_topics = fail_topics
        self.clearance_updates: list[tuple[str, str]] = []
        self.topic_updates: list[tuple[str, list[str], list[str]]] = []

    def set_clearance(
        self,
        document_id: str,
        clearance_level: str,
    ) -> None:
        self.events.append("index.clearance")
        self.clearance_updates.append((document_id, clearance_level))
        if self.fail_clearance:
            raise DocumentMetadataIndexError("metadata update failed")

    def set_topics(
        self,
        document_id: str,
        *,
        topics: list[str],
        llm_topics: list[str],
    ) -> None:
        self.events.append("index.topics")
        self.topic_updates.append((document_id, topics, llm_topics))
        if self.fail_topics:
            raise DocumentMetadataIndexError("topic update failed")


def test_tightening_clearance_updates_index_before_repository() -> None:
    service, repo, events, _ = _fixture()
    user = _user(clearance="NATO_SECRET")
    document = _document(repo, user=user)

    updated = service.update_clearance(
        document.id,
        clearance_level="NATO_CONFIDENTIAL",
        actor=user,
    )

    assert events == ["index.clearance", "repository.clearance"]
    assert updated.clearance_level == "NATO_CONFIDENTIAL"
    assert repo.audit_events[-1]["payload"]["action_result"] == "success"


def test_lowering_clearance_updates_repository_before_index() -> None:
    service, repo, events, _ = _fixture()
    user = _user(clearance="NATO_SECRET")
    document = _document(
        repo,
        user=user,
        clearance="NATO_CONFIDENTIAL",
    )

    service.update_clearance(
        document.id,
        clearance_level="NATO_RESTRICTED",
        actor=user,
    )

    assert events == ["repository.clearance", "index.clearance"]


def test_same_clearance_has_no_index_or_audit_side_effects() -> None:
    service, repo, events, index = _fixture()
    user = _user()
    document = _document(repo, user=user)

    unchanged = service.update_clearance(
        document.id,
        clearance_level="NATO_RESTRICTED",
        actor=user,
    )

    assert unchanged.id == document.id
    assert events == []
    assert index.clearance_updates == []
    assert repo.audit_events == []


def test_clearance_above_actor_is_rejected_before_side_effects() -> None:
    service, repo, events, _ = _fixture()
    user = _user()
    document = _document(repo, user=user)

    with pytest.raises(DocumentMetadataRejected) as exc_info:
        service.update_clearance(
            document.id,
            clearance_level="NATO_SECRET",
            actor=user,
        )

    assert exc_info.value.code == "clearance_forbidden"
    assert events == []


def test_topics_are_normalized_indexed_and_audited() -> None:
    service, repo, events, index = _fixture()
    user = _user()
    document = _document(repo, user=user)

    updated = service.update_topics(
        document.id,
        topics=[" OCR ", "ocr", "Handwriting"],
        llm_topics=["LLM Topic"],
        actor=user,
    )

    assert events == ["repository.topics", "index.topics"]
    assert updated.topics == ("OCR", "Handwriting")
    assert index.topic_updates[-1][1:] == (
        ["OCR", "Handwriting"],
        ["LLM Topic"],
    )
    assert repo.audit_events[-1]["payload"]["action_result"] == "success"


def test_topic_index_failure_rolls_back_and_audits_failure() -> None:
    service, repo, _, _ = _fixture(fail_topics=True)
    user = _user()
    document = _document(repo, user=user)
    repo.update_document_topics(
        document.id,
        topics=["Old"],
        llm_topics=["LLM Old"],
    )

    with pytest.raises(DocumentMetadataRejected) as exc_info:
        service.update_topics(
            document.id,
            topics=["New"],
            llm_topics=["LLM New"],
            actor=user,
        )

    current = repo.get_document(document.id)
    assert exc_info.value.code == "document_topics_index_update_failed"
    assert current is not None
    assert current.topics == ("Old",)
    assert current.llm_topics == ("LLM Old",)
    assert repo.audit_events[-1]["payload"]["action_result"] == "failed"


def test_supersede_updates_chain_and_audits() -> None:
    service, repo, _, _ = _fixture()
    user = _user()
    old_document = _document(repo, user=user)
    new_document = _document(repo, user=user)

    chain = service.supersede(
        new_document.id,
        superseded_document_ids=[old_document.id],
        actor=user,
    )

    assert {document.id for document in chain} == {
        old_document.id,
        new_document.id,
    }
    assert repo.get_document(old_document.id).is_current is False  # type: ignore[union-attr]
    assert repo.audit_events[-1]["event_type"] == "documents.supersede"


def test_self_supersession_maps_repository_validation_error() -> None:
    service, repo, _, _ = _fixture()
    user = _user()
    document = _document(repo, user=user)

    with pytest.raises(DocumentMetadataRejected) as exc_info:
        service.supersede(
            document.id,
            superseded_document_ids=[document.id],
            actor=user,
        )

    assert exc_info.value.category == "bad_request"
    assert exc_info.value.code == "invalid_supersession"


def _fixture(*, fail_topics: bool = False):
    events: list[str] = []
    repo = RecordingRepository(events)
    index = FakeMetadataIndex(events, fail_topics=fail_topics)
    return (
        DocumentMetadataService(document_repo=repo, index=index),
        repo,
        events,
        index,
    )


def _document(
    repo: InMemoryDocumentRepository,
    *,
    user: UserRecord,
    clearance: str = "NATO_RESTRICTED",
):
    return repo.create_document(
        title="Document.pdf",
        source_id=f"upload:{uuid4()}",
        group_path="/ops",
        clearance_level=clearance,
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


def _user(*, clearance: str = "NATO_RESTRICTED") -> UserRecord:
    user_id = str(uuid4())
    return UserRecord(
        id=user_id,
        email=f"{user_id}@example.test",
        name="Test User",
        password_hash="hash",
        is_active=True,
        account_type="contributor",
        clearance_level=clearance,  # type: ignore[arg-type]
        must_change_password=False,
        permission_version=1,
        group_paths=("/ops",),
    )
