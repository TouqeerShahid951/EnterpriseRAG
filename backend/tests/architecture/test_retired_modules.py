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
        "rag.artifact_jobs.bundle_repair",
        "rag.artifact_jobs.composer",
        "rag.artifact_jobs.composition",
        "rag.artifact_jobs.composition_deadline",
        "rag.artifact_jobs.execution_errors",
        "rag.artifact_jobs.execution_progress",
        "rag.artifact_jobs.execution_rendering",
        "rag.artifact_jobs.execution_state",
        "rag.artifact_jobs.fallback_composition",
        "rag.artifact_jobs.format_adaptation",
        "rag.artifact_jobs.layout_profiles",
        "rag.artifact_jobs.llm_json",
        "rag.artifact_jobs.planner",
        "rag.artifact_jobs.validation",
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

RETIRED_BUCKET_PREFIXES = frozenset({"rag.api", "rag.schemas", "rag.services"})
REORGANIZED_MODULES = frozenset(
    {
        "rag.connectors.catalog_routes",
        "rag.connectors.enrichment_routes",
        "rag.connectors.http_presenters",
        "rag.connectors.profile_routes",
        "rag.connectors.route_support",
        "rag.connectors.row_mapping",
        "rag.connectors.schema_catalog",
        "rag.connectors.schema_enrichment",
        "rag.connectors.schema_introspection",
        "rag.documents.access_scope_dependencies",
        "rag.documents.access_scope_ports",
        "rag.documents.access_scope_service",
        "rag.documents.lifecycle_dependencies",
        "rag.documents.lifecycle_ports",
        "rag.documents.lifecycle_service",
        "rag.documents.metadata_dependencies",
        "rag.documents.metadata_ports",
        "rag.documents.metadata_service",
        "rag.documents.reingestion_dependencies",
        "rag.documents.reingestion_service",
        "rag.documents.routes.access",
        "rag.documents.routes.lifecycle",
        "rag.documents.routes.metadata",
        "rag.documents.upload_routes",
        "rag.documents.upload_schemas",
        "rag.documents.upload_service",
        "rag.documents.upload_status",
        "rag.documents.upload_validation",
        "rag.ingestion.parsers.docling_adapter",
        "rag.ingestion.parsers.docling_models",
        "rag.ingestion.parsers.docling_repairs",
        "rag.ingestion.parsers.image_analysis",
        "rag.ingestion.parsers.image_contracts",
        "rag.ingestion.parsers.image_normalization",
        "rag.ingestion.parsers.image_sources",
        "rag.ingestion.parsers.inspect_pdf",
        "rag.ingestion.parsers.layered",
        "rag.ingestion.parsers.pdf_fallback",
        "rag.ingestion.parsers.pdf_image_candidates",
        "rag.ingestion.parsers.pdf_image_processing",
        "rag.ingestion.parsers.pdf_layout_repair",
        "rag.ingestion.parsers.pdf_visual_component_detection",
        "rag.ingestion.parsers.pdf_visual_page_selection",
        "rag.ingestion.parsers.pdf_visual_region_detection",
        "rag.ingestion.parsers.pdf_visual_region_geometry",
        "rag.ingestion.parsers.pdf_visual_regions",
        "rag.ingestion.parsers.pdf_visual_source_mapping",
        "rag.ingestion.parsers.pymupdf",
        "rag.ingestion.configuration_dependencies",
        "rag.ingestion.human_review_routes",
        "rag.ingestion.image_review_routes",
        "rag.ingestion.review_access",
        "rag.ingestion.review_dependencies",
        "rag.ingestion.review_models",
        "rag.ingestion.review_presenters",
        "rag.ingestion.review_routes",
        "rag.query.adapters.vllm_config_memory",
        "rag.query.adapters.vllm_config_postgres",
        "rag.query.conflicts",
        "rag.query.evidence_quality",
        "rag.query.faithfulness",
        "rag.query.intent_router",
        "rag.query.live_sql",
        "rag.query.metadata_scoring",
        "rag.query.query_intent",
        "rag.query.query_retrieval",
        "rag.query.rag_config_http_mapping",
        "rag.query.rag_config_mapping",
        "rag.query.rag_config_models",
        "rag.query.rag_config_repository",
        "rag.query.rag_config_routes",
        "rag.query.rag_config_service",
        "rag.query.rag_config_validation",
        "rag.query.reasoning",
        "rag.query.retrieval_budget",
        "rag.query.retrieval_document_scope",
        "rag.query.retrieval_hits",
        "rag.query.retrieval_plans",
        "rag.query.retrieval_policy",
        "rag.query.retrieval_recall",
        "rag.query.retrieval_structured",
        "rag.query.retrieval_trace",
        "rag.query.routing_evidence",
        "rag.query.routing_logs",
        "rag.query.routing_models",
        "rag.query.routing_rules",
        "rag.query.routing_signals",
        "rag.query.routing_verifier",
        "rag.query.source_advisory",
        "rag.query.source_catalog",
        "rag.query.source_context_budget",
        "rag.query.source_evidence_selection",
        "rag.query.source_mapping",
        "rag.query.source_matching",
        "rag.query.source_parent_promotion",
        "rag.query.source_resolution",
        "rag.query.source_routes",
        "rag.query.synthesis",
        "rag.query.temporal",
        "rag.query.vllm_config_models",
        "rag.query.vllm_config_repository",
    }
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


def test_reorganized_modules_cannot_return_to_retired_locations() -> None:
    retired_bucket_paths = tuple(
        RAG_ROOT.joinpath(*module.split(".")[1:])
        for module in RETIRED_BUCKET_PREFIXES
    )
    reorganized_paths = tuple(
        RAG_ROOT.joinpath(*module.split(".")[1:]).with_suffix(".py")
        for module in REORGANIZED_MODULES
    )
    assert not any(path.exists() for path in (*retired_bucket_paths, *reorganized_paths))

    violations = find_violations(
        python_files(BACKEND_PYTHON_ROOTS),
        lambda target: any(
            target == prefix or target.startswith(f"{prefix}.")
            for prefix in RETIRED_BUCKET_PREFIXES
        )
        or any(
            target == module or target.startswith(f"{module}.")
            for module in REORGANIZED_MODULES
        ),
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
