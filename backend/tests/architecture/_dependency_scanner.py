"""Shared AST helpers for backend architecture dependency tests."""

import ast
from collections.abc import Callable, Iterable
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = BACKEND_ROOT.parent
SRC_ROOT = BACKEND_ROOT / "src"
RAG_ROOT = SRC_ROOT / "rag"

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


def find_violations(
    paths: Iterable[Path],
    is_forbidden: Callable[[str], bool],
    *,
    resolve_relative_imports: bool = False,
) -> list[str]:
    """Return source locations whose imports match the forbidden predicate."""
    violations: list[str] = []
    for path in sorted(paths):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            targets = (
                resolved_rag_import_targets(path, node)
                if resolve_relative_imports
                else import_targets(node)
            )
            if any(is_forbidden(target) for target in targets):
                statement = ast.get_source_segment(source, node) or "<unknown import>"
                statement = " ".join(statement.split())
                relative_path = path.relative_to(BACKEND_ROOT)
                violations.append(f"{relative_path}:{node.lineno} -> {statement}")
    return violations


def python_files(roots: Iterable[Path]) -> Iterable[Path]:
    """Yield Python files beneath each supplied root."""
    for root in roots:
        yield from root.rglob("*.py")


def module_name(path: Path) -> str:
    """Return the backend import path represented by a Python source path."""
    try:
        relative = path.relative_to(SRC_ROOT)
    except ValueError:
        relative = path.relative_to(BACKEND_ROOT)
    return ".".join(relative.with_suffix("").parts)


def http_handler_names(path: Path) -> tuple[str, ...]:
    """Return module-level functions decorated as HTTP route handlers."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tuple(
        node.name
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and any(is_http_route_decorator(item) for item in node.decorator_list)
    )


def is_http_route_decorator(node: ast.expr) -> bool:
    """Return whether an expression is an HTTP-method decorator."""
    target = node.func if isinstance(node, ast.Call) else node
    return isinstance(target, ast.Attribute) and target.attr in HTTP_ROUTE_METHODS


def import_targets(node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    """Return every module and imported symbol targeted by an import node."""
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


def resolved_rag_import_targets(
    path: Path,
    node: ast.Import | ast.ImportFrom,
) -> tuple[str, ...]:
    """Resolve a relative import against the source module's package."""
    if isinstance(node, ast.Import) or node.level == 0:
        return import_targets(node)

    package_parts = module_name(path).split(".")
    package_parts.pop()
    parent_count = node.level - 1
    if parent_count > len(package_parts):
        return import_targets(node)
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


def is_route_module(path: Path) -> bool:
    """Return whether a RAG source path is an HTTP route module."""
    relative_parts = path.relative_to(RAG_ROOT).parts
    return path.name != "__init__.py" and (
        "routes" in relative_parts
        or path.name == "routes.py"
        or path.stem.endswith("_routes")
    )


def is_concrete_adapter_module(module: str) -> bool:
    """Return whether an import target names a concrete adapter."""
    segments = module.split(".")
    return "adapters" in segments or any(
        segment.endswith(("_postgres", "_memory")) for segment in segments
    )


def assert_no_violations(violations: list[str]) -> None:
    """Fail with every dependency violation rendered as a source location."""
    details = "\n".join(f"- {violation}" for violation in violations)
    assert not violations, f"Architecture dependency violations:\n{details}"
