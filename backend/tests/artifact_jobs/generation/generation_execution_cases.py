from __future__ import annotations

from rag.artifact_jobs.adapters.generated_memory import (
    InMemoryGeneratedArtifactRepository,
)
from rag.artifact_jobs.adapters.job_memory import InMemoryArtifactJobRepository
from rag.artifact_jobs.adapters.storage import LocalGeneratedArtifactStorage
from rag.artifact_jobs.execution.bundle_repair import normalize_bundle_evidence_ids
from rag.artifact_jobs.contracts import (
    ArtifactContentBundle,
    ContentBlock,
    ContentListItem,
    ContentSection,
    EvidenceBackedContent,
    PaginatedDocumentSpec,
    PresentationSlide,
    PresentationSpec,
)
from rag.artifact_jobs.execution import ArtifactJobExecutor
from rag.artifact_jobs.generation.llm_json import LlmContractError
from rag.core.config import Settings

from generation_execution_support import DocumentRepository, IdentityRepository
from generation_inference_support import FailingInference
from generation_optimization_support import (
    artifact_job,
    content_bundle,
    document_plan,
    evidence_citation,
    evidence_manifest,
    evidence_record,
)


def test_seeded_response_job_renders_without_artifact_composition(tmp_path) -> None:
    job_repo = InMemoryArtifactJobRepository()
    job = artifact_job(repo=job_repo)
    plan = document_plan()
    evidence = evidence_manifest([evidence_record(evidence_id="ev_E1")])
    bundle = normalize_bundle_evidence_ids(content_bundle(), evidence)
    job_repo.update_job(
        job.id,
        {
            "plan_json": plan.model_dump(mode="json"),
            "evidence_manifest_json": evidence.model_dump(mode="json"),
            "content_spec_json": bundle.model_dump(mode="json"),
        },
    )
    artifact_repo = InMemoryGeneratedArtifactRepository()
    executor = ArtifactJobExecutor(
        config=Settings(
            document_repository="memory",
            artifact_libreoffice_required=False,
        ),
        repo_factory=lambda: job_repo,
        artifact_repo_factory=lambda: artifact_repo,
        storage_factory=lambda: LocalGeneratedArtifactStorage(str(tmp_path)),
        identity_repo_factory=lambda: IdentityRepository(
            job.user_id,
            job.permission_version,
        ),
        document_repo_factory=DocumentRepository,
        inference=FailingInference(),
        retriever=object(),  # type: ignore[arg-type]
        model_name="test-model",
    )

    completed = executor.execute(job.id)

    assert completed.status == "complete"
    assert artifact_repo.list_artifacts_for_job(job.id)[0].format == "docx"


def test_seeded_response_job_normalizes_recoverable_evidence_ids(tmp_path) -> None:
    job_repo = InMemoryArtifactJobRepository()
    job = artifact_job(repo=job_repo)
    plan = document_plan()
    evidence = evidence_manifest([evidence_record(evidence_id="ev_E1")])
    bundle = normalize_bundle_evidence_ids(content_bundle(), evidence)
    bad_id = evidence.records[0].evidence_id.removeprefix("ev_")
    broken_block = (
        bundle.content.sections[0]
        .blocks[0]
        .model_copy(update={"evidence_ids": [bad_id]})
    )
    broken_section = bundle.content.sections[0].model_copy(
        update={"blocks": [broken_block]}
    )
    bundle = bundle.model_copy(
        update={
            "content": bundle.content.model_copy(update={"sections": [broken_section]}),
            "paginated": bundle.paginated.model_copy(
                update={"sections": [broken_section]}
            ),
            "presentation": bundle.presentation.model_copy(
                update={
                    "slides": [
                        bundle.presentation.slides[0].model_copy(
                            update={"blocks": [broken_block]}
                        )
                    ],
                }
            ),
        }
    )
    job_repo.update_job(
        job.id,
        {
            "plan_json": plan.model_dump(mode="json"),
            "evidence_manifest_json": evidence.model_dump(mode="json"),
            "content_spec_json": bundle.model_dump(mode="json"),
        },
    )
    artifact_repo = InMemoryGeneratedArtifactRepository()
    executor = ArtifactJobExecutor(
        config=Settings(
            document_repository="memory",
            artifact_libreoffice_required=False,
        ),
        repo_factory=lambda: job_repo,
        artifact_repo_factory=lambda: artifact_repo,
        storage_factory=lambda: LocalGeneratedArtifactStorage(str(tmp_path)),
        identity_repo_factory=lambda: IdentityRepository(
            job.user_id,
            job.permission_version,
        ),
        document_repo_factory=DocumentRepository,
        inference=FailingInference(),
        retriever=object(),  # type: ignore[arg-type]
        model_name="test-model",
    )

    completed = executor.execute(job.id)

    assert completed.status == "complete"
    stored_job = job_repo.get_job(job.id)
    assert stored_job is not None
    stored = ArtifactContentBundle.model_validate(stored_job.content_spec_json)
    assert stored.content.sections[0].blocks[0].evidence_ids == [
        evidence.records[0].evidence_id
    ]


