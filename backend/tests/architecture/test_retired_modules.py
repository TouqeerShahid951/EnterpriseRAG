"""Checks that retired backend modules cannot re-enter the dependency graph."""

import ast

from _dependency_scanner import (
    BACKEND_PYTHON_ROOTS,
    NON_RAG_PYTHON_ROOTS,
    RAG_ROOT,
    assert_no_violations,
    find_violations,
    python_files,
    resolved_rag_import_targets,
)


LEGACY_FEATURE_ROUTE_MODULES = frozenset(
    {
        "rag.api.routes.document_routes",
        "rag.api.routes.folder_ingest_routes",
        "rag.api.routes.ingest_job_routes",
    }
)
LEGACY_FEATURE_ROUTE_FILES = (
    RAG_ROOT / "api" / "routes" / "document_routes.py",
    RAG_ROOT / "api" / "routes" / "folder_ingest_routes.py",
    RAG_ROOT / "api" / "routes" / "ingest_job_routes.py",
)
LEGACY_FOLDER_INGESTION_MODULES = frozenset(
    {
        "rag.api.routes.folder_ingest_routes",
        "rag.schemas.folder_ingest",
        "rag.services.folder_ingestion",
        "rag.services.folder_schedule_time",
        "rag.services.folder_sources",
        "rag.services.document_uploads",
        "rag.ingestion.folder_config",
        "rag.ingestion.folder_dependencies",
        "rag.ingestion.folder_dispatch",
        "rag.ingestion.folder_errors",
        "rag.ingestion.folder_schedule_dependencies",
        "rag.ingestion.folder_schedule_models",
        "rag.ingestion.folder_schedule_routes",
        "rag.ingestion.folder_schedule_schemas",
        "rag.ingestion.folder_schedule_service",
        "rag.ingestion.folder_schedule_time",
        "rag.ingestion.folder_sources",
        "rag.ingestion.adapters.folder_schedule_memory",
        "rag.ingestion.adapters.folder_schedule_postgres",
        "rag.ingestion.adapters.folder_sources",
    }
)
LEGACY_FOLDER_INGESTION_PATHS = (
    RAG_ROOT / "api" / "routes" / "folder_ingest_routes.py",
    RAG_ROOT / "schemas" / "folder_ingest.py",
    RAG_ROOT / "services" / "folder_ingestion.py",
    RAG_ROOT / "services" / "folder_schedule_time.py",
    RAG_ROOT / "services" / "folder_sources.py",
    RAG_ROOT / "services" / "document_uploads.py",
    RAG_ROOT / "ingestion" / "folder_config.py",
    RAG_ROOT / "ingestion" / "folder_dependencies.py",
    RAG_ROOT / "ingestion" / "folder_dispatch.py",
    RAG_ROOT / "ingestion" / "folder_errors.py",
    RAG_ROOT / "ingestion" / "folder_schedule_dependencies.py",
    RAG_ROOT / "ingestion" / "folder_schedule_models.py",
    RAG_ROOT / "ingestion" / "folder_schedule_routes.py",
    RAG_ROOT / "ingestion" / "folder_schedule_schemas.py",
    RAG_ROOT / "ingestion" / "folder_schedule_service.py",
    RAG_ROOT / "ingestion" / "folder_schedule_time.py",
    RAG_ROOT / "ingestion" / "folder_sources.py",
    RAG_ROOT / "ingestion" / "adapters" / "folder_schedule_memory.py",
    RAG_ROOT / "ingestion" / "adapters" / "folder_schedule_postgres.py",
    RAG_ROOT / "ingestion" / "adapters" / "folder_sources.py",
)
LEGACY_GRAPHRAG_QUEUE_MODULE = "rag.services.graphrag_queue"
LEGACY_GRAPHRAG_QUEUE_PATHS = (
    RAG_ROOT / "services" / "graphrag_queue.py",
    RAG_ROOT / "services" / "graphrag_queue",
)
LEGACY_ARTIFACT_MODULES = frozenset(
    {
        "rag.api.routes.artifact_job_routes",
        "rag.schemas.artifact_jobs",
        "rag.services.generated_artifact_cleanup",
        "rag.services.generated_artifact_storage",
        "rag.artifact_jobs.generated_repository",
        "rag.artifact_jobs.repository",
    }
)
LEGACY_ARTIFACT_PATHS = (
    RAG_ROOT / "api" / "routes" / "artifact_job_routes.py",
    RAG_ROOT / "schemas" / "artifact_jobs.py",
    RAG_ROOT / "services" / "generated_artifact_cleanup.py",
    RAG_ROOT / "services" / "generated_artifact_storage.py",
    RAG_ROOT / "artifact_jobs" / "generated_repository.py",
    RAG_ROOT / "artifact_jobs" / "repository.py",
)
LEGACY_QUERY_MODULES = frozenset(
    {
        "rag.api.routes.query_routes",
        "rag.schemas.query",
    }
)
LEGACY_QUERY_PATHS = (
    RAG_ROOT / "api" / "routes" / "query_routes.py",
    RAG_ROOT / "schemas" / "query.py",
)


