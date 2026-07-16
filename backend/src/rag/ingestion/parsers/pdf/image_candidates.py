"""Selection and materialization of PDF image-analysis candidates."""

from __future__ import annotations

from dataclasses import dataclass

from rag.ingestion.errors import WorkerStepError
from rag.ingestion.parsers.images.contracts import (
    ImageSource,
    JPEG_CONTENT_TYPE,
    PNG_CONTENT_TYPE,
    PdfVisualSourceResult,
    ScannedVisualRegionResult,
)
from rag.ingestion.parsers.images.normalization import (
    bbox_area,
    bbox_from_value,
    content_type_for_extension,
    extension_for_content_type,
    normalized_image_source,
    page_bbox,
)
from rag.ingestion.parsers.images.sources import (
    fitz_module,
    page_blocks,
    page_text_chars,
    pdf_image_source_kind_and_flags,
)
from rag.ingestion.parsers.models import BBox, ParsedPdfItem
from rag.ingestion.parsers.pdf.visual_regions import (
    domain_visual_cue_pages_for_items,
    increment,
    parsed_text_bboxes_by_page,
    parsed_text_chars_by_page,
    scanned_visual_regions_for_page,
    visual_cue_bboxes_by_page,
    visual_region_sources_from_regions,
)

PDF_IMAGE_WEAK_TEXT_CHARS = 120
PDF_IMAGE_FULL_PAGE_AREA_RATIO = 0.75
PDF_IMAGE_MIN_FIGURE_AREA_RATIO = 0.08
PDF_IMAGE_MIN_WEAK_PAGE_AREA_RATIO = 0.02


