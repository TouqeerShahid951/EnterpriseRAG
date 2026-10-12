from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import uuid4

from rag.auth.identity_models import UserRecord
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.routes.catalog import list_documents, summarize_documents


def test_document_summary_counts_only_visible_documents() -> None:
    repo = InMemoryDocumentRepository()
    user = _user()
    _document(repo, owner="/ops")
    shared = _document(repo, owner="/finance")
    repo.replace_document_shares(
        shared.id,
        group_paths=["/ops"],
        actor_id=user.id,
    )
    _document(repo, owner="/ops", clearance="NATO_SECRET")
    _document(repo, owner="/ops", doc_type="abbreviation_glossary")
    deleted = _document(repo, owner="/ops")
    repo.soft_delete_document(deleted.id)

    summary = asyncio.run(summarize_documents(user=user, repo=repo))

    assert summary.total == 2
    assert [(group.group_path, group.count) for group in summary.groups] == [
        ("/finance", 1),
        ("/ops", 1),
    ]


def test_document_list_hides_glossary_pdfs() -> None:
    repo = InMemoryDocumentRepository()
    user = _user()
    report = _document(repo, owner="/ops")
    _document(repo, owner="/ops", doc_type="abbreviation_glossary")

    response = asyncio.run(
        list_documents(state="active", group_path=None, user=user, repo=repo)
    )

    assert [document.id for document in response.items] == [report.id]


def test_document_trash_includes_glossary_sources() -> None:
    repo = InMemoryDocumentRepository()
    user = _user()
    glossary = _document(repo, owner="/ops", doc_type="abbreviation_glossary")
    repo.soft_delete_document(glossary.id)

    response = asyncio.run(
        list_documents(state="deleted", group_path=None, user=user, repo=repo)
    )

    assert [document.id for document in response.items] == [glossary.id]


def test_document_summary_is_empty_without_document_metadata_permission() -> None:
    repo = InMemoryDocumentRepository()
    _document(repo, owner="/ops")

    summary = asyncio.run(
        summarize_documents(
            user=replace(_user(), account_type="user_manager"),
            repo=repo,
        )
    )

    assert summary.total == 0
    assert summary.groups == []


def _user() -> UserRecord:
    return UserRecord(
        id=str(uuid4()),
        email="member@example.test",
        name="Member",
        password_hash="hash",
        is_active=True,
        account_type="member",
        clearance_level="NATO_RESTRICTED",
        must_change_password=False,
        permission_version=1,
        group_paths=("/ops",),
    )


def _document(
    repo: InMemoryDocumentRepository,
    *,
    owner: str,
    clearance: str = "NATO_RESTRICTED",
    doc_type: str = "report",
):
    return repo.create_document(
        title=f"{uuid4()}.pdf",
        source_id=f"upload:{uuid4()}",
        group_path=owner,
        clearance_level=clearance,
        doc_type=doc_type,
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by=str(uuid4()),
        file_path="memory://document.pdf",
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status="complete",
    )