def test_legacy_feature_route_modules_are_absent_and_not_imported() -> None:
    assert not any(path.exists() for path in LEGACY_FEATURE_ROUTE_FILES)

    violations = find_violations(
        python_files(BACKEND_PYTHON_ROOTS),
        lambda target: target in LEGACY_FEATURE_ROUTE_MODULES,
    )

    assert_no_violations(violations)


def test_legacy_graphrag_queue_module_is_absent_and_not_imported() -> None:
    assert not any(path.exists() for path in LEGACY_GRAPHRAG_QUEUE_PATHS)

    violations = find_violations(
        RAG_ROOT.rglob("*.py"),
        _is_legacy_graphrag_queue_module,
        resolve_relative_imports=True,
    )
    violations.extend(
        find_violations(
            python_files(NON_RAG_PYTHON_ROOTS),
            _is_legacy_graphrag_queue_module,
        )
    )

    assert_no_violations(violations)


def test_legacy_folder_ingestion_modules_are_absent_and_not_imported() -> None:
    assert not any(path.exists() for path in LEGACY_FOLDER_INGESTION_PATHS)

    violations = find_violations(
        RAG_ROOT.rglob("*.py"),
        _is_legacy_folder_ingestion_module,
        resolve_relative_imports=True,
    )
    violations.extend(
        find_violations(
            python_files(NON_RAG_PYTHON_ROOTS),
            _is_legacy_folder_ingestion_module,
        )
    )

    assert_no_violations(violations)


def test_legacy_artifact_modules_are_absent_and_not_imported() -> None:
    assert not any(path.exists() for path in LEGACY_ARTIFACT_PATHS)

    violations = find_violations(
        python_files(BACKEND_PYTHON_ROOTS),
        lambda target: target in LEGACY_ARTIFACT_MODULES,
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_legacy_query_modules_are_absent_and_not_imported() -> None:
    assert not any(path.exists() for path in LEGACY_QUERY_PATHS)

    violations = find_violations(
        python_files(BACKEND_PYTHON_ROOTS),
        lambda target: target in LEGACY_QUERY_MODULES,
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_relative_import_resolution_distinguishes_the_legacy_queue() -> None:
    legacy_import = ast.parse(
        "from ..services.graphrag_queue import GraphRAGMaintenanceQueue"
    ).body[0]
    unrelated_import = ast.parse(
        "from .services.graphrag_queue import GraphRAGMaintenanceQueue"
    ).body[0]
    assert isinstance(legacy_import, ast.ImportFrom)
    assert isinstance(unrelated_import, ast.ImportFrom)
    source_paths = (
        RAG_ROOT / "documents" / "dependencies.py",
        RAG_ROOT / "documents" / "__init__.py",
    )

    for source_path in source_paths:
        assert LEGACY_GRAPHRAG_QUEUE_MODULE in resolved_rag_import_targets(
            source_path,
            legacy_import,
        )
        assert LEGACY_GRAPHRAG_QUEUE_MODULE not in resolved_rag_import_targets(
            source_path,
            unrelated_import,
        )


def _is_legacy_graphrag_queue_module(target: str) -> bool:
    return target == LEGACY_GRAPHRAG_QUEUE_MODULE or target.startswith(
        f"{LEGACY_GRAPHRAG_QUEUE_MODULE}."
    )


def _is_legacy_folder_ingestion_module(target: str) -> bool:
    return any(
        target == module or target.startswith(f"{module}.")
        for module in LEGACY_FOLDER_INGESTION_MODULES
    )
