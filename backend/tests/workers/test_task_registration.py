"""Compatibility checks for deployable Celery worker composition."""

from importlib import import_module
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

artifact_module = import_module("apps.workers.artifact.celery_app")
document_pipeline_module = import_module(
    "apps.workers.document_pipeline.celery_app"
)
evaluation_module = import_module("apps.workers.evaluation.celery_app")
artifact_app = artifact_module.celery_app
document_pipeline_app = document_pipeline_module.celery_app
document_pipeline_config = document_pipeline_module.config
evaluation_app = evaluation_module.celery_app


DOCUMENT_PIPELINE_TASKS = {
    "apps.ingestion.tasks.ingest_document",
    "apps.ingestion.tasks.index_document_graphrag",
    "apps.ingestion.tasks.rebuild_graphrag_partition",
    "apps.ingestion.tasks.reextract_document_metadata",
    "apps.ingestion.tasks.reextract_document_topics",
    "apps.ingestion.tasks.reextract_document_claims",
    "apps.ingestion.tasks.reextract_document_type",
}


def _registered_task_names(app: object) -> set[str]:
    app.loader.import_default_modules()  # type: ignore[attr-defined]
    return set(app.tasks)  # type: ignore[attr-defined]


def test_document_pipeline_preserves_registered_task_names() -> None:
    assert DOCUMENT_PIPELINE_TASKS <= _registered_task_names(document_pipeline_app)


def test_artifact_worker_preserves_registered_task_name() -> None:
    assert "rag.artifact_jobs.tasks.generate_artifact_job" in _registered_task_names(
        artifact_app
    )


def test_evaluation_worker_preserves_registered_task_name() -> None:
    assert "rag.evaluations.tasks.run_evaluation" in _registered_task_names(
        evaluation_app
    )


def test_document_pipeline_routes_graphrag_tasks_to_graphrag_queue() -> None:
    routes = document_pipeline_app.conf.task_routes

    assert routes["apps.ingestion.tasks.index_document_graphrag"] == {
        "queue": document_pipeline_config.graphrag_queue_name
    }
    assert routes["apps.ingestion.tasks.rebuild_graphrag_partition"] == {
        "queue": document_pipeline_config.graphrag_queue_name
    }
