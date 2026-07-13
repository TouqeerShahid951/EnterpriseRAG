"""Static checks for backend dependency direction."""

import ast
from collections.abc import Callable, Iterable
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = BACKEND_ROOT.parent
SRC_ROOT = BACKEND_ROOT / "src"
RAG_ROOT = BACKEND_ROOT / "src" / "rag"

BACKEND_PYTHON_ROOTS = (
    BACKEND_ROOT / "apps",
    BACKEND_ROOT / "src",
    BACKEND_ROOT / "tests",
)
NON_RAG_PYTHON_ROOTS = (
    BACKEND_ROOT / "apps",
    BACKEND_ROOT / "tests",
)
HTTP_ROUTE_METHODS = frozenset(
    {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
)
HTTP_BOUNDARY_SUPPORT_FILES = frozenset(
    {
        RAG_ROOT / "query" / "route_access.py",
    }
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
FOLDER_APPLICATION_FILES = (
    RAG_ROOT / "ingestion" / "folders" / "dispatch.py",
    RAG_ROOT / "ingestion" / "folders" / "service.py",
    RAG_ROOT / "ingestion" / "folders" / "scheduling.py",
    RAG_ROOT / "ingestion" / "folders" / "sources.py",
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
ARTIFACT_APPLICATION_FILES = (
    RAG_ROOT / "artifact_jobs" / "cleanup.py",
    RAG_ROOT / "artifact_jobs" / "publisher.py",
    RAG_ROOT / "artifact_jobs" / "queue.py",
    RAG_ROOT / "artifact_jobs" / "service.py",
    RAG_ROOT / "artifact_jobs" / "storage.py",
    RAG_ROOT / "artifact_jobs" / "task_execution.py",
)
ARTIFACT_SUBMISSION_FILE = RAG_ROOT / "artifact_jobs" / "submission.py"
EXPECTED_FEATURE_HTTP_HANDLER_OWNERS = {
    "list_documents": "rag.documents.routes",
    "get_document": "rag.documents.routes",
    "get_document_shares": "rag.documents.routes",
    "transfer_document_owner": "rag.documents.routes",
    "replace_document_shares": "rag.documents.routes",
    "unshare_document": "rag.documents.routes",
    "get_document_content": "rag.documents.routes",
    "get_document_image_asset_content": "rag.documents.routes",
    "get_document_source": "rag.documents.routes",
    "get_document_versions": "rag.documents.routes",
    "update_document_clearance": "rag.documents.routes",
    "update_document_topics": "rag.documents.routes",
    "supersede_documents": "rag.documents.routes",
    "restore_document": "rag.documents.routes",
    "delete_document": "rag.documents.routes",
    "permanently_delete_document": "rag.documents.routes",
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
    violations = _find_violations(
        RAG_ROOT.rglob("*.py"),
        lambda target: target == "apps" or target.startswith("apps."),
    )

    _assert_no_violations(violations)


def test_routes_do_not_import_concrete_adapters() -> None:
    route_modules = (
        path
        for path in RAG_ROOT.rglob("*.py")
        if _is_route_module(path) or path in HTTP_BOUNDARY_SUPPORT_FILES
    )
    violations = _find_violations(route_modules, _is_concrete_adapter_module)

    _assert_no_violations(violations)


def test_feature_http_handlers_have_exactly_one_owner() -> None:
    assert len(EXPECTED_FEATURE_HTTP_HANDLER_OWNERS) == 49

    actual_owners: dict[str, list[str]] = {
        name: [] for name in EXPECTED_FEATURE_HTTP_HANDLER_OWNERS
    }
    for path in sorted(RAG_ROOT.rglob("*.py")):
        if not _is_route_module(path):
            continue
        module = _module_name(path)
        for name in _http_handler_names(path):
            if name in actual_owners:
                actual_owners[name].append(module)

    assert {name: tuple(sorted(owners)) for name, owners in actual_owners.items()} == {
        name: (owner,) for name, owner in EXPECTED_FEATURE_HTTP_HANDLER_OWNERS.items()
    }


def test_legacy_feature_route_modules_are_absent_and_not_imported() -> None:
    assert not any(path.exists() for path in LEGACY_FEATURE_ROUTE_FILES)

    violations = _find_violations(
        _python_files(BACKEND_PYTHON_ROOTS),
        lambda target: target in LEGACY_FEATURE_ROUTE_MODULES,
    )

    _assert_no_violations(violations)


def test_legacy_graphrag_queue_module_is_absent_and_not_imported() -> None:
    assert not any(path.exists() for path in LEGACY_GRAPHRAG_QUEUE_PATHS)

    violations = _find_violations(
        RAG_ROOT.rglob("*.py"),
        _is_legacy_graphrag_queue_module,
        resolve_relative_imports=True,
    )
    violations.extend(
        _find_violations(
            _python_files(NON_RAG_PYTHON_ROOTS),
            _is_legacy_graphrag_queue_module,
        )
    )

    _assert_no_violations(violations)


def test_legacy_folder_ingestion_modules_are_absent_and_not_imported() -> None:
    assert not any(path.exists() for path in LEGACY_FOLDER_INGESTION_PATHS)

    violations = _find_violations(
        RAG_ROOT.rglob("*.py"),
        _is_legacy_folder_ingestion_module,
        resolve_relative_imports=True,
    )
    violations.extend(
        _find_violations(
            _python_files(NON_RAG_PYTHON_ROOTS),
            _is_legacy_folder_ingestion_module,
        )
    )

    _assert_no_violations(violations)


def test_legacy_artifact_modules_are_absent_and_not_imported() -> None:
    assert not any(path.exists() for path in LEGACY_ARTIFACT_PATHS)

    violations = _find_violations(
        _python_files(BACKEND_PYTHON_ROOTS),
        lambda target: target in LEGACY_ARTIFACT_MODULES,
        resolve_relative_imports=True,
    )

    _assert_no_violations(violations)


def test_legacy_query_modules_are_absent_and_not_imported() -> None:
    assert not any(path.exists() for path in LEGACY_QUERY_PATHS)

    violations = _find_violations(
        _python_files(BACKEND_PYTHON_ROOTS),
        lambda target: target in LEGACY_QUERY_MODULES,
        resolve_relative_imports=True,
    )

    _assert_no_violations(violations)


def test_query_schemas_are_transport_and_runtime_independent() -> None:
    violations = _find_violations(
        (RAG_ROOT / "query" / "schemas.py",),
        lambda target: (
            target == "fastapi"
            or target.startswith("fastapi.")
            or target == "rag.core.config"
            or target.startswith("rag.query.adapters.")
            or target in {
                "rag.query.routes",
                "rag.query.execution_routes",
                "rag.query.history_routes",
                "rag.query.source_routes",
                "rag.query.service",
            }
        ),
        resolve_relative_imports=True,
    )

    _assert_no_violations(violations)


def test_artifact_jobs_do_not_import_query_schemas() -> None:
    violations = _find_violations(
        (RAG_ROOT / "artifact_jobs").rglob("*.py"),
        lambda target: target == "rag.query.schemas"
        or target.startswith("rag.query.schemas."),
        resolve_relative_imports=True,
    )

    _assert_no_violations(violations)


def test_artifact_submission_contract_is_dependency_light() -> None:
    violations = _find_violations(
        (ARTIFACT_SUBMISSION_FILE,),
        lambda target: (
            target == "fastapi"
            or target.startswith("fastapi.")
            or target == "celery"
            or target.startswith("celery.")
            or target == "rag.core.config"
            or target.startswith("rag.artifact_jobs.adapters.")
            or target == "rag.query"
            or target.startswith("rag.query.")
            or target == "rag.documents"
            or target.startswith("rag.documents.")
        ),
        resolve_relative_imports=True,
    )

    _assert_no_violations(violations)


def test_artifact_application_code_is_transport_and_settings_independent() -> None:
    violations = _find_violations(
        ARTIFACT_APPLICATION_FILES,
        lambda target: (
            target == "celery"
            or target.startswith("celery.")
            or target == "fastapi"
            or target.startswith("fastapi.")
            or target == "rag.core.config"
            or target.startswith("rag.artifact_jobs.adapters.")
        ),
        resolve_relative_imports=True,
    )

    _assert_no_violations(violations)


def test_folder_application_code_is_transport_and_settings_independent() -> None:
    violations = _find_violations(
        FOLDER_APPLICATION_FILES,
        lambda target: (
            target == "fastapi"
            or target.startswith("fastapi.")
            or target == "rag.core.config"
        ),
        resolve_relative_imports=True,
    )

    _assert_no_violations(violations)


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
        assert LEGACY_GRAPHRAG_QUEUE_MODULE in _resolved_rag_import_targets(
            source_path,
            legacy_import,
        )
        assert LEGACY_GRAPHRAG_QUEUE_MODULE not in _resolved_rag_import_targets(
            source_path,
            unrelated_import,
        )


def test_deployment_controller_uses_backend_composition_root() -> None:
    assert (BACKEND_ROOT / "apps" / "deployment_controller" / "main.py").is_file()
    assert not (REPOSITORY_ROOT / "deployment-controller").exists()


def _find_violations(
    paths: Iterable[Path],
    is_forbidden: Callable[[str], bool],
    *,
    resolve_relative_imports: bool = False,
) -> list[str]:
    violations: list[str] = []
    for path in sorted(paths):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            targets = (
                _resolved_rag_import_targets(path, node)
                if resolve_relative_imports
                else _import_targets(node)
            )
            if any(is_forbidden(target) for target in targets):
                statement = ast.get_source_segment(source, node) or "<unknown import>"
                statement = " ".join(statement.split())
                relative_path = path.relative_to(BACKEND_ROOT)
                violations.append(f"{relative_path}:{node.lineno} -> {statement}")
    return violations


def _python_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        yield from root.rglob("*.py")


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(SRC_ROOT).with_suffix("").parts)


def _http_handler_names(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tuple(
        node.name
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and any(_is_http_route_decorator(item) for item in node.decorator_list)
    )


def _is_http_route_decorator(node: ast.expr) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    return isinstance(target, ast.Attribute) and target.attr in HTTP_ROUTE_METHODS


def _import_targets(node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)

    module = f"{'.' * node.level}{node.module or ''}"
    targets = [module] if module else []
    targets.extend(
        f"{module}.{alias.name}" if module else alias.name
        for alias in node.names
        if alias.name != "*"
    )
    return tuple(targets)


def _resolved_rag_import_targets(
    path: Path,
    node: ast.Import | ast.ImportFrom,
) -> tuple[str, ...]:
    if isinstance(node, ast.Import) or node.level == 0:
        return _import_targets(node)

    package_parts = _module_name(path).split(".")
    package_parts.pop()
    parent_count = node.level - 1
    if parent_count > len(package_parts):
        return _import_targets(node)
    if parent_count:
        package_parts = package_parts[:-parent_count]
    if node.module:
        package_parts.extend(node.module.split("."))
    module = ".".join(package_parts)
    targets = [module] if module else []
    targets.extend(
        f"{module}.{alias.name}" if module else alias.name
        for alias in node.names
        if alias.name != "*"
    )
    return tuple(targets)


def _is_legacy_graphrag_queue_module(target: str) -> bool:
    return target == LEGACY_GRAPHRAG_QUEUE_MODULE or target.startswith(
        f"{LEGACY_GRAPHRAG_QUEUE_MODULE}."
    )


def _is_legacy_folder_ingestion_module(target: str) -> bool:
    return any(
        target == module or target.startswith(f"{module}.")
        for module in LEGACY_FOLDER_INGESTION_MODULES
    )


def _is_route_module(path: Path) -> bool:
    relative_parts = path.relative_to(RAG_ROOT).parts
    return path.name != "__init__.py" and (
        "routes" in relative_parts
        or path.name == "routes.py"
        or path.stem.endswith("_routes")
    )


def _is_concrete_adapter_module(module: str) -> bool:
    segments = module.split(".")
    return "adapters" in segments or any(
        segment.endswith(("_postgres", "_memory")) for segment in segments
    )


def _assert_no_violations(violations: list[str]) -> None:
    details = "\n".join(f"- {violation}" for violation in violations)
    assert not violations, f"Architecture dependency violations:\n{details}"
