"""Image extraction helpers for document ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import hashlib
import math
import re
from typing import Callable, Protocol
from uuid import uuid4
import zipfile

from ..errors import UnsupportedDocumentError, WorkerStepError
from .layout import prepare_page_layout
from .models import BBox, DocumentParseResult, ParsedImageAsset, ParsedPdfItem
from .provenance import base_report

JPEG_CONTENT_TYPE = "image/jpeg"
PNG_CONTENT_TYPE = "image/png"
VISUAL_CUE_PATTERN = re.compile(
    r"\b("
    r"fig(?:ure)?|diagram|schematic|drawing|illustration|image|photo|photograph|plate|map|chart|graph|"
    r"signature|stamp|seal|logo|symbol|insignia|emblem|vehicle|tank|armou?red|aircraft|drone|missile|"
    r"launcher|radar|ship|vessel"
    r")\b",
    re.IGNORECASE,
)
DOMAIN_VISUAL_CUE_PATTERN = re.compile(
    r"\b(tank|armou?red|vehicle|aircraft|drone|missile|launcher|radar|ship|vessel|insignia|emblem|symbol)\b",
    re.IGNORECASE,
)
PDF_IMAGE_WEAK_TEXT_CHARS = 120
PDF_IMAGE_FULL_PAGE_AREA_RATIO = 0.75
PDF_IMAGE_MIN_FIGURE_AREA_RATIO = 0.08
PDF_IMAGE_MIN_WEAK_PAGE_AREA_RATIO = 0.02
VISION_ANALYSIS_MAX_LONG_EDGE = 2048
VISION_ANALYSIS_OCR_MAX_LONG_EDGE = 2048
VISION_RETRY_MIN_CONFIDENCE = 0.5
LAYOUT_VISUAL_LABELS = {"figure", "image", "picture"}


@dataclass(frozen=True)
class ImageAnalysisResult:
    extracted_text: str = ""
    caption: str = ""
    confidence: float | None = None
    quality_flags: list[str] | None = None


class ImageAssetStore(Protocol):
    def put_image_asset(self, *, doc_id: str, asset_id: str, filename: str, content: bytes, content_type: str) -> str: ...


class ImageAnalyzer(Protocol):
    def analyze_image(self, *, content: bytes, content_type: str) -> ImageAnalysisResult: ...


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
    bbox = ",".join(f"{value:.3f}" for value in source.bbox) if source.bbox is not None else ""
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


def parse_image_document(
    file_bytes: bytes,
    *,
    doc_id: str,
    store: ImageAssetStore,
    analyzer: ImageAnalyzer,
    content_type: str | None = None,
    filename: str = "upload",
) -> DocumentParseResult:
    target_content_type = _target_content_type_for_standalone(content_type, filename)
    source = _normalized_image_source(
        file_bytes,
        filename=filename,
        source_kind="standalone_image",
        quality_flags=["source:image_file"],
        page=1,
        bbox=None,
        target_content_type=target_content_type,
    )
    items, assets = image_sources_to_items([source], doc_id=doc_id, store=store, analyzer=analyzer)
    if not items and assets:
        items = [_standalone_image_placeholder_item(source, assets[0])]
    if not items:
        raise UnsupportedDocumentError()
    return DocumentParseResult(
        items=items,
        provenance=base_report(
            document_kind="image",
            page_count=1,
            primary_parser="image",
            secondary_parser="vision",
            routing_mode="standalone_image",
            config={},
            items=items,
        ) | {"image_asset_count": len(assets)},
        assets=assets,
    )


def docx_image_sources(file_bytes: bytes) -> list[ImageSource]:
    try:
        archive = zipfile.ZipFile(BytesIO(file_bytes))
    except zipfile.BadZipFile:
        return []
    sources: list[ImageSource] = []
    with archive:
        for name in sorted(archive.namelist()):
            if not name.startswith("word/media/"):
                continue
            content_type = _content_type_for_filename(name)
            if content_type not in {JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE}:
                continue
            try:
                raw = archive.read(name)
            except KeyError:
                continue
            try:
                sources.append(
                    _normalized_image_source(
                        raw,
                        filename=name.rsplit("/", 1)[-1],
                        source_kind="docx_media",
                        quality_flags=["source:docx_media"],
                        page=None,
                        bbox=None,
                        target_content_type=content_type,
                    )
                )
            except WorkerStepError:
                continue
    return sources


def pdf_image_sources(file_bytes: bytes) -> list[ImageSource]:
    try:
        import fitz
    except ImportError as exc:
        raise WorkerStepError("pdf_dependency_missing", "PyMuPDF dependency is not installed.") from exc
    sources: list[ImageSource] = []
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as document:
            for page_index in range(int(document.page_count)):
                page_no = page_index + 1
                page = document.load_page(page_index)
                blocks = _page_blocks(page)
                image_blocks = [block for block in blocks if block.get("type") == 1]
                page_bbox = _page_bbox(page)
                page_area = _bbox_area(page_bbox) if page_bbox is not None else 0.0
                extracted_for_page = 0
                page_text_chars = _page_text_chars(page)
                for image_index, block in enumerate(image_blocks):
                    bbox = _bbox(block.get("bbox"))
                    raw = block.get("image")
                    if not isinstance(raw, bytes) or not raw or bbox is None or _bbox_area(bbox) < 1024:
                        continue
                    content_type = _content_type_for_extension(str(block.get("ext") or ""))
                    if content_type not in {JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE}:
                        content_type = PNG_CONTENT_TYPE
                    source_kind, flags = _pdf_image_source_kind_and_flags(
                        bbox=bbox,
                        page_area=page_area,
                        page_text_chars=page_text_chars,
                    )
                    page_area_ratio = _bbox_area(bbox) / page_area if page_area > 0 else None
                    try:
                        sources.append(
                            _normalized_image_source(
                                raw,
                                filename=f"page-{page_no}-image-{image_index + 1}.{_extension_for_content_type(content_type)}",
                                source_kind=source_kind,
                                quality_flags=flags,
                                page=page_no,
                                bbox=bbox,
                                page_area_ratio=page_area_ratio,
                                target_content_type=content_type,
                            )
                        )
                        extracted_for_page += 1
                    except WorkerStepError:
                        continue
                if extracted_for_page == 0 and page_text_chars < 40:
                    pixmap = page.get_pixmap(dpi=150)
                    try:
                        sources.append(
                            _normalized_image_source(
                                pixmap.tobytes("png"),
                                filename=f"page-{page_no}.png",
                                source_kind="pdf_page_image",
                                quality_flags=["source:pdf_page_image", "scanned_or_handwritten_candidate", "vision_layout_repair_candidate"],
                                page=page_no,
                                bbox=_page_bbox(page),
                                page_area_ratio=1.0,
                                target_content_type=PNG_CONTENT_TYPE,
                            )
                        )
                    except WorkerStepError:
                        continue
    except WorkerStepError:
        raise
    except Exception as exc:
        raise WorkerStepError("pdf_image_extract_failed", "PyMuPDF failed to extract PDF images.") from exc
    return sources


def pdf_visual_sources(
    file_bytes: bytes,
    *,
    parsed_items: list[ParsedPdfItem],
    scanned_visual_region_enabled: bool,
    scanned_visual_min_area_ratio: float,
    scanned_visual_max_regions_per_page: int,
    scanned_visual_text_mask_padding_px: int,
) -> PdfVisualSourceResult:
    fitz = _fitz_module()
    page_text_chars = _parsed_text_chars_by_page(parsed_items)
    text_bboxes = _parsed_text_bboxes_by_page(parsed_items)
    visual_cues = _visual_cue_bboxes_by_page(parsed_items)
    domain_visual_cue_pages = _domain_visual_cue_pages(parsed_items)
    image_candidates: list[_PdfImageCandidate] = []
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
                page_candidates = _pdf_image_candidates_for_page(page, page_no)
                image_candidates.extend(page_candidates)
                full_page_candidate = _best_full_page_candidate(page_candidates)
                embedded_candidates = [candidate for candidate in page_candidates if not _is_full_page_candidate(candidate)]
                if not scanned_visual_region_enabled:
                    _increment(class_counts, _page_class_without_scanned_detection_for_candidates(full_page_candidate, embedded_candidates))
                    continue
                if full_page_candidate is None:
                    _increment(class_counts, "native_mixed" if embedded_candidates else "native_text_only")
                    continue
                weak_text = page_text_chars.get(page_no, 0) < PDF_IMAGE_WEAK_TEXT_CHARS
                boxes = text_bboxes.get(page_no, [])
                if not boxes:
                    _increment(class_counts, "scanned_image_only" if weak_text else "ambiguous")
                    fallback_pages.add(page_no)
                    ambiguous_count += 0 if weak_text else 1
                    continue
                try:
                    regions, tiny_count, ambiguous, cue_count, small_count = _scanned_visual_regions_for_page(
                        page,
                        boxes,
                        visual_cue_bboxes=visual_cues.get(page_no, []),
                        domain_visual_cue=page_no in domain_visual_cue_pages,
                        min_area_ratio=max(0.0, scanned_visual_min_area_ratio),
                        max_regions=scanned_visual_max_regions_per_page,
                        text_mask_padding_px=max(0, scanned_visual_text_mask_padding_px),
                    )
                except Exception:
                    _increment(class_counts, "ambiguous")
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
                    _increment(class_counts, "scanned_mixed")
                    visual_region_pages.add(page_no)
                    crop_sources.extend(
                        _visual_region_sources_from_regions(
                            page_no=page_no,
                            regions=regions,
                            full_page_quality_flags=full_page_candidate.quality_flags,
                        )
                    )
                    continue
                if weak_text:
                    _increment(class_counts, "scanned_image_only")
                    fallback_pages.add(page_no)
                else:
                    _increment(class_counts, "scanned_text_only")
                    skipped_text_only_count += 1
            materialized, skipped_unnecessary_count = _materialize_pdf_image_candidates(
                document,
                image_candidates,
                page_text_chars=page_text_chars,
                visual_region_pages=frozenset(visual_region_pages),
                fallback_pages=frozenset(fallback_pages),
            )
    except WorkerStepError:
        raise
    except Exception as exc:
        raise WorkerStepError("pdf_visual_source_extract_failed", "PyMuPDF failed to extract PDF visual sources.") from exc
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


def pdf_scanned_visual_region_sources(
    file_bytes: bytes,
    *,
    parsed_items: list[ParsedPdfItem],
    image_sources: list[ImageSource],
    enabled: bool,
    min_area_ratio: float,
    max_regions_per_page: int,
    text_mask_padding_px: int,
) -> ScannedVisualRegionResult:
    page_numbers = _document_page_numbers(parsed_items, image_sources)
    full_page_sources = _full_page_sources_by_page(image_sources)
    embedded_sources = _embedded_sources_by_page(image_sources)
    page_text_chars = _parsed_text_chars_by_page(parsed_items)
    text_bboxes = _parsed_text_bboxes_by_page(parsed_items)
    visual_cues = _visual_cue_bboxes_by_page(parsed_items)
    domain_visual_cue_pages = _domain_visual_cue_pages(parsed_items)
    class_counts: dict[str, int] = {}
    crop_sources: list[ImageSource] = []
    visual_region_pages: set[int] = set()
    fallback_pages: set[int] = set()
    candidate_count = 0
    skipped_tiny_count = 0
    skipped_text_only_count = 0
    ambiguous_count = 0
    cue_region_count = 0
    small_region_count = 0

    if not enabled:
        for page_no in sorted(page_numbers):
            _increment(class_counts, _page_class_without_scanned_detection(page_no, full_page_sources, embedded_sources))
        return ScannedVisualRegionResult(sources=[], page_class_counts=class_counts)

    fitz = _fitz_module()
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as document:
            for page_no in sorted(page_numbers):
                full_page_source = full_page_sources.get(page_no)
                if full_page_source is None:
                    _increment(class_counts, "native_mixed" if embedded_sources.get(page_no) else "native_text_only")
                    continue
                weak_text = page_text_chars.get(page_no, 0) < 120
                boxes = text_bboxes.get(page_no, [])
                if not boxes:
                    class_name = "scanned_image_only" if weak_text else "ambiguous"
                    _increment(class_counts, class_name)
                    fallback_pages.add(page_no)
                    ambiguous_count += 0 if weak_text else 1
                    continue
                try:
                    page = document.load_page(page_no - 1)
                    regions, tiny_count, ambiguous, cue_count, small_count = _scanned_visual_regions_for_page(
                        page,
                        boxes,
                        visual_cue_bboxes=visual_cues.get(page_no, []),
                        domain_visual_cue=page_no in domain_visual_cue_pages,
                        min_area_ratio=max(0.0, min_area_ratio),
                        max_regions=max_regions_per_page,
                        text_mask_padding_px=max(0, text_mask_padding_px),
                    )
                except Exception:
                    _increment(class_counts, "ambiguous")
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
                    _increment(class_counts, "scanned_mixed")
                    visual_region_pages.add(page_no)
                    crop_sources.extend(
                        _visual_region_sources_from_regions(
                            page_no=page_no,
                            regions=regions,
                            full_page_quality_flags=full_page_source.quality_flags,
                        )
                    )
                    continue
                if weak_text:
                    _increment(class_counts, "scanned_image_only")
                    fallback_pages.add(page_no)
                else:
                    _increment(class_counts, "scanned_text_only")
                    skipped_text_only_count += 1
    except Exception as exc:
        raise WorkerStepError("pdf_scanned_visual_region_extract_failed", "PyMuPDF failed to extract scanned page visual regions.") from exc

    return ScannedVisualRegionResult(
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


def pdf_page_image_sources(file_bytes: bytes, pages: set[int], *, dpi: int = 150) -> list[ImageSource]:
    if not pages:
        return []
    try:
        import fitz
    except ImportError as exc:
        raise WorkerStepError("pdf_dependency_missing", "PyMuPDF dependency is not installed.") from exc
    sources: list[ImageSource] = []
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as document:
            for page_no in sorted(page for page in pages if page > 0):
                if page_no > int(document.page_count):
                    continue
                page = document.load_page(page_no - 1)
                pixmap = page.get_pixmap(dpi=dpi)
                try:
                    sources.append(
                        _normalized_image_source(
                            pixmap.tobytes("png"),
                            filename=f"page-{page_no}-layout.png",
                            source_kind="pdf_page_layout",
                            quality_flags=["source:pdf_page_image", "vision_layout_repair_candidate"],
                            page=page_no,
                            bbox=_page_bbox(page),
                            page_area_ratio=1.0,
                            target_content_type=PNG_CONTENT_TYPE,
                        )
                    )
                except WorkerStepError:
                    continue
    except WorkerStepError:
        raise
    except Exception as exc:
        raise WorkerStepError("pdf_page_render_failed", "PyMuPDF failed to render PDF pages for vision layout repair.") from exc
    return sources


def image_sources_to_items(
    sources: list[ImageSource],
    *,
    doc_id: str,
    store: ImageAssetStore,
    analyzer: ImageAnalyzer,
    start_index: int = 0,
    progress_callback: ImageProgressCallback | None = None,
) -> tuple[list[ParsedPdfItem], list[ParsedImageAsset]]:
    items: list[ParsedPdfItem] = []
    assets: list[ParsedImageAsset] = []
    total = len(sources)
    for source_index, source in enumerate(sources, start=1):
        _emit_image_progress(progress_callback, status="running", current=source_index - 1, total=total, source=source)
        asset_id = str(uuid4())
        object_path = store.put_image_asset(
            doc_id=doc_id,
            asset_id=asset_id,
            filename=source.filename,
            content=source.content,
            content_type=source.content_type,
        )
        width, height = image_dimensions(source.content)
        effective_bbox = source.bbox or _standalone_image_bbox(source, width, height)
        analysis = _analyze_image_source(source, analyzer)
        extracted_text = _clean_text(analysis.extracted_text)
        caption = _clean_text(analysis.caption)
        flags = sorted(
            {
                *source.quality_flags,
                "source:vision",
                *(analysis.quality_flags or []),
                *(["source:ocr"] if extracted_text else []),
            }
        )
        assets.append(
            ParsedImageAsset(
                id=asset_id,
                source_kind=source.source_kind,
                object_path=object_path,
                content_type=source.content_type,
                content_hash=hashlib.sha256(source.content).hexdigest(),
                page=source.page,
                bbox=effective_bbox,
                width=width,
                height=height,
                extracted_text=extracted_text or None,
                caption=caption or None,
                confidence=analysis.confidence,
                quality_flags=flags,
            )
        )
        text = _image_item_text(extracted_text, caption)
        if not text:
            _emit_image_progress(progress_callback, status="complete", current=source_index, total=total, source=source)
            continue
        items.append(
            ParsedPdfItem(
                index=start_index + len(items),
                text=text,
                item_type="image_text",
                page_start=source.page,
                page_end=source.page,
                bbox=effective_bbox,
                parser=_parser_for_source_kind(source.source_kind),
                quality_flags=flags,
                confidence=analysis.confidence,
                image_asset_id=asset_id,
                image_source_kind=source.source_kind,
                image_content_type=source.content_type,
                extraction_method="vision_ocr_description",
            )
        )
        _emit_image_progress(progress_callback, status="complete", current=source_index, total=total, source=source)
    return items, assets


def _emit_image_progress(
    callback: ImageProgressCallback | None,
    *,
    status: str,
    current: int,
    total: int,
    source: ImageSource,
) -> None:
    if callback is None:
        return
    callback({
        "phase": "image_analysis",
        "status": status,
        "current": current,
        "total": total,
        "page": source.page,
        "source_kind": source.source_kind,
        "filename": source.filename,
    })


def image_dimensions(content: bytes) -> tuple[int | None, int | None]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise WorkerStepError("image_dependency_missing", "Pillow dependency is not installed.") from exc
    try:
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
            return int(width), int(height)
    except Exception as exc:
        raise WorkerStepError("image_parse_failed", "Image metadata could not be read.") from exc


def _analyze_image_source(source: ImageSource, analyzer: ImageAnalyzer) -> ImageAnalysisResult:
    analysis_content, analysis_content_type, analysis_flags = _vision_analysis_payload(source)
    analysis = analyzer.analyze_image(content=analysis_content, content_type=analysis_content_type)
    if "vision_input_resized" not in analysis_flags or not _analysis_needs_original_retry(source, analysis):
        return _with_analysis_flags(analysis, analysis_flags)
    original_analysis = analyzer.analyze_image(content=source.content, content_type=source.content_type)
    retry_flags = ["vision_retry_original"]
    if not _analysis_needs_original_retry(source, original_analysis) or _analysis_signal_score(original_analysis) >= _analysis_signal_score(analysis):
        return _with_analysis_flags(original_analysis, retry_flags)
    return _with_analysis_flags(analysis, [*analysis_flags, "vision_retry_original_no_improvement"])


def _vision_analysis_payload(source: ImageSource) -> tuple[bytes, str, list[str]]:
    max_long_edge = _vision_analysis_max_long_edge(source)
    if max_long_edge <= 0:
        return source.content, source.content_type, []
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise WorkerStepError("image_dependency_missing", "Pillow dependency is not installed.") from exc
    try:
        with Image.open(BytesIO(source.content)) as image:
            image = ImageOps.exif_transpose(image)
            width, height = image.size
            long_edge = max(width, height)
            if long_edge <= max_long_edge:
                return source.content, source.content_type, []
            scale = max_long_edge / long_edge
            target_size = (max(1, round(width * scale)), max(1, round(height * scale)))
            resized = image.resize(target_size, Image.Resampling.LANCZOS)
            output = BytesIO()
            if source.content_type == PNG_CONTENT_TYPE:
                resized.save(output, format="PNG", optimize=True)
            else:
                if resized.mode not in {"RGB", "L"}:
                    resized = resized.convert("RGB")
                resized.save(output, format="JPEG", quality=90, optimize=True)
            return output.getvalue(), source.content_type, ["vision_input_resized"]
    except Exception:
        return source.content, source.content_type, []


def _vision_analysis_max_long_edge(source: ImageSource) -> int:
    flags = set(source.quality_flags)
    if source.source_kind in {"pdf_page_image", "pdf_scanned_visual_region", "standalone_image"}:
        return VISION_ANALYSIS_OCR_MAX_LONG_EDGE
    if flags.intersection({"scanned_or_handwritten_candidate", "vision_layout_repair_candidate", "visual_region_crop"}):
        return VISION_ANALYSIS_OCR_MAX_LONG_EDGE
    return VISION_ANALYSIS_MAX_LONG_EDGE


def _analysis_needs_original_retry(source: ImageSource, analysis: ImageAnalysisResult) -> bool:
    flags = set(analysis.quality_flags or [])
    if any(flag.startswith("vision_failed") for flag in flags) or flags.intersection({"vision_empty_response"}):
        return True
    if analysis.confidence is not None and analysis.confidence < VISION_RETRY_MIN_CONFIDENCE:
        return True
    extracted_text = _clean_text(analysis.extracted_text)
    caption = _clean_text(analysis.caption)
    if not extracted_text and not caption:
        return True
    return _source_expects_readable_text(source) and not extracted_text


def _source_expects_readable_text(source: ImageSource) -> bool:
    flags = set(source.quality_flags)
    return source.source_kind in {"pdf_page_image", "pdf_scanned_visual_region", "standalone_image"} or bool(
        flags.intersection({"scanned_or_handwritten_candidate", "vision_layout_repair_candidate"})
    )


def _analysis_signal_score(analysis: ImageAnalysisResult) -> float:
    score = float(len(_clean_text(analysis.extracted_text)) * 2 + len(_clean_text(analysis.caption)))
    if analysis.confidence is not None:
        score += analysis.confidence * 50
    if any(str(flag).startswith("vision_failed") for flag in (analysis.quality_flags or [])):
        score -= 100
    return score


def _with_analysis_flags(analysis: ImageAnalysisResult, extra_flags: list[str]) -> ImageAnalysisResult:
    if not extra_flags:
        return analysis
    return ImageAnalysisResult(
        extracted_text=analysis.extracted_text,
        caption=analysis.caption,
        confidence=analysis.confidence,
        quality_flags=sorted({*(analysis.quality_flags or []), *extra_flags}),
    )


def _standalone_image_bbox(source: ImageSource, width: int | None, height: int | None) -> BBox | None:
    if source.source_kind != "standalone_image" or source.page != 1 or not width or not height:
        return None
    return (0.0, 0.0, float(width), float(height))


def _normalized_image_source(
    content: bytes,
    *,
    filename: str,
    source_kind: str,
    quality_flags: list[str],
    page: int | None,
    bbox: BBox | None,
    target_content_type: str,
    page_area_ratio: float | None = None,
) -> ImageSource:
    normalized, content_type = normalize_image(content, target_content_type=target_content_type)
    return ImageSource(
        content=normalized,
        content_type=content_type,
        filename=_normalized_filename(filename, content_type),
        source_kind=source_kind,
        quality_flags=quality_flags,
        page=page,
        bbox=bbox,
        page_area_ratio=page_area_ratio,
    )


def normalize_image(content: bytes, *, target_content_type: str) -> tuple[bytes, str]:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise WorkerStepError("image_dependency_missing", "Pillow dependency is not installed.") from exc
    try:
        with Image.open(BytesIO(content)) as image:
            image = ImageOps.exif_transpose(image)
            output = BytesIO()
            if target_content_type == PNG_CONTENT_TYPE:
                image.save(output, format="PNG")
                return output.getvalue(), PNG_CONTENT_TYPE
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            image.save(output, format="JPEG", quality=90, optimize=True)
            return output.getvalue(), JPEG_CONTENT_TYPE
    except Exception as exc:
        raise WorkerStepError("image_parse_failed", "Image could not be parsed.") from exc


def _page_blocks(page: object) -> list[dict[str, object]]:
    get_text = getattr(page, "get_text", None)
    if get_text is None:
        return []
    try:
        blocks = get_text("dict").get("blocks", [])
    except Exception:
        return []
    return [block for block in blocks if isinstance(block, dict)]


def _fitz_module() -> object:
    try:
        import fitz
    except ImportError as exc:
        raise WorkerStepError("pdf_dependency_missing", "PyMuPDF dependency is not installed.") from exc
    return fitz


def _document_page_numbers(parsed_items: list[ParsedPdfItem], image_sources: list[ImageSource]) -> set[int]:
    pages = {
        page
        for item in parsed_items
        for page in (item.page_start, item.page_end)
        if isinstance(page, int) and page > 0
    }
    pages.update(source.page for source in image_sources if isinstance(source.page, int) and source.page > 0)
    return pages


def _full_page_sources_by_page(sources: list[ImageSource]) -> dict[int, ImageSource]:
    result: dict[int, ImageSource] = {}
    for source in sources:
        if source.page is None or not _is_full_page_pdf_source(source):
            continue
        current = result.get(source.page)
        if current is None or (source.page_area_ratio or 0.0) > (current.page_area_ratio or 0.0):
            result[source.page] = source
    return result


def _embedded_sources_by_page(sources: list[ImageSource]) -> dict[int, list[ImageSource]]:
    result: dict[int, list[ImageSource]] = {}
    for source in sources:
        if source.page is None or _is_full_page_pdf_source(source):
            continue
        result.setdefault(source.page, []).append(source)
    return result


def _page_class_without_scanned_detection(
    page_no: int,
    full_page_sources: dict[int, ImageSource],
    embedded_sources: dict[int, list[ImageSource]],
) -> str:
    if full_page_sources.get(page_no) is not None:
        return "ambiguous"
    return "native_mixed" if embedded_sources.get(page_no) else "native_text_only"


def _is_full_page_pdf_source(source: ImageSource) -> bool:
    return (
        source.source_kind in {"pdf_page_image", "pdf_page_layout"}
        or "full_page_image_candidate" in source.quality_flags
        or (source.page_area_ratio is not None and source.page_area_ratio >= 0.75)
    )


def _parsed_text_chars_by_page(items: list[ParsedPdfItem]) -> dict[int, int]:
    chars_by_page: dict[int, int] = {}
    for item in items:
        if item.item_type == "image_text":
            continue
        text_chars = len(" ".join(str(item.text or "").split()))
        if text_chars <= 0:
            continue
        for page in _item_pages(item):
            chars_by_page[page] = chars_by_page.get(page, 0) + text_chars
    return chars_by_page


def _parsed_text_bboxes_by_page(items: list[ParsedPdfItem]) -> dict[int, list[BBox]]:
    boxes_by_page: dict[int, list[BBox]] = {}
    for item in items:
        if item.item_type == "image_text" or item.bbox is None:
            continue
        for page in _item_pages(item):
            boxes_by_page.setdefault(page, []).append(item.bbox)
    return boxes_by_page


def _visual_cue_bboxes_by_page(items: list[ParsedPdfItem]) -> dict[int, list[BBox]]:
    boxes_by_page: dict[int, list[BBox]] = {}
    for item in items:
        if item.bbox is None or not VISUAL_CUE_PATTERN.search(item.text or ""):
            continue
        for page in _item_pages(item):
            boxes_by_page.setdefault(page, []).append(item.bbox)
    return boxes_by_page


def _domain_visual_cue_pages(items: list[ParsedPdfItem]) -> set[int]:
    pages: set[int] = set()
    for item in items:
        if not DOMAIN_VISUAL_CUE_PATTERN.search(item.text or ""):
            continue
        pages.update(_item_pages(item))
    return pages


def _item_pages(item: ParsedPdfItem) -> list[int]:
    pages = [page for page in (item.page_start, item.page_end) if isinstance(page, int) and page > 0]
    if not pages:
        return []
    return list(range(min(pages), max(pages) + 1))


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


@dataclass(frozen=True)
class _PdfImageCandidate:
    page_no: int
    filename: str
    source_kind: str
    quality_flags: list[str]
    bbox: BBox | None
    page_area_ratio: float | None
    target_content_type: str
    content: bytes | None = None
    render_page: bool = False


def _pdf_image_candidates_for_page(page: object, page_no: int) -> list[_PdfImageCandidate]:
    blocks = _page_blocks(page)
    image_blocks = [block for block in blocks if block.get("type") == 1]
    page_bbox = _page_bbox(page)
    page_area = _bbox_area(page_bbox) if page_bbox is not None else 0.0
    page_text_chars = _page_text_chars(page)
    candidates: list[_PdfImageCandidate] = []
    for image_index, block in enumerate(image_blocks):
        bbox = _bbox(block.get("bbox"))
        raw = block.get("image")
        if not isinstance(raw, bytes) or not raw or bbox is None or _bbox_area(bbox) < 1024:
            continue
        content_type = _content_type_for_extension(str(block.get("ext") or ""))
        if content_type not in {JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE}:
            content_type = PNG_CONTENT_TYPE
        source_kind, flags = _pdf_image_source_kind_and_flags(
            bbox=bbox,
            page_area=page_area,
            page_text_chars=page_text_chars,
        )
        candidates.append(
            _PdfImageCandidate(
                page_no=page_no,
                filename=f"page-{page_no}-image-{image_index + 1}.{_extension_for_content_type(content_type)}",
                source_kind=source_kind,
                quality_flags=flags,
                bbox=bbox,
                page_area_ratio=_bbox_area(bbox) / page_area if page_area > 0 else None,
                target_content_type=content_type,
                content=raw,
            )
        )
    if not candidates and page_text_chars < 40:
        candidates.append(
            _PdfImageCandidate(
                page_no=page_no,
                filename=f"page-{page_no}.png",
                source_kind="pdf_page_image",
                quality_flags=["source:pdf_page_image", "scanned_or_handwritten_candidate", "vision_layout_repair_candidate"],
                bbox=page_bbox,
                page_area_ratio=1.0,
                target_content_type=PNG_CONTENT_TYPE,
                render_page=True,
            )
        )
    return candidates


def _best_full_page_candidate(candidates: list[_PdfImageCandidate]) -> _PdfImageCandidate | None:
    full_page_candidates = [candidate for candidate in candidates if _is_full_page_candidate(candidate)]
    if not full_page_candidates:
        return None
    return max(full_page_candidates, key=lambda candidate: candidate.page_area_ratio or 0.0)


def _page_class_without_scanned_detection_for_candidates(
    full_page_candidate: _PdfImageCandidate | None,
    embedded_candidates: list[_PdfImageCandidate],
) -> str:
    if full_page_candidate is not None:
        return "ambiguous"
    return "native_mixed" if embedded_candidates else "native_text_only"


def _materialize_pdf_image_candidates(
    document: object,
    candidates: list[_PdfImageCandidate],
    *,
    page_text_chars: dict[int, int],
    visual_region_pages: frozenset[int],
    fallback_pages: frozenset[int],
) -> tuple[list[ImageSource], int]:
    sources: list[ImageSource] = []
    skipped_unnecessary_count = 0
    for candidate in candidates:
        if _pdf_image_candidate_score(candidate, page_text_chars, visual_region_pages, fallback_pages) <= 0:
            skipped_unnecessary_count += 1
            continue
        try:
            content = _candidate_content(document, candidate)
            if not content:
                continue
            sources.append(
                _normalized_image_source(
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


def _candidate_content(document: object, candidate: _PdfImageCandidate) -> bytes | None:
    if not candidate.render_page:
        return candidate.content
    page = document.load_page(candidate.page_no - 1)
    return page.get_pixmap(dpi=150).tobytes("png")


def _pdf_image_candidate_score(
    candidate: _PdfImageCandidate,
    page_text_chars: dict[int, int],
    visual_region_pages: frozenset[int],
    fallback_pages: frozenset[int],
) -> int:
    weak_page = page_text_chars.get(candidate.page_no, 0) < PDF_IMAGE_WEAK_TEXT_CHARS
    if _is_full_page_candidate(candidate):
        if candidate.page_no in fallback_pages:
            return 80
        if candidate.page_no in visual_region_pages:
            return 0
        return 80 if weak_page else 0
    area_ratio = candidate.page_area_ratio
    if weak_page and (area_ratio is None or area_ratio >= PDF_IMAGE_MIN_WEAK_PAGE_AREA_RATIO):
        return 100
    if "large_image_candidate" in candidate.quality_flags:
        return 110
    if area_ratio is not None and area_ratio >= PDF_IMAGE_MIN_FIGURE_AREA_RATIO:
        return 110
    return 0


def _is_full_page_candidate(candidate: _PdfImageCandidate) -> bool:
    return (
        candidate.source_kind in {"pdf_page_image", "pdf_page_layout"}
        or "full_page_image_candidate" in candidate.quality_flags
        or (candidate.page_area_ratio is not None and candidate.page_area_ratio >= PDF_IMAGE_FULL_PAGE_AREA_RATIO)
    )


@dataclass(frozen=True)
class _VisualRegion:
    content: bytes
    bbox: BBox
    page_area_ratio: float
    quality_flags: tuple[str, ...] = ()


def _scanned_visual_regions_for_page(
    page: object,
    text_bboxes: list[BBox],
    *,
    visual_cue_bboxes: list[BBox],
    domain_visual_cue: bool,
    min_area_ratio: float,
    max_regions: int,
    text_mask_padding_px: int,
) -> tuple[list[_VisualRegion], int, bool, int, int]:
    if max_regions == 0:
        return [], 0, False, 0, 0
    unlimited = max_regions < 0
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError as exc:
        raise WorkerStepError("image_dependency_missing", "Pillow dependency is not installed.") from exc

    pixmap = page.get_pixmap(dpi=150, alpha=False)
    rendered = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")
    width, height = rendered.size
    page_rect = getattr(page, "rect", None)
    page_width = float(getattr(page_rect, "width", width) or width)
    page_height = float(getattr(page_rect, "height", height) or height)
    layout_regions = _layout_visual_regions_for_page(
        page,
        rendered=rendered,
        page_width=page_width,
        page_height=page_height,
        min_area_ratio=min_area_ratio,
        max_regions=max_regions,
    )
    if layout_regions:
        return layout_regions, 0, False, 0, 0
    max_mask_dim = 640
    scale = min(1.0, max_mask_dim / max(width, height))
    mask_width = max(1, int(width * scale))
    mask_height = max(1, int(height * scale))
    grayscale = rendered.convert("L")
    if scale < 1.0:
        grayscale = grayscale.resize((mask_width, mask_height))
    mask = grayscale.point(lambda pixel: 255 if pixel < 245 else 0).filter(ImageFilter.MaxFilter(5))
    draw = ImageDraw.Draw(mask)
    x_scale = mask_width / page_width
    y_scale = mask_height / page_height
    padding = int(text_mask_padding_px * scale)
    for bbox in text_bboxes:
        left = max(0, int(bbox[0] * x_scale) - padding)
        top = max(0, int(bbox[1] * y_scale) - padding)
        right = min(mask_width, int(bbox[2] * x_scale) + padding)
        bottom = min(mask_height, int(bbox[3] * y_scale) + padding)
        if right > left and bottom > top:
            draw.rectangle((left, top, right, bottom), fill=0)

    components = _connected_foreground_components(mask)
    regions: list[_VisualRegion] = []
    tiny_count = 0
    ambiguous = False
    cue_region_count = 0
    small_region_count = 0
    cue_mode = bool(visual_cue_bboxes)
    small_min_area_ratio = min_area_ratio if not cue_mode else max(0.004, min_area_ratio * 0.18)
    for left, top, right, bottom, foreground_pixels in components:
        bbox_area_ratio = ((right - left) * (bottom - top)) / max(1, mask_width * mask_height)
        if bbox_area_ratio > 0.85:
            ambiguous = True
            continue
        if bbox_area_ratio < small_min_area_ratio or foreground_pixels < 40:
            tiny_count += 1
            continue
        region_flags: tuple[str, ...] = ()
        if bbox_area_ratio < min_area_ratio:
            region_flags = ("small_visual_region_crop", "visual_cue_region_crop")
            if domain_visual_cue:
                region_flags = (*region_flags, "domain_visual_cue_crop")
            small_region_count += 1
        region = _visual_region_from_mask_bbox(
            rendered,
            mask_bbox=(left, top, right, bottom),
            scale=scale,
            page_width=page_width,
            page_height=page_height,
            quality_flags=region_flags,
        )
        if region is None:
            tiny_count += 1
            continue
        regions.append(region)

    if cue_mode and (unlimited or len(regions) < max_regions):
        context_regions = _visual_cue_context_regions(
            rendered,
            components,
            visual_cue_bboxes=visual_cue_bboxes,
            mask_size=(mask_width, mask_height),
            scale=scale,
            page_width=page_width,
            page_height=page_height,
            small_min_area_ratio=small_min_area_ratio,
            domain_visual_cue=domain_visual_cue,
        )
        for region in context_regions:
            if any(_region_overlap(region.bbox, existing.bbox) > 0.65 for existing in regions):
                continue
            regions.append(region)
            cue_region_count += 1
            if not unlimited and len(regions) >= max_regions:
                break
    regions.sort(key=lambda region: (0 if "visual_cue_context_crop" in region.quality_flags else 1, -region.page_area_ratio))
    return (regions if unlimited else regions[:max_regions]), tiny_count, ambiguous, cue_region_count, small_region_count


def _visual_region_from_mask_bbox(
    rendered: object,
    *,
    mask_bbox: tuple[int, int, int, int],
    scale: float,
    page_width: float,
    page_height: float,
    quality_flags: tuple[str, ...] = (),
) -> _VisualRegion | None:
    width, height = rendered.size
    left, top, right, bottom = mask_bbox
    crop_left = max(0, int(left / scale) - 4)
    crop_top = max(0, int(top / scale) - 4)
    crop_right = min(width, int(right / scale) + 4)
    crop_bottom = min(height, int(bottom / scale) + 4)
    return _visual_region_from_pixel_bbox(
        rendered,
        pixel_bbox=(crop_left, crop_top, crop_right, crop_bottom),
        page_width=page_width,
        page_height=page_height,
        quality_flags=quality_flags,
    )


def _layout_visual_regions_for_page(
    page: object,
    *,
    rendered: object,
    page_width: float,
    page_height: float,
    min_area_ratio: float,
    max_regions: int,
) -> list[_VisualRegion]:
    if max_regions == 0:
        return []
    page_area = max(1.0, page_width * page_height)
    min_layout_area_ratio = max(0.005, min_area_ratio * 0.25)
    regions: list[_VisualRegion] = []
    try:
        layout_rows = prepare_page_layout(page)
    except WorkerStepError:
        return []
    for row in layout_rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        label = str(row[4]).strip().lower()
        if label not in LAYOUT_VISUAL_LABELS:
            continue
        bbox = _bbox(row[:4])
        if bbox is None:
            continue
        area_ratio = _bbox_area(bbox) / page_area
        if area_ratio < min_layout_area_ratio:
            continue
        region = _visual_region_from_pdf_bbox(
            rendered,
            pdf_bbox=bbox,
            page_width=page_width,
            page_height=page_height,
            quality_flags=("layout_model_region_crop",),
        )
        if region is not None:
            regions.append(region)
    regions.sort(key=lambda region: (region.bbox[1], region.bbox[0], -region.page_area_ratio))
    return regions if max_regions < 0 else regions[:max_regions]


def _visual_region_from_pdf_bbox(
    rendered: object,
    *,
    pdf_bbox: BBox,
    page_width: float,
    page_height: float,
    quality_flags: tuple[str, ...] = (),
) -> _VisualRegion | None:
    width, height = rendered.size
    left, top, right, bottom = pdf_bbox
    pixel_bbox = (
        max(0, math.floor(left / page_width * width) - 8),
        max(0, math.floor(top / page_height * height) - 8),
        min(width, math.ceil(right / page_width * width) + 8),
        min(height, math.ceil(bottom / page_height * height) + 8),
    )
    return _visual_region_from_pixel_bbox(
        rendered,
        pixel_bbox=pixel_bbox,
        page_width=page_width,
        page_height=page_height,
        quality_flags=quality_flags,
    )


def _visual_region_from_pixel_bbox(
    rendered: object,
    *,
    pixel_bbox: tuple[int, int, int, int],
    page_width: float,
    page_height: float,
    quality_flags: tuple[str, ...] = (),
) -> _VisualRegion | None:
    width, height = rendered.size
    crop_left, crop_top, crop_right, crop_bottom = pixel_bbox
    if crop_right <= crop_left or crop_bottom <= crop_top:
        return None
    crop = rendered.crop((crop_left, crop_top, crop_right, crop_bottom))
    output = BytesIO()
    crop.save(output, format="PNG")
    pdf_bbox = (
        crop_left / width * page_width,
        crop_top / height * page_height,
        crop_right / width * page_width,
        crop_bottom / height * page_height,
    )
    return _VisualRegion(
        content=output.getvalue(),
        bbox=pdf_bbox,
        page_area_ratio=((pdf_bbox[2] - pdf_bbox[0]) * (pdf_bbox[3] - pdf_bbox[1])) / max(1.0, page_width * page_height),
        quality_flags=quality_flags,
    )


def _visual_cue_context_regions(
    rendered: object,
    components: list[tuple[int, int, int, int, int]],
    *,
    visual_cue_bboxes: list[BBox],
    mask_size: tuple[int, int],
    scale: float,
    page_width: float,
    page_height: float,
    small_min_area_ratio: float,
    domain_visual_cue: bool,
) -> list[_VisualRegion]:
    mask_width, mask_height = mask_size
    x_scale = mask_width / page_width
    y_scale = mask_height / page_height
    regions: list[_VisualRegion] = []
    for cue_bbox in visual_cue_bboxes:
        cue_left = int(cue_bbox[0] * x_scale)
        cue_top = int(cue_bbox[1] * y_scale)
        cue_right = int(cue_bbox[2] * x_scale)
        cue_bottom = int(cue_bbox[3] * y_scale)
        search_box = (
            max(0, cue_left - int(mask_width * 0.45)),
            max(0, cue_top - int(mask_height * 0.38)),
            min(mask_width, cue_right + int(mask_width * 0.45)),
            min(mask_height, cue_bottom + int(mask_height * 0.45)),
        )
        candidates = [
            component
            for component in components
            if _component_center_inside(component, search_box)
            and _component_area_ratio(component, mask_width, mask_height) >= small_min_area_ratio * 0.4
        ]
        if not candidates:
            continue
        left = min(component[0] for component in candidates)
        top = min(component[1] for component in candidates)
        right = max(component[2] for component in candidates)
        bottom = max(component[3] for component in candidates)
        if ((right - left) * (bottom - top)) / max(1, mask_width * mask_height) > 0.5:
            continue
        flags = ("visual_cue_context_crop", "visual_cue_region_crop")
        if domain_visual_cue:
            flags = (*flags, "domain_visual_cue_crop")
        region = _visual_region_from_mask_bbox(
            rendered,
            mask_bbox=(left, top, right, bottom),
            scale=scale,
            page_width=page_width,
            page_height=page_height,
            quality_flags=flags,
        )
        if region is not None:
            regions.append(region)
    return regions


def _component_center_inside(component: tuple[int, int, int, int, int], bbox: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom, _ = component
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    return bbox[0] <= center_x <= bbox[2] and bbox[1] <= center_y <= bbox[3]


def _component_area_ratio(component: tuple[int, int, int, int, int], width: int, height: int) -> float:
    left, top, right, bottom, _ = component
    return ((right - left) * (bottom - top)) / max(1, width * height)


def _region_overlap(a: BBox, b: BBox) -> float:
    left, top, right, bottom = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if right <= left or bottom <= top:
        return 0.0
    overlap = (right - left) * (bottom - top)
    return overlap / max(1.0, min(_bbox_area(a), _bbox_area(b)))


def _connected_foreground_components(mask: object) -> list[tuple[int, int, int, int, int]]:
    width, height = mask.size
    data = mask.tobytes()
    visited = bytearray(len(data))
    components: list[tuple[int, int, int, int, int]] = []
    for index, value in enumerate(data):
        if value == 0 or visited[index]:
            continue
        stack = [index]
        visited[index] = 1
        min_x = max_x = index % width
        min_y = max_y = index // width
        count = 0
        while stack:
            current = stack.pop()
            count += 1
            x = current % width
            y = current // width
            if x < min_x:
                min_x = x
            elif x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            elif y > max_y:
                max_y = y
            for neighbor in _foreground_neighbors(current, x, y, width, height):
                if not visited[neighbor] and data[neighbor] != 0:
                    visited[neighbor] = 1
                    stack.append(neighbor)
        components.append((min_x, min_y, max_x + 1, max_y + 1, count))
    return components


def _foreground_neighbors(index: int, x: int, y: int, width: int, height: int) -> tuple[int, ...]:
    neighbors: list[int] = []
    if x > 0:
        neighbors.append(index - 1)
    if x + 1 < width:
        neighbors.append(index + 1)
    if y > 0:
        neighbors.append(index - width)
    if y + 1 < height:
        neighbors.append(index + width)
    return tuple(neighbors)


def _visual_region_sources_from_regions(
    *,
    page_no: int,
    regions: list[_VisualRegion],
    full_page_quality_flags: list[str],
) -> list[ImageSource]:
    sources: list[ImageSource] = []
    for index, region in enumerate(regions, start=1):
        try:
            sources.append(
                _normalized_image_source(
                    region.content,
                    filename=f"page-{page_no}-visual-region-{index}.png",
                    source_kind="pdf_scanned_visual_region",
                    quality_flags=sorted(
                        {
                            "source:pdf_page_image",
                            "source:visual_region_crop",
                            "scanned_mixed_page",
                            "visual_region_crop",
                            *region.quality_flags,
                            *full_page_quality_flags,
                        }
                    ),
                    page=page_no,
                    bbox=region.bbox,
                    target_content_type=PNG_CONTENT_TYPE,
                    page_area_ratio=region.page_area_ratio,
                )
            )
        except WorkerStepError:
            continue
    return sources


def _bbox(value: object) -> BBox | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        left, top, right, bottom = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def _page_bbox(page: object) -> BBox | None:
    rect = getattr(page, "rect", None)
    width = getattr(rect, "width", None)
    height = getattr(rect, "height", None)
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        return None
    return (0.0, 0.0, float(width), float(height))


def _bbox_area(bbox: BBox) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _pdf_image_source_kind_and_flags(*, bbox: BBox, page_area: float, page_text_chars: int) -> tuple[str, list[str]]:
    area_ratio = _bbox_area(bbox) / page_area if page_area > 0 else 0.0
    if page_text_chars < 40 and area_ratio >= 0.75:
        return (
            "pdf_page_image",
            [
                "source:pdf_page_image",
                "scanned_or_handwritten_candidate",
                "vision_layout_repair_candidate",
                "full_page_image_candidate",
            ],
        )
    flags = ["source:pdf_image"]
    if area_ratio >= 0.75:
        flags.append("full_page_image_candidate")
    elif area_ratio >= 0.08:
        flags.append("large_image_candidate")
    elif area_ratio < 0.015:
        flags.append("small_image_candidate")
    return "pdf_image", flags


def _page_text_chars(page: object) -> int:
    get_text = getattr(page, "get_text", None)
    if get_text is None:
        return 0
    try:
        return len(" ".join(str(get_text("text")).split()))
    except Exception:
        return 0


def _content_type_for_filename(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return JPEG_CONTENT_TYPE
    if lowered.endswith(".png"):
        return PNG_CONTENT_TYPE
    return "application/octet-stream"


def _target_content_type_for_standalone(content_type: str | None, filename: str) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized in {JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE}:
        return normalized
    detected = _content_type_for_filename(filename)
    if detected in {JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE}:
        return detected
    return JPEG_CONTENT_TYPE


def _content_type_for_extension(extension: str) -> str:
    normalized = extension.strip().lower().lstrip(".")
    if normalized in {"jpg", "jpeg"}:
        return JPEG_CONTENT_TYPE
    if normalized == "png":
        return PNG_CONTENT_TYPE
    return "application/octet-stream"


def _extension_for_content_type(content_type: str) -> str:
    return "png" if content_type == PNG_CONTENT_TYPE else "jpg"


def _normalized_filename(filename: str, content_type: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0] or "image"
    return f"{stem}.{_extension_for_content_type(content_type)}"


def _image_item_text(extracted_text: str, caption: str) -> str:
    parts = []
    if extracted_text:
        parts.append(f"Visible image text:\n{extracted_text}")
    if caption:
        parts.append(f"Image description:\n{caption}")
    return "\n\n".join(parts).strip()


def _standalone_image_placeholder_item(source: ImageSource, asset: ParsedImageAsset) -> ParsedPdfItem:
    return ParsedPdfItem(
        index=0,
        text=f"Image file: {source.filename}\n\nVision analysis returned no readable text or description.",
        item_type="image_text",
        page_start=source.page,
        page_end=source.page,
        bbox=asset.bbox,
        parser="image",
        quality_flags=sorted({*asset.quality_flags, "vision_empty_result"}),
        confidence=asset.confidence,
        image_asset_id=asset.id,
        image_source_kind=source.source_kind,
        image_content_type=asset.content_type,
        extraction_method="vision_ocr_description",
    )


def _clean_text(value: str) -> str:
    return "\n".join(line.strip() for line in str(value or "").splitlines() if line.strip()).strip()


def _parser_for_source_kind(source_kind: str) -> str:
    if source_kind == "docx_media":
        return "docx_image"
    if source_kind.startswith("pdf"):
        return "pdf_image"
    return "image"
