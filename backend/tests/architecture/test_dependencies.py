"""Static checks for backend dependency direction."""

import ast
from collections.abc import Callable, Iterable
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
RAG_ROOT = BACKEND_ROOT / "src" / "rag"


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
