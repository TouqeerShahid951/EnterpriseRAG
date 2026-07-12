from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request

from rag.api.routes import document_routes
from rag.core.config import settings
from rag.graphrag.cleanup import GraphRAGCleanupResult
from rag.query.http import ServiceRequestError
from rag.repositories.document_memory import InMemoryDocumentRepository
from rag.repositories.identity import InMemoryIdentityRepository, UserRecord
from rag.repositories.ingest_config import InMemoryIngestConfigRepository
from rag.schemas.docs import DocumentOwnerUpdateRequest
from rag.services.graphrag_queue import InMemoryGraphRAGMaintenanceQueue


class FakeQdrant:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.access_updates: list[tuple[str, str, list[str]]] = []

    def set_document_access_scope(self, doc_id: str, *, group_path: str, acl_group_paths: list[str]) -> None:
        if self.fail:
            raise ServiceRequestError("qdrant", "metadata update failed", 502)
        self.access_updates.append((doc_id, group_path, acl_group_paths))


class FakeGraphRAGDeletionService:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    def delete_document(self, *, doc_id: str, partition_key: str) -> GraphRAGCleanupResult:
        self.deleted.append((doc_id, partition_key))
        return GraphRAGCleanupResult(status="complete", doc_id=doc_id, partition_key=partition_key)


def test_global_admin_transfers_owner_and_keeps_old_owner_shared() -> None:
    repo = InMemoryDocumentRepository()
    identity_repo = _identity_repo("/legal", "/finance", "/ops")
    admin = _user("platform_admin", group_paths=())
    document = _document(repo, user=admin, group_path="/legal")
    repo.replace_document_shares(document.id, group_paths=["/finance", "/ops"], actor_id=admin.id)
    qdrant = FakeQdrant()

    response = _transfer(document.id, "/finance", user=admin, repo=repo, identity_repo=identity_repo, qdrant=qdrant)

    assert response.id == document.id
    assert response.owner_group_path == "/finance"
    assert response.shared_group_paths == ["/legal", "/ops"]
    assert response.uploaded_by == admin.id
    assert response.clearance_level == "NATO_RESTRICTED"
    assert qdrant.access_updates == [(document.id, "/finance", ["/finance", "/legal", "/ops"])]
    assert repo.audit_events[-1]["event_type"] == "documents.owner.transfer"
    assert repo.audit_events[-1]["payload"]["action_result"] == "success"


def test_space_admin_can_transfer_when_both_spaces_are_managed() -> None:
    repo = InMemoryDocumentRepository()
    identity_repo = _identity_repo("/legal", "/finance")
    space_admin = _user("space_admin", group_paths=("/legal", "/finance"))
    document = _document(repo, user=space_admin, group_path="/legal")
    qdrant = FakeQdrant()

    response = _transfer(document.id, "/finance", user=space_admin, repo=repo, identity_repo=identity_repo, qdrant=qdrant)

    assert response.owner_group_path == "/finance"
    assert response.shared_group_paths == ["/legal"]
    assert qdrant.access_updates == [(document.id, "/finance", ["/finance", "/legal"])]


def test_space_admin_cannot_transfer_to_unmanaged_target_space() -> None:
    repo = InMemoryDocumentRepository()
    identity_repo = _identity_repo("/legal", "/finance")
    space_admin = _user("space_admin", group_paths=("/legal",))
    document = _document(repo, user=space_admin, group_path="/legal")
    qdrant = FakeQdrant()

    with pytest.raises(HTTPException) as exc_info:
        _transfer(document.id, "/finance", user=space_admin, repo=repo, identity_repo=identity_repo, qdrant=qdrant)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "document_owner_transfer_forbidden"
    assert repo.get_document(document.id).owner_group_path == "/legal"  # type: ignore[union-attr]
    assert qdrant.access_updates == []


def test_contributor_cannot_transfer_document_owner() -> None:
    repo = InMemoryDocumentRepository()
    identity_repo = _identity_repo("/legal", "/finance")
    contributor = _user("contributor", group_paths=("/legal",))
    document = _document(repo, user=contributor, group_path="/legal")
    qdrant = FakeQdrant()

    with pytest.raises(HTTPException) as exc_info:
        _transfer(document.id, "/finance", user=contributor, repo=repo, identity_repo=identity_repo, qdrant=qdrant)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "document_owner_transfer_forbidden"
    assert qdrant.access_updates == []


