from uuid import uuid4

from rag.auth.document_access import can_read_document, can_write_document
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.auth.identity_models import UserRecord


def test_shared_document_is_readable_from_shared_space_with_clearance() -> None:
    repo = InMemoryDocumentRepository()
    owner = _user("contributor", group_paths=("/legal",))
    document = _document(repo, owner, "/legal")
    shared = repo.replace_document_shares(document.id, group_paths=["/finance"], actor_id=owner.id)

    assert shared is not None
    assert can_read_document(_user("member", group_paths=("/finance",)), shared)
    assert not can_read_document(_user("member", group_paths=("/engineering",)), shared)


def test_shared_document_write_is_system_governed_until_unshared() -> None:
    repo = InMemoryDocumentRepository()
    owner = _user("contributor", group_paths=("/legal",))
    document = _document(repo, owner, "/legal")
    shared = repo.replace_document_shares(document.id, group_paths=["/finance"], actor_id=owner.id)

    assert shared is not None
    assert not can_write_document(owner, shared)
    assert can_write_document(_user("system_admin", group_paths=()), shared)

    unshared = repo.replace_document_shares(document.id, group_paths=[], actor_id=owner.id)

    assert unshared is not None
    assert can_write_document(owner, unshared)


def test_shared_document_still_requires_clearance() -> None:
    repo = InMemoryDocumentRepository()
    owner = _user("contributor", group_paths=("/legal",), clearance_level="NATO_SECRET")
    document = _document(repo, owner, "/legal", clearance_level="NATO_SECRET")
    shared = repo.replace_document_shares(document.id, group_paths=["/finance"], actor_id=owner.id)

    assert shared is not None
    assert not can_read_document(_user("member", group_paths=("/finance",), clearance_level="NATO_RESTRICTED"), shared)
    assert can_read_document(_user("member", group_paths=("/finance",), clearance_level="NATO_SECRET"), shared)


def _document(
    repo: InMemoryDocumentRepository,
    user: UserRecord,
    group_path: str,
    *,
    clearance_level: str = "NATO_RESTRICTED",
):
    return repo.create_document(
        title=f"{group_path.strip('/')} document.pdf",
        source_id=f"upload:{uuid4()}",
        group_path=group_path,
        clearance_level=clearance_level,
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
    group_paths: tuple[str, ...],
    clearance_level: str = "NATO_RESTRICTED",
) -> UserRecord:
    user_id = str(uuid4())
    return UserRecord(
        id=user_id,
        email=f"{user_id}@example.test",
        name="Test User",
        password_hash="hash",
        is_active=True,
        account_type=account_type,  # type: ignore[arg-type]
        clearance_level=clearance_level,  # type: ignore[arg-type]
        must_change_password=False,
        permission_version=1,
        group_paths=group_paths,
    )
