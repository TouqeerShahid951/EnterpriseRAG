from __future__ import annotations

from uuid import uuid4

import pytest

from rag.auth.adapters.identity_memory import InMemoryIdentityRepository
from rag.auth.identity_models import UserRecord
from rag.documents.access_scope.ports import (
    DocumentAccessScopeIndexError,
    DocumentGraphCleanupError,
    DocumentGraphCleanupResult,
)
from rag.documents.access_scope.service import (
    DocumentAccessScopeRejected,
    DocumentAccessScopeService,
)
from rag.documents.adapters.memory import InMemoryDocumentRepository


class RecordingDocumentRepository(InMemoryDocumentRepository):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def replace_document_shares(
        self,
        document_id: str,
        *,
        group_paths: list[str],
        actor_id: str | None,
    ):
        self.events.append("repository.shares")
        return super().replace_document_shares(
            document_id,
            group_paths=group_paths,
            actor_id=actor_id,
        )


class FakeIndex:
    collection_name = "documents-test"

    def __init__(
        self,
        events: list[str],
        *,
        fail_acl: bool = False,
        fail_scope: bool = False,
    ) -> None:
        self.events = events
        self.fail_acl = fail_acl
        self.fail_scope = fail_scope
        self.acl_updates: list[tuple[str, list[str]]] = []
        self.scope_updates: list[tuple[str, str, list[str]]] = []

    def set_acl(self, document_id: str, access_group_paths: list[str]) -> None:
        self.events.append("index.acl")
        self.acl_updates.append((document_id, access_group_paths))
        if self.fail_acl:
            raise DocumentAccessScopeIndexError("metadata update failed")

    def set_access_scope(
        self,
        document_id: str,
        *,
        owner_group_path: str,
        access_group_paths: list[str],
    ) -> None:
        self.events.append("index.scope")
        self.scope_updates.append(
            (document_id, owner_group_path, access_group_paths)
        )
        if self.fail_scope:
            raise DocumentAccessScopeIndexError("metadata update failed")


class FakeGraphStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[tuple[str, str]] = []

    def partition_key_for(self, document) -> str:
        return f"{document.group_path}|partition"

    def delete_document(
        self,
        *,
        document_id: str,
        partition_key: str,
    ) -> DocumentGraphCleanupResult:
        self.deleted.append((document_id, partition_key))
        if self.fail:
            raise DocumentGraphCleanupError("graph unavailable")
        return DocumentGraphCleanupResult(
            status="complete",
            partition_key=partition_key,
        )


class FakeGraphQueue:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[tuple[str, str, str]] = []

    def enqueue_document(
        self,
        *,
        document_id: str,
        job_id: str,
        reason: str,
    ) -> None:
        if self.fail:
            raise RuntimeError("queue unavailable")
        self.messages.append((document_id, job_id, reason))


def test_transfer_owner_updates_repository_index_and_audit() -> None:
    service, repo, _, index, _, _ = _fixture()
    admin = _user("platform_admin")
    document = _document(repo, admin, "/legal")
    repo.replace_document_shares(
        document.id,
        group_paths=["/finance", "/ops"],
        actor_id=admin.id,
    )

    updated = service.transfer_owner(
        document.id,
        target_group_path="/finance",
        actor=admin,
    )

    assert updated.owner_group_path == "/finance"
    assert list(updated.shared_group_paths) == ["/legal", "/ops"]
    assert index.scope_updates == [
        (document.id, "/finance", ["/finance", "/legal", "/ops"])
    ]
    assert repo.audit_events[-1]["payload"] == {
        "old_group_path": "/legal",
        "new_group_path": "/finance",
        "old_shared_group_paths": ["/finance", "/ops"],
        "new_shared_group_paths": ["/legal", "/ops"],
        "qdrant_collection": "documents-test",
        "action_result": "success",
    }


def test_transfer_owner_rolls_back_repository_when_index_fails() -> None:
    service, repo, _, _, _, _ = _fixture(fail_scope=True)
    admin = _user("platform_admin")
    document = _document(repo, admin, "/legal")
    repo.replace_document_shares(
        document.id,
        group_paths=["/finance", "/ops"],
        actor_id=admin.id,
    )

    with pytest.raises(DocumentAccessScopeRejected) as exc_info:
        service.transfer_owner(
            document.id,
            target_group_path="/finance",
            actor=admin,
        )

    rolled_back = repo.get_document(document.id)
    assert exc_info.value.category == "upstream"
    assert exc_info.value.code == "document_owner_transfer_index_failed"
    assert rolled_back is not None
    assert rolled_back.owner_group_path == "/legal"
    assert list(rolled_back.shared_group_paths) == ["/finance", "/ops"]
    assert repo.audit_events[-1]["payload"]["action_result"] == "failed"


