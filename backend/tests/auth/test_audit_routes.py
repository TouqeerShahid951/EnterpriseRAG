from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from rag.api.routes import audit_routes
from rag.auth.dependencies import require_current_user
from rag.repositories.audit_memory import RepositoryAuditRepository
from rag.repositories.document_memory import InMemoryDocumentRepository
from rag.repositories.documents import get_document_repository
from rag.auth.identity_repository import get_identity_repository
from rag.auth.identity_models import UserRecord


class FakeIdentityRepository:
    def __init__(self, users: list[UserRecord]) -> None:
        self._users = {user.id: user for user in users}

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        return self._users.get(user_id)


def test_audit_list_defaults_and_enriches_user_email() -> None:
    repo = InMemoryDocumentRepository()
    actor = _user("platform_admin", email="admin@example.test")
    target = _user("member", email="member@example.test", name="Target Member")
    identity = FakeIdentityRepository([actor, target])
    repo.append_audit_event(
        event_type="admin.user.deleted",
        actor_id=actor.id,
        target_type="user",
        target_id=target.id,
        payload={"email": target.email, "name": target.name, "account_type": target.account_type},
    )

    response = _list(user=actor, repo=repo, identity=identity)

    assert response.total == 1
    assert response.limit == 100
    assert response.offset == 0
    assert response.summary.total == 1
    assert response.summary.category_counts["user"] == 1
    assert response.items[0].actor_email == "admin@example.test"
    assert response.items[0].target_user_email == "member@example.test"
    assert response.items[0].target_user_name == "Target Member"


def test_dependency_overrides_flow_through_audit_repository_provider() -> None:
    repo = InMemoryDocumentRepository()
    admin = _user("platform_admin", email="admin@example.test")
    identity = FakeIdentityRepository([admin])
    repo.append_audit_event(
        event_type="auth.login",
        actor_id=admin.id,
        target_type="user",
        target_id=admin.id,
        payload={"email": admin.email},
    )
    app = FastAPI()
    app.include_router(audit_routes.router)

    with TestClient(app) as anonymous:
        assert anonymous.get("/audit-log?category=unsupported").status_code == 401
        assert anonymous.get("/audit-log/export?category=unsupported").status_code == 401

    app.dependency_overrides[require_current_user] = lambda: admin
    app.dependency_overrides[get_document_repository] = lambda: repo
    app.dependency_overrides[get_identity_repository] = lambda: identity

    with TestClient(app) as client:
        response = client.get("/audit-log?category=authentication")
        export = client.get("/audit-log/export?category=authentication")
        invalid = client.get("/audit-log?category=unsupported")
        invalid_group = client.get("/audit-log?group_path=/finance//")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["actor_email"] == admin.email
    assert export.status_code == 200
    assert "auth.login" in export.text
    assert repo.audit_events[-1]["event_type"] == "audit.exported"
    assert invalid.status_code == 400
    assert invalid_group.status_code == 400


def test_audit_list_requires_audit_permission() -> None:
    repo = InMemoryDocumentRepository()
    member = _user("member")

    with pytest.raises(HTTPException) as exc_info:
        _list(user=member, repo=repo, identity=FakeIdentityRepository([member]))

    assert exc_info.value.status_code == 403


def test_auditor_visibility_stays_scoped_to_readable_documents() -> None:
    repo = InMemoryDocumentRepository()
    auditor = _user("auditor", group_paths=("/finance",))
    uploader = _user("contributor", group_paths=("/finance",))
    finance_doc = _document(repo, uploader, "/finance")
    ops_doc = _document(repo, uploader, "/ops")
    repo.append_audit_event(event_type="upload.queued", actor_id=uploader.id, target_type="document", target_id=finance_doc.id, payload={"group_path": "/finance"})
    repo.append_audit_event(event_type="upload.queued", actor_id=uploader.id, target_type="document", target_id=ops_doc.id, payload={"group_path": "/ops"})

    response = _list(user=auditor, repo=repo, identity=FakeIdentityRepository([auditor, uploader]))

    assert response.total == 1
    assert response.items[0].target_id == finance_doc.id
    assert response.items[0].target_document_title == finance_doc.title


def test_document_event_cannot_bypass_document_scope_with_payload_group() -> None:
    repo = InMemoryDocumentRepository()
    auditor = _user("auditor", group_paths=("/finance",))
    uploader = _user("contributor", group_paths=("/ops",))
    ops_doc = _document(repo, uploader, "/ops")
    repo.append_audit_event(
        event_type="upload.queued",
        actor_id=uploader.id,
        target_type="document",
        target_id=ops_doc.id,
        payload={"group_path": "/finance", "doc_id": ops_doc.id},
    )
    repo.append_audit_event(
        event_type="review.queue.opened",
        actor_id=uploader.id,
        target_type="review_queue",
        target_id=None,
        payload={"group_path": "/finance"},
    )

    response = _list(
        user=auditor,
        repo=repo,
        identity=FakeIdentityRepository([auditor, uploader]),
    )

    assert response.total == 1
    assert response.items[0].event_type == "review.queue.opened"


