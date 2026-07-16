from __future__ import annotations

from rag.artifact_jobs.adapters.generated_memory import (
    InMemoryGeneratedArtifactRepository,
)
from rag.artifact_jobs.adapters.job_memory import InMemoryArtifactJobRepository
from rag.artifact_jobs.adapters.storage import LocalGeneratedArtifactStorage
from rag.artifact_jobs.generation.composer import compose_document_bundle
from rag.artifact_jobs.execution import ArtifactJobExecutor
from rag.core.config import Settings

from generation_execution_support import DocumentRepository, IdentityRepository
from generation_inference_support import CapturingSectionInference
from generation_optimization_support import (
    artifact_job,
    content_bundle,
    evidence_manifest,
    evidence_record,
    document_plan,
)


def test_composer_reports_progress_for_each_composition_batch() -> None:
    events: list[tuple[int, int, str]] = []

    compose_document_bundle(
        artifact_job(),
        document_plan(),
        evidence_manifest(
            [
                evidence_record(
                    evidence_id=f"E{index}",
                    text=f"Evidence fact {index}.",
                )
                for index in range(1, 82)
            ]
        ),
        inference=CapturingSectionInference(),
        model=None,
        section_timeout_seconds=0.01,
        progress_callback=lambda current, total, phase: events.append(
            (current, total, phase)
        ),
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
    job = artifact_job(repo=job_repo)
    executor = object.__new__(ArtifactJobExecutor)
    executor.repo_factory = lambda: job_repo

    executor._record_composition_progress(job.id, current=1, total=4, phase="batch")
    first = job_repo.get_job(job.id)
    assert first is not None
    assert first.status == "composing"
    assert first.stage == "composing_1_of_4_batch"
    assert first.progress_pct == 56
    assert first.stage_progress == {
        "unit": "batches",
        "current": 1,
        "total": 4,
        "label": "Composing content batch 1 of 4",
    }

    executor._record_composition_progress(
        job.id,
        current=2,
        total=4,
        phase="batch_complete",
    )
    middle = job_repo.get_job(job.id)
    assert middle is not None
    assert middle.stage == "composing_2_of_4_batch"
    assert middle.progress_pct == 63

    executor._record_composition_progress(
        job.id,
        current=4,
        total=4,
        phase="formatting",
    )
    final = job_repo.get_job(job.id)
    assert final is not None
    assert final.stage == "formatting_outputs"
    assert final.progress_pct == 70
    assert final.stage_progress == {
        "unit": "slides",
        "current": 0,
        "total": 1,
        "label": "Choosing title, sections, and slide layout",
    }


def test_executor_records_render_format_progress() -> None:
    job_repo = InMemoryArtifactJobRepository()
    job = artifact_job(repo=job_repo)
    executor = object.__new__(ArtifactJobExecutor)
    executor.repo_factory = lambda: job_repo

    executor._record_render_format_progress(job.id, "pptx", 2, 3)

    updated = job_repo.get_job(job.id)
    assert updated is not None
    assert updated.stage == "rendering_pptx"
    assert updated.stage_progress == {
        "unit": "formats",
        "current": 2,
        "total": 3,
        "label": "Rendering PPTX (2 of 3)",
    }


def test_artifact_job_renderer_uses_shared_renderer_for_all_formats(tmp_path) -> None:
    job_repo = InMemoryArtifactJobRepository()
    job = artifact_job(
        repo=job_repo,
        requested_formats=("docx", "pdf", "pptx"),
    )
    artifact_repo = InMemoryGeneratedArtifactRepository()
    storage = LocalGeneratedArtifactStorage(str(tmp_path))
    executor = ArtifactJobExecutor(
        config=Settings(
            document_repository="memory",
            artifact_libreoffice_required=False,
        ),
        repo_factory=lambda: job_repo,
        artifact_repo_factory=lambda: artifact_repo,
        storage_factory=lambda: storage,
        identity_repo_factory=lambda: IdentityRepository(
            job.user_id,
            job.permission_version,
        ),
        document_repo_factory=DocumentRepository,
        inference=object(),
        retriever=object(),  # type: ignore[arg-type]
        model_name="test-model",
    )

    failures = executor._render_formats(
        job,
        evidence_manifest([evidence_record()]),
        content_bundle(),
    )

    assert failures == []
    assert {
        artifact.format for artifact in artifact_repo.list_artifacts_for_job(job.id)
    } == {"docx", "pdf", "pptx"}
    stored_job = job_repo.get_job(job.id)
    assert stored_job is not None
    assert set(stored_job.stage_timings_json) == {"storing"}