def test_owner_transfer_refreshes_graph_with_latest_completed_job() -> None:
    service, repo, _, _, graph, queue = _fixture(graph_enabled=True)
    admin = _user("platform_admin")
    document = _document(repo, admin, "/legal")
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="complete",
        progress_pct=100,
        origin="upload",
    )

    service.transfer_owner(
        document.id,
        target_group_path="/finance",
        actor=admin,
    )

    assert graph.deleted == [(document.id, "/legal|partition")]
    assert queue.messages == [
        (document.id, job.id, "documents.owner.transfer")
    ]
    assert repo.audit_events[-1]["payload"]["action_result"] == "queued"


def test_graph_cleanup_failure_is_warning_and_reindex_still_queues() -> None:
    service, repo, _, _, graph, queue = _fixture(
        graph_enabled=True,
        graph_fail=True,
    )
    admin = _user("platform_admin")
    document = _document(repo, admin, "/legal")
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="complete",
        progress_pct=100,
        origin="upload",
    )

    service.transfer_owner(
        document.id,
        target_group_path="/finance",
        actor=admin,
    )

    assert graph.deleted
    assert queue.messages == [
        (document.id, job.id, "documents.owner.transfer")
    ]
    refresh_events = [
        event
        for event in repo.audit_events
        if event["event_type"]
        == "documents.owner.transfer.graphrag_refresh"
    ]
    assert refresh_events[0]["payload"]["warning_code"] == (
        "graphrag_cleanup_failed"
    )
    assert refresh_events[1]["payload"]["action_result"] == "queued"


def test_graph_enqueue_failure_is_warning_and_does_not_fail_transfer() -> None:
    service, repo, _, _, _, _ = _fixture(
        graph_enabled=True,
        graph_queue_fail=True,
    )
    admin = _user("platform_admin")
    document = _document(repo, admin, "/legal")
    repo.create_ingest_job(
        doc_id=document.id,
        status="complete",
        progress_pct=100,
        origin="upload",
    )

    updated = service.transfer_owner(
        document.id,
        target_group_path="/finance",
        actor=admin,
    )

    assert updated.owner_group_path == "/finance"
    assert repo.audit_events[-1]["payload"]["warning_code"] == (
        "graphrag_reindex_enqueue_failed"
    )


def test_replace_shares_orders_additions_repository_before_index() -> None:
    service, repo, events, index, _, _ = _fixture()
    admin = _user("platform_admin")
    document = _document(repo, admin, "/legal")
    events.clear()

    updated = service.replace_shares(
        document.id,
        group_paths=["/finance", "/finance", "/ops"],
        actor=admin,
    )

    assert events == ["repository.shares", "index.acl"]
    assert list(updated.shared_group_paths) == ["/finance", "/ops"]
    assert index.acl_updates[-1][1] == ["/legal", "/finance", "/ops"]


def test_replace_shares_orders_removals_index_before_repository() -> None:
    service, repo, events, _, _, _ = _fixture()
    admin = _user("platform_admin")
    document = _document(repo, admin, "/legal")
    repo.replace_document_shares(
        document.id,
        group_paths=["/finance", "/ops"],
        actor_id=admin.id,
    )
    events.clear()

    service.replace_shares(
        document.id,
        group_paths=["/finance"],
        actor=admin,
    )

    assert events == ["index.acl", "repository.shares"]


def test_replace_shares_rolls_back_when_index_fails() -> None:
    service, repo, _, _, _, _ = _fixture(fail_acl=True)
    admin = _user("platform_admin")
    document = _document(repo, admin, "/legal")

    with pytest.raises(DocumentAccessScopeRejected) as exc_info:
        service.replace_shares(
            document.id,
            group_paths=["/finance"],
            actor=admin,
        )

    rolled_back = repo.get_document(document.id)
    assert exc_info.value.code == "document_acl_index_update_failed"
    assert rolled_back is not None
    assert rolled_back.shared_group_paths == ()
    assert repo.audit_events[-1]["payload"]["action_result"] == "failed"


