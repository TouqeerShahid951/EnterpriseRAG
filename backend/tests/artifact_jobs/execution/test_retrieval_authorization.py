from __future__ import annotations

from datetime import date

import pytest

from rag.artifact_jobs.execution import executor as execution_module
from rag.artifact_jobs.adapters.generated_memory import (
    InMemoryGeneratedArtifactRepository,
)
from rag.artifact_jobs.adapters.job_memory import InMemoryArtifactJobRepository
from rag.artifact_jobs.contracts import (
    DocumentPlan,
    DocumentPlanSection,
    EvidenceManifest,
    EvidenceRecord,
    EvidenceSection,
)
from rag.artifact_jobs.execution import ArtifactJobExecutor, ArtifactPermissionChanged
from rag.artifact_jobs.service import ArtifactJobActionError, ArtifactJobService
from rag.auth.context import UserContext
from rag.auth.identity_models import UserRecord
from rag.core.config import Settings
from rag.documents.models import DocumentRecord
from rag.retrieval.contracts import AuthorizedCorpusRequest, RetrievedChunk


def test_scan_results_precede_search_results_and_keep_first_duplicate() -> None:
    jobs = InMemoryArtifactJobRepository()
    job = _job(jobs, document_ids=("doc-1",))
    scan_chunk = _chunk("doc-1", "chunk-1", text="Scan evidence", score=0.8)
    duplicate = _chunk("doc-1", "chunk-1", text="Search duplicate", score=0.9)
    search_chunk = _chunk("doc-1", "chunk-2", text="Search evidence", score=0.7)
    retriever = _SequencedRetriever(
        scan_results=(scan_chunk,),
        search_results=[(duplicate, search_chunk)],
    )

    evidence = execution_module.retrieve_document_evidence(
        job,
        _plan(retrieval_mode="document_scan"),
        retriever=retriever,
    )

    section = evidence.sections[0]
    assert [record.chunk_id for record in section.records] == ["chunk-1", "chunk-2"]
    assert section.records[0].text == "Scan evidence"
    assert section.coverage_status == "complete_scan"
    assert section.scanned_document_count == 1
    assert section.scanned_chunk_count == 1
    assert section.top_k_record_count == 2
    assert evidence.retrieval_rounds == 1
    assert retriever.scan_calls[0][0].document_ids == ("doc-1",)
    assert retriever.scan_calls[0][1:] == (False, 4000)


def test_empty_section_retries_once_and_retains_diagnostics() -> None:
    jobs = InMemoryArtifactJobRepository()
    job = _job(jobs)
    retriever = _SequencedRetriever(
        search_results=[(), (_chunk("doc-1", "chunk-1", text="Recovered"),)]
    )

    evidence = execution_module.retrieve_document_evidence(
        job,
        _plan(),
        retriever=retriever,
    )

    section = evidence.sections[0]
    assert evidence.retrieval_rounds == 2
    assert section.searched_query_count == 2
    assert section.coverage_status == "sufficient"
    assert [record.text for record in section.records] == ["Recovered"]
    assert section.warnings == [
        "No authorized evidence was found for this section.",
        "Coverage is based on top-k retrieval, not an exhaustive scan.",
    ]
    assert [request.query for request in retriever.search_calls] == [
        "policy",
        "Summarize policy. Original request: Create a policy report",
    ]


def test_inferred_scope_includes_shared_documents_and_remains_capped() -> None:
    jobs = InMemoryArtifactJobRepository()
    job = _job(
        jobs,
        group_path="/finance",
        group_paths=("/finance",),
        account_type="member",
        original_request="Create a report about all policies",
    )
    documents = [
        _document(
            f"policy-{index:03d}",
            f"Policy {index:03d}",
            group_path="/operations",
            shared_group_paths=("/finance",),
        )
        for index in range(105)
    ]
    documents.append(
        _document(
            "unshared-policy",
            "Unshared Policy",
            group_path="/legal",
        )
    )
    retriever = _SequencedRetriever(search_results=[(), ()])

    execution_module.retrieve_document_evidence(
        job,
        _plan(retrieval_mode="structured_rows"),
        retriever=retriever,
        document_repo=_Documents(documents),
    )

    inferred_ids = retriever.scan_calls[0][0].document_ids
    assert len(inferred_ids) == 100
    assert inferred_ids[0] == "policy-000"
    assert inferred_ids[-1] == "policy-099"
    assert "unshared-policy" not in inferred_ids


