"""Contracts shared by ingestion image parsing components."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable, Protocol

from .models import BBox

JPEG_CONTENT_TYPE = "image/jpeg"
PNG_CONTENT_TYPE = "image/png"


@dataclass(frozen=True)
class ImageAnalysisResult:
    extracted_text: str = ""
    caption: str = ""
    confidence: float | None = None
    quality_flags: list[str] | None = None


class ImageAssetStore(Protocol):
    def put_image_asset(
        self,
        *,
        doc_id: str,
        asset_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> str: ...


class ImageAnalyzer(Protocol):
    def analyze_image(
        self, *, content: bytes, content_type: str
    ) -> ImageAnalysisResult: ...


ImageProgressCallback = Callable[[dict[str, object]], None]


@dataclass(frozen=True)
class ImageSource:
    content: bytes
    content_type: str
    filename: str
    source_kind: str
    quality_flags: list[str]
    page: int | None = None
    bbox: BBox | None = None
    page_area_ratio: float | None = None


def image_source_candidate_key(source: ImageSource) -> str:
    bbox = (
        ",".join(f"{value:.3f}" for value in source.bbox)
        if source.bbox is not None
        else ""
    )
    digest = hashlib.sha256(source.content).hexdigest()
    parts = [
        source.source_kind,
        str(source.page or ""),
        bbox,
        source.filename,
        digest,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ScannedVisualRegionResult:
    sources: list[ImageSource]
    page_class_counts: dict[str, int]
    candidate_count: int = 0
    selected_count: int = 0
    whole_page_fallback_count: int = 0
    skipped_text_only_count: int = 0
    skipped_tiny_count: int = 0
    ambiguous_count: int = 0
    cue_region_count: int = 0
    small_region_count: int = 0
    visual_region_pages: frozenset[int] = frozenset()
    whole_page_fallback_pages: frozenset[int] = frozenset()


@dataclass(frozen=True)
class PdfVisualSourceResult:
    image_sources: list[ImageSource]
    scanned_visual_regions: ScannedVisualRegionResult
    image_candidate_count: int
    skipped_unnecessary_count: int = 0