def test_auditor_cannot_see_upper_level_events_outside_visible_scope() -> None:
    repo = InMemoryDocumentRepository()
    auditor = _user("auditor", group_paths=("/finance",))
    admin = _user("platform_admin", email="admin@example.test", group_paths=("/admin",))
    managed_user = _user("member", email="managed@example.test", group_paths=("/ops",))
    finance_doc = _document(repo, admin, "/finance")
    ops_doc = _document(repo, admin, "/ops")
    visible_event_id = _append_event(
        repo,
        event_type="documents.delete",
        actor_id=admin.id,
        target_type="document",
        target_id=finance_doc.id,
        payload={"group_path": "/finance", "doc_id": finance_doc.id},
        created_at=datetime.now(UTC),
    )
    _append_event(
        repo,
        event_type="admin.ingest.config",
        actor_id=admin.id,
        target_type="workspace_ingest_config",
        target_id=None,
        payload={"max_concurrent_jobs": 2},
        created_at=datetime.now(UTC),
    )
    _append_event(
        repo,
        event_type="auth.login",
        actor_id=admin.id,
        target_type="user",
        target_id=admin.id,
        payload={"email": admin.email},
        created_at=datetime.now(UTC),
    )
    _append_event(
        repo,
        event_type="admin.user.deleted",
        actor_id=admin.id,
        target_type="user",
        target_id=managed_user.id,
        payload={"email": managed_user.email, "name": managed_user.name},
        created_at=datetime.now(UTC),
    )
    _append_event(
        repo,
        event_type="upload.queued",
        actor_id=admin.id,
        target_type="document",
        target_id=ops_doc.id,
        payload={"group_path": "/ops", "doc_id": ops_doc.id},
        created_at=datetime.now(UTC),
    )

    response = _list(user=auditor, repo=repo, identity=FakeIdentityRepository([auditor, admin, managed_user]))

    assert response.total == 1
    assert response.items[0].id == visible_event_id
    assert response.items[0].target_id == finance_doc.id
    assert response.items[0].actor_email == "admin@example.test"


def test_audit_filters_search_category_actor_target_group_and_dates() -> None:
    repo = InMemoryDocumentRepository()
    admin = _user("platform_admin", email="admin@example.test")
    uploader = _user("contributor", email="uploader@example.test", group_paths=("/finance",))
    finance_doc = _document(repo, uploader, "/finance")
    old_doc = _document(repo, uploader, "/finance/archive")
    now = datetime.now(UTC)
    _append_event(
        repo,
        event_type="upload.queued",
        actor_id=uploader.id,
        target_type="document",
        target_id=finance_doc.id,
        payload={"filename": "Budget.pdf", "group_path": "/finance", "doc_id": finance_doc.id},
        created_at=now,
    )
    _append_event(
        repo,
        event_type="auth.login",
        actor_id=admin.id,
        target_type="user",
        target_id=admin.id,
        payload={"email": admin.email},
        created_at=now - timedelta(days=5),
    )
    _append_event(
        repo,
        event_type="documents.delete",
        actor_id=uploader.id,
        target_type="document",
        target_id=old_doc.id,
        payload={"group_path": "/finance/archive", "doc_id": old_doc.id},
        created_at=now - timedelta(days=2),
    )

    response = _list(
        user=admin,
        repo=repo,
        identity=FakeIdentityRepository([admin, uploader]),
        search="budget",
        category="document",
        actor_id="uploader@example.test",
        target_type="document",
        group_path="/finance",
        created_from=now - timedelta(hours=1),
        created_to=now + timedelta(hours=1),
    )

    assert response.total == 1
    assert response.items[0].event_type == "upload.queued"
    assert response.items[0].actor_email == "uploader@example.test"


def test_audit_pagination_and_summary_use_filtered_visible_result_set() -> None:
    repo = InMemoryDocumentRepository()
    admin = _user("platform_admin")
    for index in range(3):
        repo.append_audit_event(event_type="auth.login", actor_id=admin.id, target_type="user", target_id=admin.id, payload={"email": admin.email, "index": index})

    response = _list(user=admin, repo=repo, identity=FakeIdentityRepository([admin]), category="authentication", limit=1, offset=1)

    assert response.total == 3
    assert response.limit == 1
    assert response.offset == 1
    assert len(response.items) == 1
    assert response.summary.auth_events == 3
    assert response.summary.event_type_counts["auth.login"] == 3


