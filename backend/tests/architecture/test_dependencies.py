"""Application-wide backend dependency-direction checks."""

from _dependency_scanner import (
    BACKEND_ROOT,
    RAG_ROOT,
    REPOSITORY_ROOT,
    assert_no_violations,
    find_violations,
    http_handler_names,
    is_concrete_adapter_module,
    is_route_module,
    module_name,
)


HTTP_BOUNDARY_SUPPORT_FILES = frozenset(
    {
        RAG_ROOT / "query" / "route_access.py",
    }
)
FOLDER_APPLICATION_FILES = (
    RAG_ROOT / "ingestion" / "folders" / "dispatch.py",
    RAG_ROOT / "ingestion" / "folders" / "service.py",
    RAG_ROOT / "ingestion" / "folders" / "scheduling.py",
    RAG_ROOT / "ingestion" / "folders" / "sources.py",
)
EXPECTED_FEATURE_HTTP_HANDLER_OWNERS = {
    "list_documents": "rag.documents.routes.catalog",
    "get_document": "rag.documents.routes.catalog",
    "get_document_shares": "rag.documents.routes.access",
    "transfer_document_owner": "rag.documents.routes.access",
    "replace_document_shares": "rag.documents.routes.access",
    "unshare_document": "rag.documents.routes.access",
    "get_document_content": "rag.documents.routes.content",
    "get_document_image_asset_content": "rag.documents.routes.content",
    "get_document_source": "rag.documents.routes.content",
    "get_document_versions": "rag.documents.routes.catalog",
    "update_document_clearance": "rag.documents.routes.metadata",
    "update_document_topics": "rag.documents.routes.metadata",
    "supersede_documents": "rag.documents.routes.metadata",
    "restore_document": "rag.documents.routes.lifecycle",
    "delete_document": "rag.documents.routes.lifecycle",
    "permanently_delete_document": "rag.documents.routes.lifecycle",
    "reingest_document": "rag.ingestion.document_routes",
    "queue_document_graph_enrichment": "rag.graphrag.document_routes",
    "list_ingest_jobs": "rag.ingestion.job_routes",
    "summarize_ingest_jobs": "rag.ingestion.job_routes",
    "cancel_ingest_job": "rag.ingestion.job_routes",
    "list_stale_jobs": "rag.ingestion.job_routes",
    "requeue_stale_job": "rag.ingestion.job_routes",
    "get_graphrag_status": "rag.graphrag.job_routes",
    "cancel_graph_enrichment": "rag.graphrag.job_routes",
    "list_local_folders": "rag.ingestion.folders.routes",
    "list_folder_schedules": "rag.ingestion.folders.routes",
    "get_folder_schedule": "rag.ingestion.folders.routes",
    "create_snapshot_folder_schedule": "rag.ingestion.folders.routes",
    "create_minio_folder_schedule": "rag.ingestion.folders.routes",
    "create_local_folder_schedule_route": "rag.ingestion.folders.routes",
    "create_connector_folder_schedule": "rag.ingestion.folders.routes",
    "reschedule_folder_schedule": "rag.ingestion.folders.routes",
    "pause_folder_schedule": "rag.ingestion.folders.routes",
    "resume_folder_schedule": "rag.ingestion.folders.routes",
    "cancel_folder_schedule": "rag.ingestion.folders.routes",
    "list_folder_runs": "rag.ingestion.folders.routes",
    "list_folder_run_items": "rag.ingestion.folders.routes",
    "get_generated_artifact_content": "rag.artifact_jobs.routes",
    "get_artifact_job": "rag.artifact_jobs.routes",
    "clarify_artifact_job": "rag.artifact_jobs.routes",
    "cancel_artifact_job": "rag.artifact_jobs.routes",
    "retry_artifact_job": "rag.artifact_jobs.routes",
    "list_chat_sessions": "rag.query.history_routes",
    "get_chat_session": "rag.query.history_routes",
    "delete_chat_session": "rag.query.history_routes",
    "list_query_sources": "rag.query.source_routes",
    "run_query": "rag.query.execution_routes",
    "stream_query": "rag.query.execution_routes",
}


def test_rag_package_does_not_import_process_entrypoints() -> None:
    violations = find_violations(
        RAG_ROOT.rglob("*.py"),
        lambda target: target == "apps" or target.startswith("apps."),
    )

    assert_no_violations(violations)


def test_routes_do_not_import_concrete_adapters() -> None:
    route_modules = (
        path
        for path in RAG_ROOT.rglob("*.py")
        if is_route_module(path) or path in HTTP_BOUNDARY_SUPPORT_FILES
    )
    violations = find_violations(route_modules, is_concrete_adapter_module)

    assert_no_violations(violations)


def test_feature_http_handlers_have_exactly_one_owner() -> None:
    assert len(EXPECTED_FEATURE_HTTP_HANDLER_OWNERS) == 49

    actual_owners: dict[str, list[str]] = {
        name: [] for name in EXPECTED_FEATURE_HTTP_HANDLER_OWNERS
    }
    for path in sorted(RAG_ROOT.rglob("*.py")):
        if not is_route_module(path):
            continue
        module = module_name(path)
        for name in http_handler_names(path):
            if name in actual_owners:
                actual_owners[name].append(module)

    assert {name: tuple(sorted(owners)) for name, owners in actual_owners.items()} == {
        name: (owner,) for name, owner in EXPECTED_FEATURE_HTTP_HANDLER_OWNERS.items()
    }


def test_folder_application_code_is_transport_and_settings_independent() -> None:
    violations = find_violations(
        FOLDER_APPLICATION_FILES,
        lambda target: (
            target == "fastapi"
            or target.startswith("fastapi.")
            or target == "rag.core.config"
        ),
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_deployment_controller_uses_backend_composition_root() -> None:
    assert (BACKEND_ROOT / "apps" / "deployment_controller" / "main.py").is_file()
    assert not (REPOSITORY_ROOT / "deployment-controller").exists()
