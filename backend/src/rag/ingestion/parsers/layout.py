"""PyMuPDF layout analysis activation."""

from __future__ import annotations

from importlib import import_module
from importlib import metadata
from typing import Any

from ..errors import WorkerStepError


def layout_package_version() -> str | None:
    try:
        return metadata.version("pymupdf-layout")
    except metadata.PackageNotFoundError:
        return None


def prepare_page_layout(page: Any) -> list[list[Any]]:
    get_layout = getattr(page, "get_layout", None)
    if get_layout is None:
        return []
    try:
        get_layout()
        layout = getattr(page, "layout_information", None)
        if layout is None:
            _activate_layout_package()
            get_layout()
            layout = getattr(page, "layout_information", None)
    except Exception as exc:
        raise WorkerStepError("pdf_layout_failed", "PyMuPDF layout analysis failed.") from exc
    return layout if isinstance(layout, list) else []


def _activate_layout_package() -> None:
    try:
        import_module("pymupdf.layout")
    except ModuleNotFoundError as exc:
        if exc.name in {"pymupdf", "pymupdf.layout"}:
            return
        raise WorkerStepError("pdf_layout_failed", "PyMuPDF layout dependency failed to import.") from exc
    except Exception as exc:
        raise WorkerStepError("pdf_layout_failed", "PyMuPDF layout dependency failed to import.") from exc
