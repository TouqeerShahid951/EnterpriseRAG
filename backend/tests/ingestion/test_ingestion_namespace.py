import ast
from pathlib import Path


def test_backend_python_imports_use_the_canonical_ingestion_namespace() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    violations: list[str] = []
    for source_root in (backend_root / "src", backend_root / "apps"):
        for path in source_root.rglob("*.py"):
            if path.name.startswith("._"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                else:
                    continue
                if any(_is_legacy_ingestion_module(module) for module in modules):
                    violations.append(str(path.relative_to(backend_root)))

    assert violations == []
    assert not (backend_root / "src" / "rag_ingestion").exists()


def _is_legacy_ingestion_module(module: str) -> bool:
    return module == "rag_ingestion" or module.startswith("rag_ingestion.")