def test_audit_export_uses_filters_and_records_export_event() -> None:
    repo = InMemoryDocumentRepository()
    admin = _user("platform_admin", email="admin@example.test")
    uploader = _user("contributor", email="uploader@example.test", group_paths=("/finance",))
    finance_doc = _document(repo, uploader, "/finance")
    repo.append_audit_event(
        event_type="upload.queued",
        actor_id=uploader.id,
        target_type="document",
        target_id=finance_doc.id,
        payload={"filename": "Budget.pdf", "group_path": "/finance", "doc_id": finance_doc.id},
    )
    repo.append_audit_event(event_type="auth.login", actor_id=admin.id, target_type="user", target_id=admin.id, payload={"email": admin.email})

    response = _export(user=admin, repo=repo, identity=FakeIdentityRepository([admin, uploader]), category="document")
    body = response.body.decode("utf-8")

    assert "upload.queued" in body
    assert "target_document_title" in body
    assert finance_doc.title in body
    assert "Budget.pdf" in body
    assert "auth.login" not in body
    assert repo.audit_events[-1]["event_type"] == "audit.exported"
    assert repo.audit_events[-1]["payload"]["row_count"] == 1
    assert repo.audit_events[-1]["payload"]["matched_count"] == 1


def test_deleted_user_target_email_falls_back_to_payload() -> None:
    repo = InMemoryDocumentRepository()
    actor = _user("platform_admin", email="admin@example.test")
    deleted_user_id = str(uuid4())
    repo.append_audit_event(
        event_type="admin.user.deleted",
        actor_id=actor.id,
        target_type="user",
        target_id=deleted_user_id,
        payload={"email": "deleted@example.test", "name": "Deleted User"},
    )

    response = _list(user=actor, repo=repo, identity=FakeIdentityRepository([actor]))

    assert response.items[0].actor_email == "admin@example.test"
    assert response.items[0].target_user_email == "deleted@example.test"
    assert response.items[0].target_user_name == "Deleted User"


def test_document_title_is_enriched_for_document_events_without_filename_payload() -> None:
    repo = InMemoryDocumentRepository()
    admin = _user("platform_admin", email="admin@example.test")
    document = _document(repo, admin, "/finance")
    repo.append_audit_event(
        event_type="documents.delete",
        actor_id=admin.id,
        target_type="document",
        target_id=document.id,
        payload={"group_path": "/finance", "doc_id": document.id},
    )

    response = _list(user=admin, repo=repo, identity=FakeIdentityRepository([admin]), search=document.title)

    assert response.total == 1
    assert response.items[0].target_document_title == document.title


def _list(
    *,
    user: UserRecord,
    repo: InMemoryDocumentRepository,
    identity: FakeIdentityRepository,
    search: str | None = None,
    category: str | None = None,
    event_type: str | None = None,
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    group_path: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
):
    audit_repo = RepositoryAuditRepository(documents=repo, identities=identity)
    return asyncio.run(
        audit_routes.list_audit_events(
            limit=limit,
            offset=offset,
            filters=audit_routes._audit_filters(
                search=search,
                category=category,
                event_type=event_type,
                actor_id=actor_id,
                target_type=target_type,
                target_id=target_id,
                group_path=group_path,
                created_from=created_from,
                created_to=created_to,
            ),
            user=user,
            repo=audit_repo,
        )
    )


def _export(
    *,
    user: UserRecord,
    repo: InMemoryDocumentRepository,
    identity: FakeIdentityRepository,
    search: str | None = None,
    category: str | None = None,
    event_type: str | None = None,
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    group_path: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    max_rows: int = audit_routes.AUDIT_SCAN_LIMIT,
):
    audit_repo = RepositoryAuditRepository(documents=repo, identities=identity)
    return asyncio.run(
        audit_routes.export_audit_events(
            max_rows=max_rows,
            filters=audit_routes._audit_filters(
                search=search,
                category=category,
                event_type=event_type,
                actor_id=actor_id,
                target_type=target_type,
                target_id=target_id,
                group_path=group_path,
                created_from=created_from,
                created_to=created_to,
            ),
            user=user,
            repo=audit_repo,
            writer=repo,
        )
    )


def _append_event(
    repo: InMemoryDocumentRepository,
    *,
    event_type: str,
    actor_id: str | None,
    target_type: str | None,
    target_id: str | None,
    payload: dict[str, object],
    created_at: datetime,
) -> str:
    event_id = str(uuid4())
    repo.audit_events.append({
        "id": event_id,
        "event_type": event_type,
        "actor_id": actor_id,
        "target_type": target_type,
        "target_id": target_id,
        "payload": payload,
        "created_at": created_at,
    })
    return event_id


def _document(repo: InMemoryDocumentRepository, user: UserRecord, group_path: str):
    return repo.create_document(
        title=f"{group_path.strip('/') or 'root'} document.pdf",
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
    email: str | None = None,
    name: str = "Test User",
    group_paths: tuple[str, ...] = ("/finance",),
) -> UserRecord:
    user_id = str(uuid4())
    return UserRecord(
        id=user_id,
        email=email or f"{user_id}@example.test",
        name=name,
        password_hash="hash",
        is_active=True,
        account_type=account_type,  # type: ignore[arg-type]
        clearance_level="NATO_RESTRICTED",
        must_change_password=False,
        permission_version=1,
        group_paths=group_paths,
    )