def test_executor_reauthorizes_retrieved_sources_before_persisting_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = InMemoryArtifactJobRepository()
    job = _job(jobs, account_type="member", group_paths=("/finance",))
    plan = _plan()
    evidence = _manifest(_record("revoked-doc", "chunk-1"))
    monkeypatch.setattr(
        execution_module, "plan_document", lambda *_args, **_kwargs: plan
    )
    monkeypatch.setattr(
        execution_module,
        "retrieve_document_evidence",
        lambda *_args, **_kwargs: evidence,
    )
    user = _user_record(job.user_id, group_paths=("/finance",))
    executor = ArtifactJobExecutor(
        config=Settings(document_repository="memory"),
        repo_factory=lambda: jobs,
        artifact_repo_factory=lambda: object(),  # type: ignore[arg-type]
        storage_factory=lambda: object(),  # type: ignore[arg-type]
        identity_repo_factory=lambda: _IdentityRepository(user),
        document_repo_factory=lambda: _Documents([]),
        inference=object(),  # type: ignore[arg-type]
        retriever=object(),  # type: ignore[arg-type]
        model_name="test-model",
    )

    with pytest.raises(ArtifactPermissionChanged):
        executor.execute(job.id)

    current = jobs.get_job(job.id)
    assert current is not None
    assert current.evidence_manifest_json is None


def test_job_detail_hides_persisted_evidence_after_source_access_is_revoked() -> None:
    jobs = InMemoryArtifactJobRepository()
    job = _job(jobs, account_type="member", group_paths=("/finance",))
    jobs.update_job(
        job.id,
        {
            "evidence_manifest_json": _manifest(_record("doc-1", "chunk-1")).model_dump(
                mode="json"
            )
        },
    )
    documents = _Documents(
        [
            _document(
                "doc-1",
                "Finance Policy",
                group_path="/operations",
                shared_group_paths=("/finance",),
            )
        ]
    )
    service = ArtifactJobService(
        repo_factory=lambda: jobs,
        artifact_repo_factory=InMemoryGeneratedArtifactRepository,
        document_repo_factory=lambda: documents,
        queue_factory=_Queue,
        retention_days=1,
    )
    user = _user_context(group_paths=("/finance",), account_type="member")

    assert service.get_for_user(job.id, user).id == job.id

    documents.records.clear()
    with pytest.raises(ArtifactJobActionError) as raised:
        service.get_for_user(job.id, user)

    assert raised.value.code == "artifact_job_not_found"


class _SequencedRetriever:
    def __init__(
        self,
        *,
        scan_results: tuple[RetrievedChunk, ...] = (),
        search_results: list[tuple[RetrievedChunk, ...]] | None = None,
    ) -> None:
        self.scan_results = scan_results
        self.search_results = search_results or []
        self.scan_calls: list[tuple[AuthorizedCorpusRequest, bool, int]] = []
        self.search_calls: list[AuthorizedCorpusRequest] = []

    def search(self, request: AuthorizedCorpusRequest) -> tuple[RetrievedChunk, ...]:
        self.search_calls.append(request)
        index = len(self.search_calls) - 1
        return self.search_results[index] if index < len(self.search_results) else ()

    def scan_documents(
        self,
        request: AuthorizedCorpusRequest,
        *,
        structured_only: bool,
        limit: int,
    ) -> tuple[RetrievedChunk, ...]:
        self.scan_calls.append((request, structured_only, limit))
        return self.scan_results


class _Documents:
    def __init__(self, records: list[DocumentRecord]) -> None:
        self.records = {record.id: record for record in records}

    def list_documents(self, *, state: str = "active") -> list[DocumentRecord]:
        assert state == "active"
        return list(self.records.values())

    def get_document(self, document_id: str) -> DocumentRecord | None:
        return self.records.get(document_id)


class _IdentityRepository:
    def __init__(self, user: UserRecord) -> None:
        self.user = user

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        return self.user if user_id == self.user.id else None


