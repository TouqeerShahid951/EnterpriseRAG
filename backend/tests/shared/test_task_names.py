"""Shared worker task-name contract tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rag.core.config import Settings
from rag.shared.contracts.task_names import (
    DEFAULT_ARTIFACT_TASK_NAME,
    DEFAULT_EVALUATION_TASK_NAME,
    DEFAULT_GRAPHRAG_INDEX_TASK_NAME,
    DEFAULT_GRAPHRAG_PARTITION_REBUILD_TASK_NAME,
    DEFAULT_INGEST_TASK_NAME,
)


def test_settings_use_canonical_worker_task_names() -> None:
    config = Settings()

    assert config.artifact_task_name == DEFAULT_ARTIFACT_TASK_NAME
    assert config.evaluation_task_name == DEFAULT_EVALUATION_TASK_NAME
    assert config.ingest_task_name == DEFAULT_INGEST_TASK_NAME
    assert config.graphrag_index_task_name == DEFAULT_GRAPHRAG_INDEX_TASK_NAME
    assert (
        config.graphrag_partition_rebuild_task_name
        == DEFAULT_GRAPHRAG_PARTITION_REBUILD_TASK_NAME
    )


@pytest.mark.parametrize(
    "field",
    [
        "artifact_task_name",
        "evaluation_task_name",
        "ingest_task_name",
        "graphrag_index_task_name",
        "graphrag_partition_rebuild_task_name",
    ],
)
def test_settings_reject_blank_task_names(field: str) -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        Settings(**{field: "  "})


@pytest.mark.parametrize(
    "field",
    [
        "artifact_task_name",
        "evaluation_task_name",
        "ingest_task_name",
        "graphrag_index_task_name",
        "graphrag_partition_rebuild_task_name",
    ],
)
def test_settings_reject_the_reserved_celery_task_namespace(field: str) -> None:
    with pytest.raises(ValidationError, match="reserved task namespace"):
        Settings(**{field: "celery.chain"})


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "ingest_task_name": "custom.same",
            "graphrag_index_task_name": "custom.same",
        },
        {
            "ingest_task_name": DEFAULT_GRAPHRAG_INDEX_TASK_NAME,
        },
        {
            "graphrag_partition_rebuild_task_name": (
                "apps.ingestion.tasks.reextract_document_claims"
            ),
        },
    ],
)
def test_settings_reject_document_pipeline_task_name_collisions(
    overrides: dict[str, str],
) -> None:
    with pytest.raises(ValidationError, match="document pipeline task name collision"):
        Settings(**overrides)