def test_replace_shares_rejects_non_global_admin_before_document_lookup() -> None:
    service, _, _, _, _, _ = _fixture()

    with pytest.raises(DocumentAccessScopeRejected) as exc_info:
        service.replace_shares(
            "missing-document",
            group_paths=["/finance"],
            actor=_user("space_admin", group_paths=("/finance",)),
        )

    assert exc_info.value.category == "forbidden"
    assert exc_info.value.code == "document_share_forbidden"


def test_replace_shares_rejects_owner_space_as_share() -> None:
    service, repo, _, _, _, _ = _fixture()
    admin = _user("platform_admin")
    document = _document(repo, admin, "/legal")

    with pytest.raises(DocumentAccessScopeRejected) as exc_info:
        service.replace_shares(
            document.id,
            group_paths=["/legal"],
            actor=admin,
        )

    assert exc_info.value.category == "invalid"
    assert exc_info.value.code == "invalid_document_share"


def test_unshare_allows_target_space_admin_and_updates_acl_first() -> None:
    service, repo, events, _, _, _ = _fixture()
    admin = _user("platform_admin")
    document = _document(repo, admin, "/legal")
    repo.replace_document_shares(
        document.id,
        group_paths=["/finance", "/ops"],
        actor_id=admin.id,
    )
    finance_admin = _user("space_admin", group_paths=("/finance",))
    events.clear()

    updated = service.unshare(
        document.id,
        target_group_path="/finance",
        actor=finance_admin,
    )

    assert events == ["index.acl", "repository.shares"]
    assert list(updated.shared_group_paths) == ["/ops"]
    assert repo.audit_events[-1]["event_type"] == "documents.shares.unshare"


def test_unshare_missing_target_is_noop_before_permission_check() -> None:
    service, repo, events, _, _, _ = _fixture()
    admin = _user("platform_admin")
    document = _document(repo, admin, "/legal")
    repo.replace_document_shares(
        document.id,
        group_paths=["/finance"],
        actor_id=admin.id,
    )
    member = _user("member", group_paths=("/finance",))
    events.clear()

    unchanged = service.unshare(
        document.id,
        target_group_path="/ops",
        actor=member,
    )

    assert unchanged.shared_group_paths == ("/finance",)
    assert events == []


def test_unshare_rejects_member_when_target_share_exists() -> None:
    service, repo, _, _, _, _ = _fixture()
    admin = _user("platform_admin")
    document = _document(repo, admin, "/legal")
    repo.replace_document_shares(
        document.id,
        group_paths=["/finance"],
        actor_id=admin.id,
    )

    with pytest.raises(DocumentAccessScopeRejected) as exc_info:
        service.unshare(
            document.id,
            target_group_path="/finance",
            actor=_user("member", group_paths=("/finance",)),
        )

    assert exc_info.value.category == "forbidden"
    assert exc_info.value.code == "document_unshare_forbidden"


def _fixture(
    *,
    fail_acl: bool = False,
    fail_scope: bool = False,
    graph_enabled: bool = False,
    graph_fail: bool = False,
    graph_queue_fail: bool = False,
):
    events: list[str] = []
    repo = RecordingDocumentRepository(events)
    identities = InMemoryIdentityRepository()
    for group_path in ("/legal", "/finance", "/ops"):
        identities.create_group(
            path=group_path,
            name=group_path.removeprefix("/").title(),
        )
    index = FakeIndex(
        events,
        fail_acl=fail_acl,
        fail_scope=fail_scope,
    )
    graph = FakeGraphStore(fail=graph_fail)
    queue = FakeGraphQueue(fail=graph_queue_fail)
    service = DocumentAccessScopeService(
        document_repo=repo,
        identity_repo=identities,
        job_repo=repo,
        index=index,
        graph_store=graph,
        graph_queue=queue,
        graph_refresh_enabled=lambda: graph_enabled,
    )
    return service, repo, events, index, graph, queue


def _document(
    repo: InMemoryDocumentRepository,
    user: UserRecord,
    group_path: str,
):
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


def _user(
    account_type: str,
    *,
    group_paths: tuple[str, ...] = (),
) -> UserRecord:
    user_id = str(uuid4())
    return UserRecord(
        id=user_id,
        email=f"{user_id}@example.test",
        name="Test User",
        password_hash="hash",
        is_active=True,
        account_type=account_type,  # type: ignore[arg-type]
        clearance_level="NATO_RESTRICTED",
        must_change_password=False,
        permission_version=1,
        group_paths=group_paths,
    )
