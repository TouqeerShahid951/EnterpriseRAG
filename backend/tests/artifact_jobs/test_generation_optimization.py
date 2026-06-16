from __future__ import annotations

import json

from rag.artifact_jobs.build_program import generate_build_program
from rag.artifact_jobs.composer import (
    COMPOSITION_RECORD_TEXT_LIMIT,
    _compose_section,
    compose_document_bundle,
)
from rag.artifact_jobs.grounded_response import (
    build_grounded_artifact_payload,
    response_is_artifact_ready,
)
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
from rag.artifact_jobs.execution import ArtifactJobExecutor
from rag.artifact_jobs.sandbox_runner import InMemoryArtifactSandboxRunner
from rag.artifact_jobs.service import _public_stage_timings
from rag.core.config import Settings
from rag.repositories.artifact_jobs import InMemoryArtifactJobRepository
from rag.repositories.generated_artifact_memory import InMemoryGeneratedArtifactRepository
from rag.repositories.identity_models import UserRecord
from rag.repositories.rag_config_models import RagConfigRecord
from rag.schemas.query import RAGResponse, SourceAnchor
from rag.services.generated_artifact_storage import LocalGeneratedArtifactStorage


def test_stage_timing_serializer_handles_missing_and_partial_timings() -> None:
    assert _public_stage_timings(None) == {}
    assert _public_stage_timings({"planning": {"duration_ms": 25}, "bad": {"started_at": "x"}}) == {
        "planning": {"duration_ms": 25, "started_at": None, "completed_at": None}
    }


def test_composer_truncates_evidence_payload_for_llm_prompt() -> None:
    inference = _CapturingSectionInference()
    record = _evidence_record(text="A" * (COMPOSITION_RECORD_TEXT_LIMIT + 100))

    _compose_section(
        _job(),
        _plan(),
        "Facts",
        "Summarize the facts.",
        ["paragraph"],
        [record],
        inference=inference,
        model=None,
    )

    assert "A" * COMPOSITION_RECORD_TEXT_LIMIT in inference.prompts[0]
    assert "A" * (COMPOSITION_RECORD_TEXT_LIMIT + 1) not in inference.prompts[0]


def test_composer_failure_falls_back_with_evidence_ids_preserved() -> None:
    bundle = compose_document_bundle(
        _job(),
        _plan(),
        _evidence_manifest([
            _evidence_record(text="First fact."),
            _evidence_record(evidence_id="E2", text="Second fact."),
        ]),
        inference=_FailingInference(),
        model=None,
        section_timeout_seconds=0.01,
    )

    list_items = bundle.content.sections[0].blocks[0].list_items
    assert [item.evidence_ids for item in list_items] == [["E1"], ["E2"]]
    assert [citation.evidence_id for citation in bundle.content.citations] == ["E1", "E2"]


def test_grounded_response_payload_uses_displayed_answer_and_sources() -> None:
    response = _rag_response()

    assert response_is_artifact_ready(response, faithfulness_threshold=0.8)
    plan, evidence, bundle = build_grounded_artifact_payload(
        original_request="Generate a docx file summarizing the crimes",
        content_query="summarizing the crimes",
        response=response,
    )

    assert plan.sections[0].retrieval_queries == ["summarizing the crimes"]
    assert [record.doc_title for record in evidence.records] == ["FIR_03_robbery.pdf"]
    assert bundle.content.sections[0].blocks[0].text == response.answer
    assert bundle.content.citations[0].doc_title == "FIR_03_robbery.pdf"


