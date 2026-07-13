"""Compatibility facade for deterministic artifact rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .contracts import ArtifactContentBundle
from .layout_profiles import select_layout_profile
from .renderers.docx import render_docx as _render_docx
from .renderers.package_validation import (
    office_smoke_check as _office_smoke_check,
    validate_package as _validate_package,
)
from .renderers.pdf import (
    PDF_WIDE_TABLE_COLUMNS as PDF_WIDE_TABLE_COLUMNS,
    render_pdf as _render_pdf,
)
from .renderers.pptx import (
    PPTX_BODY_PANEL_HEIGHT_IN as PPTX_BODY_PANEL_HEIGHT_IN,
    PPTX_BODY_PANEL_LEFT_IN as PPTX_BODY_PANEL_LEFT_IN,
    PPTX_BODY_PANEL_TOP_IN as PPTX_BODY_PANEL_TOP_IN,
    PPTX_BODY_PANEL_WIDTH_IN as PPTX_BODY_PANEL_WIDTH_IN,
    PPTX_MAX_BULLETS_PER_SLIDE as PPTX_MAX_BULLETS_PER_SLIDE,
    PPTX_MAX_TEXT_UNITS_PER_SLIDE as PPTX_MAX_TEXT_UNITS_PER_SLIDE,
    PPTX_TABLE_BODY_FONT_MAX as PPTX_TABLE_BODY_FONT_MAX,
    PPTX_TABLE_BODY_FONT_MIN as PPTX_TABLE_BODY_FONT_MIN,
    PPTX_TABLE_HEADER_MIN_HEIGHT_IN as PPTX_TABLE_HEADER_MIN_HEIGHT_IN,
    PPTX_TABLE_LEFT_IN as PPTX_TABLE_LEFT_IN,
    PPTX_TABLE_MAX_HEIGHT_IN as PPTX_TABLE_MAX_HEIGHT_IN,
    PPTX_TABLE_ROW_MAX_HEIGHT_IN as PPTX_TABLE_ROW_MAX_HEIGHT_IN,
    PPTX_TABLE_ROW_MIN_HEIGHT_IN as PPTX_TABLE_ROW_MIN_HEIGHT_IN,
    PPTX_TABLE_TOP_IN as PPTX_TABLE_TOP_IN,
    PPTX_TABLE_WIDTH_IN as PPTX_TABLE_WIDTH_IN,
    PPTX_TEXT_UNIT_CHARS as PPTX_TEXT_UNIT_CHARS,
    PptxTableLayout as PptxTableLayout,
    render_pptx as _render_pptx,
)
from .renderers.shared import (
    PPTX_MAX_SOURCE_LABELS as PPTX_MAX_SOURCE_LABELS,
    _safe_filename,
)
from .types import ArtifactFormat


CONTENT_TYPES: dict[ArtifactFormat, str] = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
}


@dataclass(frozen=True)
class RenderedV2Artifact:
    filename: str
    format: ArtifactFormat
    content_type: str
    content: bytes
    smoke_warnings: tuple[str, ...] = ()


def render_document(
    *,
    artifact_format: ArtifactFormat,
    bundle: ArtifactContentBundle,
    generated_at: datetime,
    require_libreoffice: bool,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> RenderedV2Artifact:
    profile = select_layout_profile(bundle)
    if artifact_format == "docx":
        content = _render_docx(bundle, generated_at, profile)
    elif artifact_format == "pdf":
        content = _render_pdf(bundle, generated_at, profile)
    elif artifact_format == "pptx":
        content = _render_pptx(bundle, generated_at, profile, progress_callback=progress_callback)
    else:
        raise ValueError(f"unsupported artifact format: {artifact_format}")
    _validate_package(artifact_format, content)
    warnings = _office_smoke_check(
        artifact_format=artifact_format,
        content=content,
        require_libreoffice=require_libreoffice,
    )
    return RenderedV2Artifact(
        filename=f"{_safe_filename(bundle.content.title)}.{artifact_format}",
        format=artifact_format,
        content_type=CONTENT_TYPES[artifact_format],
        content=content,
        smoke_warnings=warnings,
    )
