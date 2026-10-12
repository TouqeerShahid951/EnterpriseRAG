from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi import Response
from starlette.requests import Request

from rag.auth.routes import admin_users as admin_user_routes
from rag.auth.routes import session as session_routes
from rag.auth.passwords import hash_password, verify_password
from rag.auth.refresh_sessions import InMemoryRefreshSessionStore
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.auth.adapters.identity_memory import InMemoryIdentityRepository
from rag.auth.identity_models import UserRecord
from rag.auth.schemas.admin import UserPasswordResetRequest, UserUpdateRequest
from rag.auth.schemas.session import ChangeEmailRequest


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


def test_platform_admin_can_change_another_users_email_and_revoke_sessions() -> None:
    repo = InMemoryIdentityRepository()
    audit_repo = InMemoryDocumentRepository()
    sessions = InMemoryRefreshSessionStore()
    admin = _create_user(repo, "admin@example.test", "platform_admin")
    target = _create_user(repo, "member@example.test", "member")
    sessions.remember(user_id=target.id, refresh_token="target-token", ttl_seconds=300)

    updated = admin_user_routes.update_user(
        target.id,
        UserUpdateRequest(email="new-member@example.test"),
        user=admin,
        repo=repo,
        sessions=sessions,
        audit_repo=audit_repo,
    )

    assert updated.email == "new-member@example.test"
    assert sessions.touch(user_id=target.id, refresh_token="target-token", ttl_seconds=300) is False
    assert audit_repo.audit_events[-1]["event_type"] == "admin.user.email_changed"


def test_user_can_change_own_email_with_current_password_and_new_session() -> None:
    repo = InMemoryIdentityRepository()
    audit_repo = InMemoryDocumentRepository()
    sessions = InMemoryRefreshSessionStore()
    user = _create_user(repo, "admin@example.test", "platform_admin")
    sessions.remember(user_id=user.id, refresh_token="old-token", ttl_seconds=300)

    updated = session_routes.change_email(
        ChangeEmailRequest(current_password="OldPass123!", new_email="new-admin@example.test"),
        _csrf_request(),
        Response(),
        user=user,
        repo=repo,
        sessions=sessions,
        audit_repo=audit_repo,
    )

    assert updated.email == "new-admin@example.test"
    assert repo.get_user_by_email("admin@example.test") is None
    assert repo.get_user_by_email("new-admin@example.test") is not None
    assert sessions.touch(user_id=user.id, refresh_token="old-token", ttl_seconds=300) is False
    assert audit_repo.audit_events[-1]["event_type"] == "auth.email_changed"
    assert audit_repo.audit_events[-1]["payload"] == {"previous_email": "admin@example.test", "email": "new-admin@example.test"}


def test_email_change_rejects_duplicate_or_wrong_password() -> None:
    repo = InMemoryIdentityRepository()
    audit_repo = InMemoryDocumentRepository()
    sessions = InMemoryRefreshSessionStore()
    user = _create_user(repo, "admin@example.test", "platform_admin")
    _create_user(repo, "taken@example.test", "member")

    for password, email, code in (("wrong", "new@example.test", "invalid_current_password"), ("OldPass123!", "taken@example.test", "invalid_email")):
        with pytest.raises(HTTPException) as exc:
            session_routes.change_email(
                ChangeEmailRequest(current_password=password, new_email=email),
                _csrf_request(),
                Response(),
                user=user,
                repo=repo,
                sessions=sessions,
                audit_repo=audit_repo,
            )
        assert exc.value.status_code == 400
        assert exc.value.detail["code"] == code


def _csrf_request() -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "headers": [(b"cookie", b"csrf_token=token"), (b"x-csrf-token", b"token")],
    })


def _create_user(repo: InMemoryIdentityRepository, email: str, account_type: str) -> UserRecord:
    return repo.create_user(
        email=email,
        name=email.split("@", 1)[0],
        password_hash=hash_password("OldPass123!"),
        group_paths=[],
        is_active=True,
        account_type=account_type,
    )