class _Queue:
    def enqueue(self, _job_id: str) -> None:
        return None


def _job(
    repo: InMemoryArtifactJobRepository,
    *,
    document_ids: tuple[str, ...] = (),
    group_path: str | None = None,
    group_paths: tuple[str, ...] = ("/finance",),
    account_type: str = "platform_admin",
    original_request: str = "Create a policy report",
):
    return repo.create_job(
        client_request_id="request-1",
        user_id="user-1",
        permission_version=1,
        user_email="user@example.test",
        account_type=account_type,
        group_paths=list(group_paths),
        clearance_level="NATO_RESTRICTED",
        session_id="session-1",
        trace_id="trace-1",
        original_request=original_request,
        requested_formats=["pdf"],
        group_path=group_path,
        document_ids=list(document_ids),
        conversation_context=[],
        retention_days=1,
    )


def _plan(*, retrieval_mode: str = "focused_search") -> DocumentPlan:
    return DocumentPlan(
        title="Policy report",
        purpose="Summarize policy.",
        sections=[
            DocumentPlanSection(
                title="Policy",
                objective="Summarize policy",
                preferred_blocks=["paragraph"],
                retrieval_queries=["policy"],
                retrieval_mode=retrieval_mode,  # type: ignore[arg-type]
            )
        ],
    )


def _chunk(
    doc_id: str,
    chunk_id: str,
    *,
    text: str,
    score: float = 1.0,
) -> RetrievedChunk:
    return RetrievedChunk(
        point_id=chunk_id,
        doc_id=doc_id,
        doc_title="Policy.pdf",
        chunk_id=chunk_id,
        page_start=1,
        page_end=1,
        content_type="text",
        text=text,
        structured_fields=(),
        retrieval_score=score,
        rerank_score=None,
        identity_keys=frozenset(),
    )


def _record(doc_id: str, chunk_id: str) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id="ev-1",
        section_title="Policy",
        query="policy",
        doc_id=doc_id,
        doc_title="Policy.pdf",
        chunk_id=chunk_id,
        page_start=1,
        page_end=1,
        content_type="text",
        text="Policy evidence",
        structured_fields={},
        retrieval_score=1.0,
    )


def _manifest(record: EvidenceRecord) -> EvidenceManifest:
    return EvidenceManifest(
        sections=[
            EvidenceSection(
                title="Policy",
                objective="Summarize policy",
                retrieval_mode="focused_search",
                coverage_requirement="relevant_evidence",
                coverage_status="sufficient",
                records=[record],
            )
        ]
    )


def _document(
    document_id: str,
    title: str,
    *,
    group_path: str,
    shared_group_paths: tuple[str, ...] = (),
) -> DocumentRecord:
    return DocumentRecord(
        id=document_id,
        title=title,
        source_id=title,
        group_path=group_path,
        clearance_level="NATO_RESTRICTED",
        doc_type="policy",
        language="en",
        effective_date=date(2026, 1, 1),
        expiry_date=None,
        description=None,
        summary=None,
        topics=(),
        llm_topics=(),
        auto_doc_type="policy",
        extracted_dates={},
        metadata_flags={},
        is_current=True,
        superseded_by=None,
        pending_supersedes=(),
        content_hash=None,
        uploaded_by=None,
        file_path=None,
        ingest_status="complete",
        deleted_at=None,
        created_at=None,
        updated_at=None,
        shared_group_paths=shared_group_paths,
    )


def _user_context(
    *,
    group_paths: tuple[str, ...],
    account_type: str,
) -> UserContext:
    return UserContext(
        user_id="user-1",
        email="user@example.test",
        account_type=account_type,  # type: ignore[arg-type]
        group_paths=group_paths,
        clearance_level="NATO_RESTRICTED",
        permission_version=1,
    )


def _user_record(
    user_id: str,
    *,
    group_paths: tuple[str, ...],
) -> UserRecord:
    return UserRecord(
        id=user_id,
        email="user@example.test",
        name="Test User",
        password_hash="",
        is_active=True,
        account_type="member",
        clearance_level="NATO_RESTRICTED",
        must_change_password=False,
        permission_version=1,
        group_paths=group_paths,
    )