def test_transfer_to_missing_group_returns_422() -> None:
    repo = InMemoryDocumentRepository()
    identity_repo = _identity_repo("/legal")
    admin = _user("platform_admin", group_paths=())
    document = _document(repo, user=admin, group_path="/legal")

    with pytest.raises(HTTPException) as exc_info:
        _transfer(document.id, "/finance", user=admin, repo=repo, identity_repo=identity_repo, qdrant=FakeQdrant())

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "group_not_found"


def test_same_owner_transfer_is_noop() -> None:
    repo = InMemoryDocumentRepository()
    identity_repo = _identity_repo("/legal", "/finance")
    admin = _user("platform_admin", group_paths=())
    document = _document(repo, user=admin, group_path="/legal")
    repo.replace_document_shares(document.id, group_paths=["/finance"], actor_id=admin.id)
    qdrant = FakeQdrant()

    response = _transfer(document.id, "/legal", user=admin, repo=repo, identity_repo=identity_repo, qdrant=qdrant)

    assert response.owner_group_path == "/legal"
    assert response.shared_group_paths == ["/finance"]
    assert qdrant.access_updates == []
    assert repo.audit_events == []


def test_qdrant_failure_rolls_back_owner_and_shares() -> None:
    repo = InMemoryDocumentRepository()
    identity_repo = _identity_repo("/legal", "/finance", "/ops")
    admin = _user("platform_admin", group_paths=())
    document = _document(repo, user=admin, group_path="/legal")
    repo.replace_document_shares(document.id, group_paths=["/finance", "/ops"], actor_id=admin.id)
    qdrant = FakeQdrant(fail=True)

    with pytest.raises(HTTPException) as exc_info:
        _transfer(document.id, "/finance", user=admin, repo=repo, identity_repo=identity_repo, qdrant=qdrant)

    rolled_back = repo.get_document(document.id)
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "document_owner_transfer_index_failed"
    assert rolled_back is not None
    assert rolled_back.owner_group_path == "/legal"
    assert list(rolled_back.shared_group_paths) == ["/finance", "/ops"]
    assert repo.audit_events[-1]["payload"]["action_result"] == "failed"


def test_deleted_document_owner_transfer_is_rejected() -> None:
    repo = InMemoryDocumentRepository()
    identity_repo = _identity_repo("/legal", "/finance")
    admin = _user("platform_admin", group_paths=())
    document = _document(repo, user=admin, group_path="/legal")
    repo.soft_delete_document(document.id)

    with pytest.raises(HTTPException) as exc_info:
        _transfer(document.id, "/finance", user=admin, repo=repo, identity_repo=identity_repo, qdrant=FakeQdrant())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "document_deleted"


def _transfer(
    document_id: str,
    group_path: str,
    *,
    user: UserRecord,
    repo: InMemoryDocumentRepository,
    identity_repo: InMemoryIdentityRepository,
    qdrant: FakeQdrant,
):
    return asyncio.run(
        document_routes.transfer_document_owner(
            document_id,
            DocumentOwnerUpdateRequest(group_path=group_path),
            _csrf_request(),
            user=user,
            repo=repo,
            identity_repo=identity_repo,
            qdrant=qdrant,  # type: ignore[arg-type]
            graphrag=FakeGraphRAGDeletionService(),  # type: ignore[arg-type]
            graphrag_queue=InMemoryGraphRAGMaintenanceQueue(),
            config_repo=InMemoryIngestConfigRepository(),
        )
    )


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


def _identity_repo(*group_paths: str) -> InMemoryIdentityRepository:
    repo = InMemoryIdentityRepository()
    for path in group_paths:
        repo.create_group(path=path, name=path.removeprefix("/").title())
    return repo


def _document(repo: InMemoryDocumentRepository, *, user: UserRecord, group_path: str):
    return repo.create_document(
        title="Document.pdf",
        source_id=f"upload:{uuid4()}",
        group_path=group_path,
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