def test_seeded_response_job_falls_back_when_repair_json_is_malformed(
    tmp_path,
    monkeypatch,
) -> None:
    job_repo = InMemoryArtifactJobRepository()
    job = artifact_job(repo=job_repo, requested_formats=("pptx",))
    evidence = evidence_manifest(
        [evidence_record(evidence_id="E1", text="Supported evidence fact.")]
    )
    bundle = invalid_seeded_bundle()
    job_repo.update_job(
        job.id,
        {
            "plan_json": document_plan().model_dump(mode="json"),
            "evidence_manifest_json": evidence.model_dump(mode="json"),
            "content_spec_json": bundle.model_dump(mode="json"),
        },
    )
    monkeypatch.setattr(
        "rag.artifact_jobs.execution.executor.repair_document_bundle",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            LlmContractError(
                "ArtifactContentBundle validation failed after repair: bad json"
            )
        ),
    )
    artifact_repo = InMemoryGeneratedArtifactRepository()
    executor = seeded_executor(
        tmp_path=tmp_path,
        job_repo=job_repo,
        artifact_repo=artifact_repo,
        job=job,
    )

    completed = executor.execute(job.id)

    assert completed.status == "complete"
    stored_job = job_repo.get_job(job.id)
    assert stored_job is not None
    stored = ArtifactContentBundle.model_validate(stored_job.content_spec_json)
    assert [item.text for item in stored.content.sections[0].blocks[0].list_items] == [
        "Supported evidence fact."
    ]


def test_seeded_response_job_uses_deterministic_repair_before_llm(
    tmp_path,
    monkeypatch,
) -> None:
    job_repo = InMemoryArtifactJobRepository()
    job = artifact_job(repo=job_repo, requested_formats=("pptx",))
    evidence = evidence_manifest(
        [evidence_record(evidence_id="E1", text="Supported evidence fact.")]
    )
    bundle = invalid_seeded_bundle()
    job_repo.update_job(
        job.id,
        {
            "plan_json": document_plan().model_dump(mode="json"),
            "evidence_manifest_json": evidence.model_dump(mode="json"),
            "content_spec_json": bundle.model_dump(mode="json"),
        },
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError(
            "LLM repair should not run when deterministic repair already passes validation"
        )

    monkeypatch.setattr(
        "rag.artifact_jobs.execution.executor.repair_document_bundle",
        fail_if_called,
    )
    artifact_repo = InMemoryGeneratedArtifactRepository()
    executor = seeded_executor(
        tmp_path=tmp_path,
        job_repo=job_repo,
        artifact_repo=artifact_repo,
        job=job,
    )

    completed = executor.execute(job.id)

    assert completed.status == "complete"
    stored_job = job_repo.get_job(job.id)
    assert stored_job is not None
    stored = ArtifactContentBundle.model_validate(stored_job.content_spec_json)
    assert [item.text for item in stored.content.sections[0].blocks[0].list_items] == [
        "Supported evidence fact."
    ]


def invalid_seeded_bundle() -> ArtifactContentBundle:
    bad_section = ContentSection(
        title="Facts",
        blocks=[
            ContentBlock(
                kind="bullet_list",
                list_items=[
                    ContentListItem(
                        text="Supported evidence fact.",
                        evidence_ids=["E1"],
                    ),
                    ContentListItem(text="Ungrounded claim.", evidence_ids=["E1"]),
                ],
            )
        ],
    )
    return ArtifactContentBundle(
        content=EvidenceBackedContent(
            title="FIR summary",
            purpose="Summarize alleged crimes.",
            sections=[bad_section],
            citations=[evidence_citation()],
        ),
        paginated=PaginatedDocumentSpec(title="FIR summary", sections=[bad_section]),
        presentation=PresentationSpec(
            title="FIR summary",
            slides=[PresentationSlide(title="Facts", blocks=bad_section.blocks)],
        ),
    )


def seeded_executor(*, tmp_path, job_repo, artifact_repo, job) -> ArtifactJobExecutor:
    return ArtifactJobExecutor(
        config=Settings(
            document_repository="memory",
            artifact_libreoffice_required=False,
        ),
        repo_factory=lambda: job_repo,
        artifact_repo_factory=lambda: artifact_repo,
        storage_factory=lambda: LocalGeneratedArtifactStorage(str(tmp_path)),
        identity_repo_factory=lambda: IdentityRepository(
            job.user_id,
            job.permission_version,
        ),
        document_repo_factory=DocumentRepository,
        inference=FailingInference(),
        retriever=object(),  # type: ignore[arg-type]
        model_name="test-model",
    )
