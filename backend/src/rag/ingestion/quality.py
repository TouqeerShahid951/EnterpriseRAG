"""Ingestion quality preset definitions."""

from __future__ import annotations

from dataclasses import dataclass

INGESTION_QUALITY_FAST = "fast"
INGESTION_QUALITY_BALANCED = "balanced"
INGESTION_QUALITY_HIGH_ACCURACY = "high_accuracy"
DEFAULT_INGESTION_QUALITY_PRESET = INGESTION_QUALITY_FAST
SUPPORTED_INGESTION_QUALITY_PRESETS = frozenset(
    {
        INGESTION_QUALITY_FAST,
        INGESTION_QUALITY_BALANCED,
        INGESTION_QUALITY_HIGH_ACCURACY,
    }
)


@dataclass(frozen=True)
class IngestionParserTuning:
    quality_preset: str
    weak_page_threshold: int
    full_doc_weak_page_ratio: float
    layered_docling_max_pages: int
    layered_docling_max_page_ratio: float | None
    prefer_full_document_docling: bool


def normalize_ingestion_quality_preset(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_INGESTION_QUALITY_PRESETS:
        return normalized
    return DEFAULT_INGESTION_QUALITY_PRESET


def parser_tuning_for_quality_preset(
    preset: str | None,
    *,
    weak_page_threshold: int,
    full_doc_weak_page_ratio: float,
    layered_docling_max_pages: int,
) -> IngestionParserTuning:
    normalized = normalize_ingestion_quality_preset(preset)
    base_threshold = max(1, int(weak_page_threshold))
    base_full_doc_ratio = _ratio(full_doc_weak_page_ratio, default=0.25)
    base_max_pages = max(1, int(layered_docling_max_pages))

    if normalized == INGESTION_QUALITY_HIGH_ACCURACY:
        return IngestionParserTuning(
            quality_preset=normalized,
            weak_page_threshold=max(1, min(base_threshold, 4)),
            full_doc_weak_page_ratio=min(base_full_doc_ratio, 0.25),
            layered_docling_max_pages=max(base_max_pages, 120),
            layered_docling_max_page_ratio=None,
            prefer_full_document_docling=True,
        )
    if normalized == INGESTION_QUALITY_BALANCED:
        return IngestionParserTuning(
            quality_preset=normalized,
            weak_page_threshold=base_threshold,
            full_doc_weak_page_ratio=base_full_doc_ratio,
            layered_docling_max_pages=base_max_pages,
            layered_docling_max_page_ratio=0.25,
            prefer_full_document_docling=False,
        )
    return IngestionParserTuning(
        quality_preset=normalized,
        weak_page_threshold=max(base_threshold, 8),
        full_doc_weak_page_ratio=max(base_full_doc_ratio, 0.50),
        layered_docling_max_pages=min(base_max_pages, 12),
        layered_docling_max_page_ratio=0.10,
        prefer_full_document_docling=False,
    )


def _ratio(value: float, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return min(1.0, parsed)
