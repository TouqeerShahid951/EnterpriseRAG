from __future__ import annotations

from rag.auth.identity_models import UserRecord

from generation_optimization_support import document_record


class RecordingQueue:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    def enqueue(self, job_id: str) -> None:
        self.job_ids.append(job_id)


class IdentityRepository:
    def __init__(self, user_id: str, permission_version: int) -> None:
        self.user = UserRecord(
            id=user_id,
            email="user@example.test",
            name="Test User",
            password_hash="",
            is_active=True,
            account_type="platform_admin",
            clearance_level="NATO_RESTRICTED",
            must_change_password=False,
            permission_version=permission_version,
            group_paths=("/",),
        )

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        return self.user if user_id == self.user.id else None


class DocumentRepository:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def get_document(self, document_id: str):
        return document_record(document_id, "Authorized source")

    def append_audit_event(self, **kwargs):
        self.events.append(kwargs)