def test_seeded_response_job_renders_without_artifact_composition(tmp_path) -> None:
    job_repo = InMemoryArtifactJobRepository()
    job = _job(repo=job_repo)
    plan, evidence, bundle = build_grounded_artifact_payload(
        original_request=job.original_request,
        content_query="summarizing the crimes",
        response=_rag_response(),
    )
    job_repo.update_job(job.id, {
        "plan_json": plan.model_dump(mode="json"),
        "evidence_manifest_json": evidence.model_dump(mode="json"),
        "content_spec_json": bundle.model_dump(mode="json"),
    })
    artifact_repo = InMemoryGeneratedArtifactRepository()
    executor = ArtifactJobExecutor(
        config=Settings(
            document_repository="memory",
            artifact_renderer_mode="deterministic",
            artifact_libreoffice_required=False,
        ),
        repo_factory=lambda: job_repo,
        artifact_repo_factory=lambda: artifact_repo,
        storage_factory=lambda: LocalGeneratedArtifactStorage(str(tmp_path)),
        identity_repo_factory=lambda: _IdentityRepo(job.user_id, job.permission_version),
        document_repo_factory=_DocumentRepo,
        inference=_FailingInference(),
        qdrant=object(),
        model_name="test-model",
        rag_config=RagConfigRecord(
            base_url="http://example.test",
            chat_model="test-chat",
            embed_model="test-embed",
            faithfulness_model=None,
            chat_timeout_seconds=1,
            embed_timeout_seconds=1,
        ),
    )

    completed = executor.execute(job.id)

    assert completed.status == "complete"
    assert artifact_repo.list_artifacts_for_job(job.id)[0].format == "docx"


def test_composer_reports_progress_for_each_composition_batch() -> None:
    events: list[tuple[int, int, str]] = []

    compose_document_bundle(
        _job(),
        _plan(),
        _evidence_manifest([
            _evidence_record(evidence_id=f"E{index}", text=f"Evidence fact {index}.")
            for index in range(1, 82)
        ]),
        inference=_CapturingSectionInference(),
        model=None,
        section_timeout_seconds=0.01,
        progress_callback=lambda current, total, phase: events.append((current, total, phase)),
    )

    assert events == [
        (1, 3, "batch"),
        (1, 3, "batch_complete"),
        (2, 3, "batch"),
        (2, 3, "batch_complete"),
        (3, 3, "batch"),
        (3, 3, "batch_complete"),
        (3, 3, "formatting"),
    ]


def test_executor_maps_composition_progress_to_visible_job_stages() -> None:
    job_repo = InMemoryArtifactJobRepository()
    job = _job(repo=job_repo)
    executor = object.__new__(ArtifactJobExecutor)
    executor.repo_factory = lambda: job_repo

    executor._record_composition_progress(job.id, current=1, total=4, phase="batch")
    first = job_repo.get_job(job.id)
    assert first is not None
    assert first.status == "composing"
    assert first.stage == "composing_1_of_4_batch"
    assert first.progress_pct == 56

    executor._record_composition_progress(job.id, current=2, total=4, phase="batch_complete")
    middle = job_repo.get_job(job.id)
    assert middle is not None
    assert middle.stage == "composing_2_of_4_batch"
    assert middle.progress_pct == 63

    executor._record_composition_progress(job.id, current=4, total=4, phase="formatting")
    final = job_repo.get_job(job.id)
    assert final is not None
    assert final.stage == "formatting_outputs"
    assert final.progress_pct == 70


def test_build_program_can_be_limited_to_subset_of_requested_formats() -> None:
    inference = _PptxBuildProgramInference()
    program = generate_build_program(
        _job(requested_formats=("docx", "pptx")),
        _plan(),
        _bundle(),
        inference=inference,
        model=None,
        requested_formats=("pptx",),
    )

    assert [output.format for output in program.expected_outputs] == ["pptx"]
    assert program.expected_outputs[0].filename.endswith(".pptx")


def test_fast_paginated_renderer_skips_sandbox_for_docx_pdf(tmp_path) -> None:
    job_repo = InMemoryArtifactJobRepository()
    job = _job(repo=job_repo, requested_formats=("docx", "pdf"))
    artifact_repo = InMemoryGeneratedArtifactRepository()
    storage = LocalGeneratedArtifactStorage(str(tmp_path))
    sandbox = InMemoryArtifactSandboxRunner(error=AssertionError("sandbox should not render DOCX/PDF"))
    executor = ArtifactJobExecutor(
        config=Settings(
            document_repository="memory",
            artifact_renderer_mode="sandbox",
            artifact_fast_paginated_renderer=True,
            artifact_libreoffice_required=False,
        ),
        repo_factory=lambda: job_repo,
        artifact_repo_factory=lambda: artifact_repo,
        storage_factory=lambda: storage,
        identity_repo_factory=lambda: _IdentityRepo(job.user_id, job.permission_version),
        document_repo_factory=_DocumentRepo,
        inference=object(),
        qdrant=object(),
        model_name="test-model",
        rag_config=RagConfigRecord(
            base_url="http://example.test",
            chat_model="test-chat",
            embed_model="test-embed",
            faithfulness_model=None,
            chat_timeout_seconds=1,
            embed_timeout_seconds=1,
        ),
        sandbox_runner=sandbox,
    )

    failures = executor._render_formats(job, _plan(), _evidence_manifest([_evidence_record()]), _bundle())

    assert failures == []
    assert sandbox.requests == []
    assert {artifact.format for artifact in artifact_repo.list_artifacts_for_job(job.id)} == {"docx", "pdf"}
    assert set(job_repo.get_job(job.id).stage_timings_json) == {"storing"}  # type: ignore[union-attr]