def pdf_visual_sources(
    file_bytes: bytes,
    *,
    parsed_items: list[ParsedPdfItem],
    scanned_visual_region_enabled: bool,
    scanned_visual_min_area_ratio: float,
    scanned_visual_max_regions_per_page: int,
    scanned_visual_text_mask_padding_px: int,
) -> PdfVisualSourceResult:
    fitz = fitz_module()
    page_text_counts = parsed_text_chars_by_page(parsed_items)
    text_bboxes = parsed_text_bboxes_by_page(parsed_items)
    visual_cues = visual_cue_bboxes_by_page(parsed_items)
    domain_visual_cue_pages = domain_visual_cue_pages_for_items(parsed_items)
    image_candidates: list[PdfImageCandidate] = []
    crop_sources: list[ImageSource] = []
    class_counts: dict[str, int] = {}
    visual_region_pages: set[int] = set()
    fallback_pages: set[int] = set()
    candidate_count = 0
    skipped_tiny_count = 0
    skipped_text_only_count = 0
    ambiguous_count = 0
    cue_region_count = 0
    small_region_count = 0
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as document:
            for page_index in range(int(document.page_count)):
                page_no = page_index + 1
                page = document.load_page(page_index)
                page_candidates = pdf_image_candidates_for_page(page, page_no)
                image_candidates.extend(page_candidates)
                full_page_candidate = best_full_page_candidate(page_candidates)
                embedded_candidates = [
                    candidate
                    for candidate in page_candidates
                    if not is_full_page_candidate(candidate)
                ]
                if not scanned_visual_region_enabled:
                    increment(
                        class_counts,
                        page_class_without_scanned_detection_for_candidates(
                            full_page_candidate, embedded_candidates
                        ),
                    )
                    continue
                if full_page_candidate is None:
                    increment(
                        class_counts,
                        "native_mixed" if embedded_candidates else "native_text_only",
                    )
                    continue
                weak_text = page_text_counts.get(page_no, 0) < PDF_IMAGE_WEAK_TEXT_CHARS
                boxes = text_bboxes.get(page_no, [])
                if not boxes:
                    increment(
                        class_counts, "scanned_image_only" if weak_text else "ambiguous"
                    )
                    fallback_pages.add(page_no)
                    ambiguous_count += 0 if weak_text else 1
                    continue
                try:
                    regions, tiny_count, ambiguous, cue_count, small_count = (
                        scanned_visual_regions_for_page(
                            page,
                            boxes,
                            visual_cue_bboxes=visual_cues.get(page_no, []),
                            domain_visual_cue=page_no in domain_visual_cue_pages,
                            min_area_ratio=max(0.0, scanned_visual_min_area_ratio),
                            max_regions=scanned_visual_max_regions_per_page,
                            text_mask_padding_px=max(
                                0, scanned_visual_text_mask_padding_px
                            ),
                        )
                    )
                except Exception:
                    increment(class_counts, "ambiguous")
                    fallback_pages.add(page_no)
                    ambiguous_count += 1
                    continue
                candidate_count += len(regions) + tiny_count
                skipped_tiny_count += tiny_count
                cue_region_count += cue_count
                small_region_count += small_count
                if ambiguous:
                    ambiguous_count += 1
                if regions:
                    increment(class_counts, "scanned_mixed")
                    visual_region_pages.add(page_no)
                    crop_sources.extend(
                        visual_region_sources_from_regions(
                            page_no=page_no,
                            regions=regions,
                            full_page_quality_flags=full_page_candidate.quality_flags,
                        )
                    )
                    continue
                if weak_text:
                    increment(class_counts, "scanned_image_only")
                    fallback_pages.add(page_no)
                else:
                    increment(class_counts, "scanned_text_only")
                    skipped_text_only_count += 1
            materialized, skipped_unnecessary_count = materialize_pdf_image_candidates(
                document,
                image_candidates,
                page_text_chars=page_text_counts,
                visual_region_pages=frozenset(visual_region_pages),
                fallback_pages=frozenset(fallback_pages),
            )
    except WorkerStepError:
        raise
    except Exception as exc:
        raise WorkerStepError(
            "pdf_visual_source_extract_failed",
            "PyMuPDF failed to extract PDF visual sources.",
        ) from exc
    scanned = ScannedVisualRegionResult(
        sources=crop_sources,
        page_class_counts=class_counts,
        candidate_count=candidate_count,
        selected_count=len(crop_sources),
        whole_page_fallback_count=len(fallback_pages),
        skipped_text_only_count=skipped_text_only_count,
        skipped_tiny_count=skipped_tiny_count,
        ambiguous_count=ambiguous_count,
        cue_region_count=cue_region_count,
        small_region_count=small_region_count,
        visual_region_pages=frozenset(visual_region_pages),
        whole_page_fallback_pages=frozenset(fallback_pages),
    )
    return PdfVisualSourceResult(
        image_sources=[*materialized, *crop_sources],
        scanned_visual_regions=scanned,
        image_candidate_count=len(image_candidates) + len(crop_sources),
        skipped_unnecessary_count=skipped_unnecessary_count,
    )


@dataclass(frozen=True)
class PdfImageCandidate:
    page_no: int
    filename: str
    source_kind: str
    quality_flags: list[str]
    bbox: BBox | None
    page_area_ratio: float | None
    target_content_type: str
    content: bytes | None = None
    render_page: bool = False


def pdf_image_candidates_for_page(
    page: object, page_no: int
) -> list[PdfImageCandidate]:
    blocks = page_blocks(page)
    image_blocks = [block for block in blocks if block.get("type") == 1]
    page_box = page_bbox(page)
    page_area = bbox_area(page_box) if page_box is not None else 0.0
    page_text_count = page_text_chars(page)
    candidates: list[PdfImageCandidate] = []
    for image_index, block in enumerate(image_blocks):
        bbox = bbox_from_value(block.get("bbox"))
        raw = block.get("image")
        if (
            not isinstance(raw, bytes)
            or not raw
            or bbox is None
            or bbox_area(bbox) < 1024
        ):
            continue
        content_type = content_type_for_extension(str(block.get("ext") or ""))
        if content_type not in {JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE}:
            content_type = PNG_CONTENT_TYPE
        source_kind, flags = pdf_image_source_kind_and_flags(
            bbox=bbox,
            page_area=page_area,
            page_text_chars=page_text_count,
        )
        candidates.append(
            PdfImageCandidate(
                page_no=page_no,
                filename=f"page-{page_no}-image-{image_index + 1}.{extension_for_content_type(content_type)}",
                source_kind=source_kind,
                quality_flags=flags,
                bbox=bbox,
                page_area_ratio=bbox_area(bbox) / page_area if page_area > 0 else None,
                target_content_type=content_type,
                content=raw,
            )
        )
    if not candidates and page_text_count < 40:
        candidates.append(
            PdfImageCandidate(
                page_no=page_no,
                filename=f"page-{page_no}.png",
                source_kind="pdf_page_image",
                quality_flags=[
                    "source:pdf_page_image",
                    "scanned_or_handwritten_candidate",
                    "vision_layout_repair_candidate",
                ],
                bbox=page_box,
                page_area_ratio=1.0,
                target_content_type=PNG_CONTENT_TYPE,
                render_page=True,
            )
        )
    return candidates


