"""Dependency boundaries for Celery worker composition adapters."""

from _dependency_scanner import (
    BACKEND_PYTHON_ROOTS,
    BACKEND_ROOT,
    RAG_ROOT,
    assert_no_violations,
    find_violations,
    python_files,
)


ARTIFACT_WORKER_TASK_FILE = BACKEND_ROOT / "apps" / "workers" / "artifact" / "tasks.py"
REMOVED_ARTIFACT_TASK_MODULE = "rag.artifact_jobs.tasks"
REMOVED_ARTIFACT_TASK_PATHS = (
    RAG_ROOT / "artifact_jobs" / "tasks.py",
    RAG_ROOT / "artifact_jobs" / "tasks",
)
EVALUATION_WORKER_TASK_FILE = (
    BACKEND_ROOT / "apps" / "workers" / "evaluation" / "tasks.py"
)
REMOVED_EVALUATION_TASK_MODULE = "rag.evaluations.tasks"
REMOVED_EVALUATION_TASK_PATHS = (
    RAG_ROOT / "evaluations" / "tasks.py",
    RAG_ROOT / "evaluations" / "tasks",
)
DOCUMENT_PIPELINE_WORKER_TASK_FILE = (
    BACKEND_ROOT / "apps" / "workers" / "document_pipeline" / "tasks.py"
)
REMOVED_DOCUMENT_PIPELINE_TASK_MODULES = frozenset(
    {"rag.ingestion.tasks", "rag.graphrag.tasks"}
)
REMOVED_DOCUMENT_PIPELINE_TASK_PATHS = (
    RAG_ROOT / "ingestion" / "tasks.py",
    RAG_ROOT / "ingestion" / "tasks",
    RAG_ROOT / "graphrag" / "tasks.py",
    RAG_ROOT / "graphrag" / "tasks",
)
TASK_NAMES_CONTRACT_FILE = RAG_ROOT / "shared" / "contracts" / "task_names.py"


def test_artifact_celery_adapter_is_owned_by_worker_app() -> None:
    assert ARTIFACT_WORKER_TASK_FILE.is_file()
    assert not any(path.exists() for path in REMOVED_ARTIFACT_TASK_PATHS)

    violations = find_violations(
        python_files(BACKEND_PYTHON_ROOTS),
        lambda target: (
            target == REMOVED_ARTIFACT_TASK_MODULE
            or target.startswith(f"{REMOVED_ARTIFACT_TASK_MODULE}.")
        ),
        resolve_relative_imports=True,
    )
    violations.extend(
        find_violations(
            (RAG_ROOT / "artifact_jobs").rglob("*.py"),
            lambda target: target == "celery.shared_task",
            resolve_relative_imports=True,
        )
    )

    assert_no_violations(violations)


def test_artifact_worker_task_adapter_has_only_composition_dependencies() -> None:
    allowed_imports = frozenset(
        {
            "__future__",
            "__future__.annotations",
            "apps.workers.artifact.celery_app",
            "apps.workers.artifact.celery_app.celery_app",
            "billiard.exceptions",
            "billiard.exceptions.SoftTimeLimitExceeded",
            "rag.artifact_jobs.dependencies",
            "rag.artifact_jobs.dependencies.get_artifact_context_validator",
            "rag.artifact_jobs.dependencies.get_artifact_job_executor",
            "rag.artifact_jobs.dependencies.get_artifact_job_repository",
            "rag.artifact_jobs.task_execution",
            "rag.artifact_jobs.task_execution.ArtifactDeliveryRetry",
            "rag.artifact_jobs.task_execution.run_artifact_job",
            "rag.core.config",
            "rag.core.config.settings",
            "rag.shared.contracts.task_names",
            "rag.shared.contracts.task_names.DEFAULT_ARTIFACT_TASK_NAME",
            "typing",
            "typing.Any",
        }
    )
    violations = find_violations(
        (ARTIFACT_WORKER_TASK_FILE,),
        lambda target: target not in allowed_imports,
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_evaluation_celery_adapter_is_owned_by_worker_app() -> None:
    assert EVALUATION_WORKER_TASK_FILE.is_file()
    assert not any(path.exists() for path in REMOVED_EVALUATION_TASK_PATHS)

    violations = find_violations(
        python_files(BACKEND_PYTHON_ROOTS),
        lambda target: (
            target == REMOVED_EVALUATION_TASK_MODULE
            or target.startswith(f"{REMOVED_EVALUATION_TASK_MODULE}.")
        ),
        resolve_relative_imports=True,
    )
    violations.extend(
        find_violations(
            (RAG_ROOT / "evaluations").rglob("*.py"),
            lambda target: target == "celery.shared_task",
            resolve_relative_imports=True,
        )
    )

    assert_no_violations(violations)


def test_evaluation_worker_task_adapter_has_only_composition_dependencies() -> None:
    allowed_imports = frozenset(
        {
            "__future__",
            "__future__.annotations",
            "apps.workers.evaluation.celery_app",
            "apps.workers.evaluation.celery_app.celery_app",
            "billiard.exceptions",
            "billiard.exceptions.SoftTimeLimitExceeded",
            "celery.exceptions",
            "celery.exceptions.Reject",
            "rag.core.config",
            "rag.core.config.settings",
            "rag.evaluations.execution",
            "rag.evaluations.execution.EvaluationCaseExecutor",
            "rag.evaluations.execution.default_evaluation_case_executor",
            "rag.evaluations.repository",
            "rag.evaluations.repository.get_evaluation_repository",
            "rag.evaluations.task_execution",
            "rag.evaluations.task_execution.EvaluationDeliveryRetry",
            "rag.evaluations.task_execution.run_evaluation_run",
            "rag.shared.contracts.task_names",
            "rag.shared.contracts.task_names.DEFAULT_EVALUATION_TASK_NAME",
            "typing",
            "typing.Any",
        }
    )
    violations = find_violations(
        (EVALUATION_WORKER_TASK_FILE,),
        lambda target: target not in allowed_imports,
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_document_pipeline_celery_adapters_are_owned_by_worker_app() -> None:
    assert DOCUMENT_PIPELINE_WORKER_TASK_FILE.is_file()
    assert not any(path.exists() for path in REMOVED_DOCUMENT_PIPELINE_TASK_PATHS)

    violations = find_violations(
        python_files(BACKEND_PYTHON_ROOTS),
        lambda target: (
            target in REMOVED_DOCUMENT_PIPELINE_TASK_MODULES
            or any(
                target.startswith(f"{module}.")
                for module in REMOVED_DOCUMENT_PIPELINE_TASK_MODULES
            )
        ),
        resolve_relative_imports=True,
    )
    violations.extend(
        find_violations(
            RAG_ROOT.rglob("*.py"),
            lambda target: target == "celery.shared_task",
            resolve_relative_imports=True,
        )
    )
    violations.extend(
        find_violations(
            (RAG_ROOT / "ingestion" / "execution.py",),
            lambda target: (
                target == "billiard"
                or target.startswith("billiard.")
                or target == "celery"
                or target.startswith("celery.")
            ),
            resolve_relative_imports=True,
        )
    )

    assert_no_violations(violations)


def test_document_pipeline_task_adapter_has_only_composition_dependencies() -> None:
    allowed_imports = frozenset(
        {
            "__future__",
            "__future__.annotations",
            "apps.workers.document_pipeline.celery_app",
            "apps.workers.document_pipeline.celery_app.celery_app",
            "apps.workers.document_pipeline.celery_app.config",
            "billiard.exceptions",
            "billiard.exceptions.SoftTimeLimitExceeded",
            "rag.graphrag.task_execution",
            "rag.graphrag.task_execution.GraphRAGDeliveryRetry",
            "rag.graphrag.task_execution.run_document_graph_index",
            "rag.graphrag.task_execution.run_partition_rebuild",
            "rag.ingestion.execution",
            "rag.ingestion.execution.IngestDeliveryRetry",
            "rag.ingestion.execution.run_ingest_document",
            "rag.shared.contracts.task_names",
            "rag.shared.contracts.task_names.DEFAULT_GRAPHRAG_INDEX_TASK_NAME",
            "rag.shared.contracts.task_names.DEFAULT_GRAPHRAG_PARTITION_REBUILD_TASK_NAME",
            "rag.shared.contracts.task_names.DEFAULT_INGEST_TASK_NAME",
            "rag.shared.contracts.task_names.REEXTRACT_DOCUMENT_CLAIMS_TASK_NAME",
            "rag.shared.contracts.task_names.REEXTRACT_DOCUMENT_METADATA_TASK_NAME",
            "rag.shared.contracts.task_names.REEXTRACT_DOCUMENT_TOPICS_TASK_NAME",
            "rag.shared.contracts.task_names.REEXTRACT_DOCUMENT_TYPE_TASK_NAME",
            "typing",
            "typing.Any",
            "typing.Callable",
            "uuid",
            "uuid.uuid4",
        }
    )
    violations = find_violations(
        (DOCUMENT_PIPELINE_WORKER_TASK_FILE,),
        lambda target: target not in allowed_imports,
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_worker_task_name_contract_is_dependency_free() -> None:
    violations = find_violations(
        (TASK_NAMES_CONTRACT_FILE,),
        lambda target: not target.startswith("__future__"),
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)