def _job(
    *,
    repo: InMemoryArtifactJobRepository | None = None,
    requested_formats: tuple[str, ...] = ("docx",),
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
        original_request="Generate an evidence-backed artifact.",
        requested_formats=list(requested_formats),
        group_path=None,
        document_ids=[],
        conversation_context=[],
        retention_days=1,
    )


def _plan() -> DocumentPlan:
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


def _evidence_record(*, evidence_id: str = "E1", text: str = "Evidence fact.") -> EvidenceRecord:
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


def _evidence_manifest(records: list[EvidenceRecord]) -> EvidenceManifest:
    return EvidenceManifest(
        sections=[
            EvidenceSection(
                title="Facts",
                objective="Summarize the facts.",
                retrieval_mode="focused_search",
                coverage_requirement="relevant_evidence",
                coverage_status="sufficient",
                records=records,
            )
        ]
    )


def _bundle() -> ArtifactContentBundle:
    citation = EvidenceCitation(
        evidence_id="E1",
        doc_id="doc-1",
        doc_title="FIR_02_kidnapping.pdf",
        chunk_id="chunk-E1",
        page_start=1,
        page_end=1,
    )
    section = ContentSection(
        title="Facts",
        blocks=[ContentBlock(kind="paragraph", text="Evidence fact.", evidence_ids=["E1"])],
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


def _rag_response() -> RAGResponse:
    source = SourceAnchor(
        doc_id="doc-1",
        doc_title="FIR_03_robbery.pdf",
        chunk_id="chunk-E1",
        page=1,
        page_start=1,
        page_end=1,
        excerpt="The complainant reported a robbery involving stolen cash and a mobile phone.",
        group_path="/",
    )
    return RAGResponse(
        trace_id="trace-1",
        answer="The retrieved FIR evidence describes a robbery involving stolen cash and a mobile phone.",
        sources=[source],
        artifacts=[],
        artifact_job=None,
        conflict_flag=False,
        conflict_detail=None,
        faithfulness_score=0.98,
        faithfulness_status="checked",
        unfounded_claims=[],
        intent="factual_simple",
        session_id="session-1",
        latency_ms=10,
        node_timings=[],
        degraded=False,
        degraded_reason=None,
    )


class _CapturingSectionInference:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_json(self, *, prompt: str, **_kwargs) -> str:
        self.prompts.append(prompt)
        return json.dumps({
            "title": "Facts",
            "blocks": [{"kind": "paragraph", "text": "Evidence fact.", "evidence_ids": ["E1"]}],
        })


class _FailingInference:
    def generate_json(self, **_kwargs) -> str:
        raise TimeoutError("composition call failed")


class _PptxBuildProgramInference:
    def generate_json(self, **_kwargs) -> str:
        return json.dumps({
            "sdk_version": "artifact_sdk_v1",
            "layout_profile": "professional",
            "expected_outputs": [{"format": "pptx", "filename": "FIR-summary.pptx"}],
            "python_code": "\n".join([
                "from rag.artifact_sandbox.sdk import ArtifactDocument",
                "doc = ArtifactDocument.from_input('/work/input.json')",
                "pptx = doc.create_pptx('/work/out/FIR-summary.pptx', title=doc.title)",
                "pptx.add_title_slide(doc.title)",
                "pptx.finalize()",
            ]),
        })


class _IdentityRepo:
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


class _DocumentRepo:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def get_document(self, _document_id: str):
        return None

    def append_audit_event(self, **kwargs):
        self.events.append(kwargs)
