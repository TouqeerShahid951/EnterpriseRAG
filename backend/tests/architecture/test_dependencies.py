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
HTTP_ROUTE_METHODS = frozenset(
    {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
)
LEGACY_FEATURE_ROUTE_MODULES = frozenset(
    {
        "rag.api.routes.document_routes",
        "rag.api.routes.ingest_job_routes",
    }
)
LEGACY_FEATURE_ROUTE_FILES = (
    RAG_ROOT / "api" / "routes" / "document_routes.py",
    RAG_ROOT / "api" / "routes" / "ingest_job_routes.py",
)
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
}


def test_rag_package_does_not_import_process_entrypoints() -> None:
    violations = _find_violations(
        RAG_ROOT.rglob("*.py"),
        lambda target: target == "apps" or target.startswith("apps."),
    )

    _assert_no_violations(violations)


def test_routes_do_not_import_concrete_adapters() -> None:
    route_modules = (path for path in RAG_ROOT.rglob("*.py") if _is_route_module(path))
    violations = _find_violations(route_modules, _is_concrete_adapter_module)

    _assert_no_violations(violations)


def test_feature_http_handlers_have_exactly_one_owner() -> None:
    assert len(EXPECTED_FEATURE_HTTP_HANDLER_OWNERS) == 25

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

    assert {
        name: tuple(sorted(owners)) for name, owners in actual_owners.items()
    } == {
        name: (owner,)
        for name, owner in EXPECTED_FEATURE_HTTP_HANDLER_OWNERS.items()
    }


def test_legacy_feature_route_modules_are_absent_and_not_imported() -> None:
    assert not any(path.exists() for path in LEGACY_FEATURE_ROUTE_FILES)

    violations = _find_violations(
        _python_files(BACKEND_PYTHON_ROOTS),
        lambda target: target in LEGACY_FEATURE_ROUTE_MODULES,
    )

    _assert_no_violations(violations)


def test_deployment_controller_uses_backend_composition_root() -> None:
    assert (
        BACKEND_ROOT / "apps" / "deployment_controller" / "main.py"
    ).is_file()
    assert not (REPOSITORY_ROOT / "deployment-controller").exists()


def _find_violations(
    paths: Iterable[Path],
    is_forbidden: Callable[[str], bool],
) -> list[str]:
    violations: list[str] = []
    for path in sorted(paths):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if any(is_forbidden(target) for target in _import_targets(node)):
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


def _is_route_module(path: Path) -> bool:
    relative_parts = path.relative_to(RAG_ROOT).parts
    return (
        path.name != "__init__.py"
        and ("routes" in relative_parts or path.name == "routes.py" or path.stem.endswith("_routes"))
    )


def _is_concrete_adapter_module(module: str) -> bool:
    segments = module.split(".")
    return "adapters" in segments or any(
        segment.endswith(("_postgres", "_memory")) for segment in segments
    )


def _assert_no_violations(violations: list[str]) -> None:
    details = "\n".join(f"- {violation}" for violation in violations)
    assert not violations, f"Architecture dependency violations:\n{details}"