def best_full_page_candidate(
    candidates: list[PdfImageCandidate],
) -> PdfImageCandidate | None:
    full_page_candidates = [
        candidate for candidate in candidates if is_full_page_candidate(candidate)
    ]
    if not full_page_candidates:
        return None
    return max(
        full_page_candidates, key=lambda candidate: candidate.page_area_ratio or 0.0
    )


def page_class_without_scanned_detection_for_candidates(
    full_page_candidate: PdfImageCandidate | None,
    embedded_candidates: list[PdfImageCandidate],
) -> str:
    if full_page_candidate is not None:
        return "ambiguous"
    return "native_mixed" if embedded_candidates else "native_text_only"


def materialize_pdf_image_candidates(
    document: object,
    candidates: list[PdfImageCandidate],
    *,
    page_text_chars: dict[int, int],
    visual_region_pages: frozenset[int],
    fallback_pages: frozenset[int],
) -> tuple[list[ImageSource], int]:
    sources: list[ImageSource] = []
    skipped_unnecessary_count = 0
    for candidate in candidates:
        if (
            pdf_image_candidate_score(
                candidate, page_text_chars, visual_region_pages, fallback_pages
            )
            <= 0
        ):
            skipped_unnecessary_count += 1
            continue
        try:
            content = candidate_content(document, candidate)
            if not content:
                continue
            sources.append(
                normalized_image_source(
                    content,
                    filename=candidate.filename,
                    source_kind=candidate.source_kind,
                    quality_flags=candidate.quality_flags,
                    page=candidate.page_no,
                    bbox=candidate.bbox,
                    page_area_ratio=candidate.page_area_ratio,
                    target_content_type=candidate.target_content_type,
                )
            )
        except WorkerStepError:
            continue
    return sources, skipped_unnecessary_count


def candidate_content(document: object, candidate: PdfImageCandidate) -> bytes | None:
    if not candidate.render_page:
        return candidate.content
    page = document.load_page(candidate.page_no - 1)
    return page.get_pixmap(dpi=150).tobytes("png")


def pdf_image_candidate_score(
    candidate: PdfImageCandidate,
    page_text_chars: dict[int, int],
    visual_region_pages: frozenset[int],
    fallback_pages: frozenset[int],
) -> int:
    weak_page = page_text_chars.get(candidate.page_no, 0) < PDF_IMAGE_WEAK_TEXT_CHARS
    if is_full_page_candidate(candidate):
        if candidate.page_no in fallback_pages:
            return 80
        if candidate.page_no in visual_region_pages:
            return 0
        return 80 if weak_page else 0
    area_ratio = candidate.page_area_ratio
    if weak_page and (
        area_ratio is None or area_ratio >= PDF_IMAGE_MIN_WEAK_PAGE_AREA_RATIO
    ):
        return 100
    if "large_image_candidate" in candidate.quality_flags:
        return 110
    if area_ratio is not None and area_ratio >= PDF_IMAGE_MIN_FIGURE_AREA_RATIO:
        return 110
    return 0


def is_full_page_candidate(candidate: PdfImageCandidate) -> bool:
    return (
        candidate.source_kind in {"pdf_page_image", "pdf_page_layout"}
        or "full_page_image_candidate" in candidate.quality_flags
        or (
            candidate.page_area_ratio is not None
            and candidate.page_area_ratio >= PDF_IMAGE_FULL_PAGE_AREA_RATIO
        )
    )
