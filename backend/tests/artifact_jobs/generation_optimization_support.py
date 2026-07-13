from __future__ import annotations

from rag.artifact_jobs.adapters.job_memory import InMemoryArtifactJobRepository
from rag.artifact_jobs.contracts import (
    ArtifactContentBundle,
    ContentBlock,
    ContentSection,
    DocumentPlan,
    DocumentPlanSection,
    EvidenceBackedContent,
    EvidenceCitation,
    EvidenceManifest,
    EvidenceRecord,
    EvidenceSection,
    PaginatedDocumentSpec,
    PresentationSlide,
    PresentationSpec,
)
from rag.auth.context import UserContext
from rag.documents.models import DocumentRecord


def artifact_job(
    *,
    repo: InMemoryArtifactJobRepository | None = None,
    requested_formats: tuple[str, ...] = ("docx",),
    original_request: str = "Generate an evidence-backed artifact.",
):
    selected_repo = repo or InMemoryArtifactJobRepository()
    return selected_repo.create_job(
        client_request_id="request-1",
        user_id="user-1",
        permission_version=1,
        user_email="user@example.test",
        account_type="platform_admin",
        group_paths=["/"],
        clearance_level="NATO_RESTRICTED",
        session_id="session-1",
        trace_id="trace-1",
        original_request=original_request,
        requested_formats=list(requested_formats),
        group_path=None,
        document_ids=[],
        conversation_context=[],
        retention_days=1,
    )


def user_context() -> UserContext:
    return UserContext(
        user_id="user-1",
        email="user@example.test",
        account_type="platform_admin",
        group_paths=("/",),
        clearance_level="NATO_RESTRICTED",
        permission_version=1,
    )


def document_plan() -> DocumentPlan:
    return DocumentPlan(
        title="FIR summary",
        purpose="Summarize alleged crimes.",
        sections=[
            DocumentPlanSection(
                title="Facts",
                objective="Summarize the facts.",
                preferred_blocks=["paragraph"],
                retrieval_queries=["facts"],
            )
        ],
    )


def structured_rows_plan(
    *,
    title: str = "All Crimes In FIRs",
    query: str = "all crimes in FIRs",
) -> DocumentPlan:
    return DocumentPlan(
        title=title,
        purpose=f"Create an evidence-grounded artifact about {query}.",
        sections=[
            DocumentPlanSection(
                title="Details",
                objective=f"Extract structured facts about {query}.",
                preferred_blocks=["table"],
                retrieval_queries=[query],
                retrieval_mode="structured_rows",
                coverage_requirement="complete_authorized_scope",
            )
        ],
    )


def evidence_record(
    *,
    evidence_id: str = "E1",
    text: str = "Evidence fact.",
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        section_title="Facts",
        query="facts",
        doc_id="doc-1",
        doc_title="FIR_02_kidnapping.pdf",
        chunk_id=f"chunk-{evidence_id}",
        page_start=1,
        page_end=1,
        text=text,
    )


def evidence_manifest(records: list[EvidenceRecord]) -> EvidenceManifest:
    return evidence_manifest_for_section("Facts", records)


def evidence_manifest_for_section(
    title: str,
    records: list[EvidenceRecord],
) -> EvidenceManifest:
    return EvidenceManifest(
        sections=[
            EvidenceSection(
                title=title,
                objective="Summarize the facts.",
                retrieval_mode="focused_search",
                coverage_requirement="relevant_evidence",
                coverage_status="sufficient",
                records=records,
            )
        ]
    )


def content_bundle() -> ArtifactContentBundle:
    citation = evidence_citation()
    section = ContentSection(
        title="Facts",
        blocks=[
            ContentBlock(
                kind="paragraph",
                text="Evidence fact.",
                evidence_ids=["E1"],
            )
        ],
    )
    content = EvidenceBackedContent(
        title="FIR summary",
        purpose="Summarize alleged crimes.",
        sections=[section],
        citations=[citation],
    )
    return ArtifactContentBundle(
        content=content,
        paginated=PaginatedDocumentSpec(title="FIR summary", sections=[section]),
        presentation=PresentationSpec(
            title="FIR summary",
            slides=[PresentationSlide(title="Facts", blocks=section.blocks)],
        ),
    )


def document_record(
    document_id: str,
    title: str,
    *,
    doc_type: str = "report",
    summary: str | None = None,
) -> DocumentRecord:
    return DocumentRecord(
        id=document_id,
        title=title,
        source_id=title,
        group_path="/admin",
        clearance_level="NATO_RESTRICTED",
        doc_type=doc_type,
        language="en",
        effective_date=None,
        expiry_date=None,
        description=None,
        summary=summary,
        topics=(),
        llm_topics=(),
        auto_doc_type=doc_type,
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
    )


def evidence_citation() -> EvidenceCitation:
    return EvidenceCitation(
        evidence_id="E1",
        doc_id="doc-1",
        doc_title="FIR_02_kidnapping.pdf",
        chunk_id="chunk-E1",
        page_start=1,
        page_end=1,
    )
