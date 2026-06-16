"""Static policy checks for constrained artifact build programs."""

from __future__ import annotations

import ast

_ALLOWED_IMPORTS = ("json", "pathlib", "docx", "pptx", "reportlab", "rag.artifact_sandbox.sdk")
_BLOCKED_CALLS = {
    "open",
    "eval",
    "exec",
    "compile",
    "__import__",
    "input",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
}
_BLOCKED_ATTRS = {
    "open",
    "write_text",
    "write_bytes",
    "touch",
    "mkdir",
    "rename",
    "replace",
    "unlink",
    "rmdir",
    "chmod",
    "symlink_to",
    "hardlink_to",
    "save",
    "write_docx",
    "write_pptx",
    "write_pdf",
    "write_format",
}


def validate_program_policy(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"invalid Python syntax: {exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _validate_import(alias.name)
        elif isinstance(node, ast.ImportFrom):
            _validate_import(node.module or "")
        elif isinstance(node, ast.Call):
            _validate_call(node.func)
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("dunder attribute access is not allowed")


def _validate_import(module: str) -> None:
    if not any(module == allowed or module.startswith(f"{allowed}.") for allowed in _ALLOWED_IMPORTS):
        raise ValueError(f"import is not allowed: {module}")


def _validate_call(func: ast.expr) -> None:
    if isinstance(func, ast.Name) and func.id in _BLOCKED_CALLS:
        raise ValueError(f"call is not allowed: {func.id}")
    if isinstance(func, ast.Attribute) and func.attr in _BLOCKED_ATTRS:
        raise ValueError(f"method is not allowed: {func.attr}")
