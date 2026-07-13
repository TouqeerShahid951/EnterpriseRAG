"""Image-review serialization helpers for the ingestion pipeline."""

import hashlib
from uuid import uuid4

from ..parsers import PdfImageReviewRequired
from ..parsers.images import ImageSource, image_dimensions, image_source_candidate_key
from ..parsers.models import BBox, ParsedPdfItem, parsed_item_from_dict
from .state import IngestDependencies


def image_review_resume_inputs(
    image_review_batch_id: str,
    deps: IngestDependencies,
) -> tuple[list[ParsedPdfItem], list[ImageSource], int]:
    resume = deps.backend.get_image_review_resume(
        image_review_batch_id=image_review_batch_id
    )
    parsed_items = [parsed_item_from_dict(item) for item in resume["parsed_items"]]
    sources = [
        image_source_from_review_candidate(candidate, deps)
        for candidate in resume["candidates"]
    ]
    return parsed_items, sources, int(resume.get("candidate_count") or len(sources))


def image_source_from_review_candidate(
    candidate: dict[str, object], deps: IngestDependencies
) -> ImageSource:
    object_path = str(candidate["object_path"])
    return ImageSource(
        content=deps.storage.read(object_path),
        content_type=str(candidate.get("content_type") or "image/png"),
        filename=str(candidate.get("filename") or "image.png"),
        source_kind=str(candidate.get("source_kind") or "pdf_image"),
        quality_flags=sorted(
            {*string_list(candidate.get("quality_flags")), "image_review_approved"}
        ),
        page=positive_int_or_none(candidate.get("page")),
        bbox=bbox_tuple(candidate.get("bbox")),
        page_area_ratio=float_or_none(candidate.get("page_area_ratio")),
    )


def image_review_candidates(
    exc: PdfImageReviewRequired,
    *,
    deps: IngestDependencies,
    doc_id: str,
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for source in exc.image_selection.sources:
        candidate_key = image_source_candidate_key(source)
        asset_id = str(uuid4())
        object_path = deps.image_asset_writer.put_image_asset(
            doc_id=doc_id,
            asset_id=asset_id,
            filename=source.filename,
            content=source.content,
            content_type=source.content_type,
        )
        try:
            width, height = image_dimensions(source.content)
        except Exception:
            width, height = None, None
        candidates.append(
            {
                "candidate_key": candidate_key,
                "filename": source.filename,
                "source_kind": source.source_kind,
                "page": source.page,
                "bbox": list(source.bbox) if source.bbox is not None else None,
                "page_area_ratio": source.page_area_ratio,
                "object_path": object_path,
                "content_type": source.content_type,
                "width": width,
                "height": height,
                "content_hash": hashlib.sha256(source.content).hexdigest(),
                "quality_flags": sorted(
                    {*source.quality_flags, "image_review_candidate"}
                ),
                "score": exc.image_selection.source_scores.get(candidate_key, 0),
                "recommended": True,
            }
        )
    return candidates


def image_review_required_provenance(exc: PdfImageReviewRequired) -> dict[str, object]:
    selection = exc.image_selection
    visual_sources = exc.visual_sources
    scanned = visual_sources.scanned_visual_regions
    return {
        **exc.parsed.provenance,
        "image_analysis_review_required": True,
        "image_analysis_candidate_count": visual_sources.image_candidate_count,
        "image_analysis_selected_count": len(selection.sources),
        "image_analysis_pending_review_count": len(selection.sources),
        "image_analysis_skipped_count": selection.skipped_count
        + visual_sources.skipped_unnecessary_count,
        "image_analysis_skipped_unnecessary_count": (
            selection.skipped_unnecessary_count
            + visual_sources.skipped_unnecessary_count
        ),
        "image_analysis_skipped_duplicate_count": selection.skipped_duplicate_count,
        "image_analysis_skipped_limit_count": selection.skipped_limit_count,
        "image_analysis_skipped_full_page_fallback_count": selection.skipped_full_page_fallback_count,
        "scanned_page_class_counts": scanned.page_class_counts,
        "scanned_visual_candidate_count": scanned.candidate_count,
        "scanned_visual_selected_count": scanned.selected_count,
        "scanned_visual_whole_page_fallback_count": scanned.whole_page_fallback_count,
    }


def positive_int_or_none(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    return None


def float_or_none(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def bbox_tuple(value: object) -> BBox | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    except (TypeError, ValueError):
        return None


def string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []
