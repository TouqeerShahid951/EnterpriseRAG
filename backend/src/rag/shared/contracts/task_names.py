"""Stable Celery task identifiers shared by producers and worker images."""

DEFAULT_ARTIFACT_TASK_NAME = "rag.artifact_jobs.tasks.generate_artifact_job"
DEFAULT_EVALUATION_TASK_NAME = "rag.evaluations.tasks.run_evaluation"
DEFAULT_INGEST_TASK_NAME = "apps.ingestion.tasks.ingest_document"
DEFAULT_GRAPHRAG_INDEX_TASK_NAME = "apps.ingestion.tasks.index_document_graphrag"
DEFAULT_GRAPHRAG_PARTITION_REBUILD_TASK_NAME = (
    "apps.ingestion.tasks.rebuild_graphrag_partition"
)

REEXTRACT_DOCUMENT_METADATA_TASK_NAME = (
    "apps.ingestion.tasks.reextract_document_metadata"
)
REEXTRACT_DOCUMENT_TOPICS_TASK_NAME = "apps.ingestion.tasks.reextract_document_topics"
REEXTRACT_DOCUMENT_CLAIMS_TASK_NAME = "apps.ingestion.tasks.reextract_document_claims"
REEXTRACT_DOCUMENT_TYPE_TASK_NAME = "apps.ingestion.tasks.reextract_document_type"


def normalize_task_name(setting_name: str, value: str) -> str:
    """Return a non-empty task identifier or fail at process startup."""

    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{setting_name} must not be empty")
    if normalized == "celery" or normalized.startswith("celery."):
        raise ValueError(f"{setting_name} must not use Celery's reserved task namespace")
    return normalized


def validate_document_pipeline_task_names(
    *,
    ingest: str,
    graphrag_index: str,
    graphrag_partition_rebuild: str,
) -> None:
    """Reject names that would bind different document workflows to one task."""

    names_by_owner = {
        "ingest": {DEFAULT_INGEST_TASK_NAME, ingest},
        "graphrag_index": {
            DEFAULT_GRAPHRAG_INDEX_TASK_NAME,
            graphrag_index,
        },
        "graphrag_partition_rebuild": {
            DEFAULT_GRAPHRAG_PARTITION_REBUILD_TASK_NAME,
            graphrag_partition_rebuild,
        },
        "reextract_metadata": {REEXTRACT_DOCUMENT_METADATA_TASK_NAME},
        "reextract_topics": {REEXTRACT_DOCUMENT_TOPICS_TASK_NAME},
        "reextract_claims": {REEXTRACT_DOCUMENT_CLAIMS_TASK_NAME},
        "reextract_type": {REEXTRACT_DOCUMENT_TYPE_TASK_NAME},
    }
    owner_by_name: dict[str, str] = {}
    for owner, names in names_by_owner.items():
        for name in names:
            previous_owner = owner_by_name.setdefault(name, owner)
            if previous_owner != owner:
                raise ValueError(
                    "document pipeline task name collision: "
                    f"{name!r} is assigned to {previous_owner} and {owner}"
                )
