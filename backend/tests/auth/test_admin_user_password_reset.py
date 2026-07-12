from __future__ import annotations

import pytest
from fastapi import HTTPException

from rag.api.routes import admin_user_routes
from rag.auth.passwords import hash_password, verify_password
from rag.auth.refresh_sessions import InMemoryRefreshSessionStore
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.auth.adapters.identity_memory import InMemoryIdentityRepository
from rag.auth.identity_models import UserRecord
from rag.schemas.admin import UserPasswordResetRequest


def test_admin_reset_password_forces_change_revokes_sessions_and_audits() -> None:
    repo = InMemoryIdentityRepository()
    audit_repo = InMemoryDocumentRepository()
    sessions = InMemoryRefreshSessionStore()
    admin = _create_user(repo, "admin@example.test", "platform_admin")
    target = _create_user(repo, "member@example.test", "member")
    original_permission_version = target.permission_version
    sessions.remember(user_id=admin.id, refresh_token="admin-token", ttl_seconds=300)
    sessions.remember(user_id=target.id, refresh_token="target-token", ttl_seconds=300)

    response = admin_user_routes.reset_user_password(
        target.id,
        UserPasswordResetRequest(temporary_password="NewPass123!"),
        user=admin,
        repo=repo,
        sessions=sessions,
        audit_repo=audit_repo,
    )

    updated = repo.get_user_by_id(target.id)
    assert updated is not None
    assert response.id == target.id
    assert verify_password("NewPass123!", updated.password_hash)
    assert not verify_password("OldPass123!", updated.password_hash)
    assert updated.must_change_password is True
    assert updated.permission_version == original_permission_version
    assert sessions.touch(user_id=target.id, refresh_token="target-token", ttl_seconds=300) is False
    assert sessions.touch(user_id=admin.id, refresh_token="admin-token", ttl_seconds=300) is True
    assert audit_repo.audit_events[-1]["event_type"] == "admin.user.password_reset"
    assert audit_repo.audit_events[-1]["target_id"] == target.id
    assert audit_repo.audit_events[-1]["payload"]["email"] == target.email
    assert "NewPass123!" not in str(audit_repo.audit_events[-1]["payload"])


def test_admin_cannot_reset_current_user_password() -> None:
    repo = InMemoryIdentityRepository()
    audit_repo = InMemoryDocumentRepository()
    sessions = InMemoryRefreshSessionStore()
    admin = _create_user(repo, "admin@example.test", "platform_admin")

    with pytest.raises(HTTPException) as exc:
        admin_user_routes.reset_user_password(
            admin.id,
            UserPasswordResetRequest(temporary_password="NewPass123!"),
            user=admin,
            repo=repo,
            sessions=sessions,
            audit_repo=audit_repo,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "cannot_reset_current_user"
    assert audit_repo.audit_events == []


def _create_user(repo: InMemoryIdentityRepository, email: str, account_type: str) -> UserRecord:
    return repo.create_user(
        email=email,
        name=email.split("@", 1)[0],
        password_hash=hash_password("OldPass123!"),
        group_paths=[],
        is_active=True,
        account_type=account_type,
    )
