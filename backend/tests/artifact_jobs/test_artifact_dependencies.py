from types import SimpleNamespace

import pytest

from rag.artifact_jobs.adapters.generated_memory import (
    InMemoryGeneratedArtifactRepository,
)
from rag.artifact_jobs.adapters.job_memory import InMemoryArtifactJobRepository
from rag.artifact_jobs.adapters.queue import (
    CeleryArtifactJobQueue,
    InMemoryArtifactJobQueue,
)
from rag.artifact_jobs.adapters.storage import LocalGeneratedArtifactStorage
from rag.artifact_jobs.dependencies import (
    build_artifact_job_queue,
    build_artifact_job_repository,
    build_generated_artifact_repository,
    build_generated_artifact_storage,
)
from rag.core.config import settings


def test_memory_dependencies_are_selected_from_one_feature_composition_module(
    tmp_path,
) -> None:
    config = settings.model_copy(
        update={
            "document_repository": "memory",
            "upload_storage_backend": "local",
            "upload_storage_dir": str(tmp_path),
            "artifact_queue_backend": "memory",
        }
    )

    assert isinstance(
        build_artifact_job_repository(config), InMemoryArtifactJobRepository
    )
    assert isinstance(
        build_generated_artifact_repository(config),
        InMemoryGeneratedArtifactRepository,
    )
    assert isinstance(
        build_generated_artifact_storage(config), LocalGeneratedArtifactStorage
    )
    assert isinstance(build_artifact_job_queue(config), InMemoryArtifactJobQueue)


@pytest.mark.parametrize(
    ("field", "value", "builder", "message"),
    [
        (
            "upload_storage_backend",
            "unsupported",
            build_generated_artifact_storage,
            "unsupported generated artifact storage backend",
        ),
        (
            "artifact_queue_backend",
            "unsupported",
            build_artifact_job_queue,
            "unsupported artifact queue backend",
        ),
    ],
)
def test_dependency_builders_reject_unknown_backends(
    field: str,
    value: str,
    builder,
    message: str,
) -> None:
    config = settings.model_copy(update={field: value})

    with pytest.raises(RuntimeError, match=message):
        builder(config)


def test_celery_queue_preserves_task_name_and_queue() -> None:
    calls: list[tuple[str, list[str], str]] = []
    app = SimpleNamespace(
        send_task=lambda name, args, queue: calls.append((name, args, queue))
    )
    queue = CeleryArtifactJobQueue(
        broker_url="redis://unused",
        queue_name="artifact:jobs",
        task_name="rag.artifact_jobs.tasks.generate_artifact_job",
        app=app,
    )

    queue.enqueue("job-1")

    assert calls == [
        (
            "rag.artifact_jobs.tasks.generate_artifact_job",
            ["job-1"],
            "artifact:jobs",
        )
    ]


def test_celery_queue_exposes_dispatch_failure() -> None:
    def fail(*_args, **_kwargs) -> None:
        raise ConnectionError("broker unavailable")

    queue = CeleryArtifactJobQueue(
        broker_url="redis://unused",
        queue_name="artifact:jobs",
        task_name="rag.artifact_jobs.tasks.generate_artifact_job",
        app=SimpleNamespace(send_task=fail),
    )

    with pytest.raises(RuntimeError, match="artifact celery enqueue failed"):
        queue.enqueue("job-1")
