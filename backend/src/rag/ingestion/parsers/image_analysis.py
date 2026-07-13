"""Vision analysis and parsed-item construction for image sources."""

from __future__ import annotations

from io import BytesIO
import hashlib
from uuid import uuid4

from ..errors import UnsupportedDocumentError, WorkerStepError
from .image_contracts import (
    ImageAnalysisResult,
    ImageAnalyzer,
    ImageAssetStore,
    ImageProgressCallback,
    ImageSource,
    PNG_CONTENT_TYPE,
)
from .image_normalization import (
    image_dimensions,
    normalized_image_source,
    target_content_type_for_standalone,
)
from .models import BBox, DocumentParseResult, ParsedImageAsset, ParsedPdfItem
from .provenance import base_report

VISION_ANALYSIS_MAX_LONG_EDGE = 2048
VISION_ANALYSIS_OCR_MAX_LONG_EDGE = 2048
VISION_RETRY_MIN_CONFIDENCE = 0.5


def parse_image_document(
    file_bytes: bytes,
    *,
    doc_id: str,
    store: ImageAssetStore,
    analyzer: ImageAnalyzer,
    content_type: str | None = None,
    filename: str = "upload",
) -> DocumentParseResult:
    target_content_type = target_content_type_for_standalone(content_type, filename)
    source = normalized_image_source(
        file_bytes,
        filename=filename,
        source_kind="standalone_image",
        quality_flags=["source:image_file"],
        page=1,
        bbox=None,
        target_content_type=target_content_type,
    )
    items, assets = image_sources_to_items(
        [source], doc_id=doc_id, store=store, analyzer=analyzer
    )
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
        )
        | {"image_asset_count": len(assets)},
        assets=assets,
    )


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
        _emit_image_progress(
            progress_callback,
            status="running",
            current=source_index - 1,
            total=total,
            source=source,
        )
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
        analysis = analyze_image_source(source, analyzer)
        extracted_text = clean_text(analysis.extracted_text)
        caption = clean_text(analysis.caption)
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
        text = image_item_text(extracted_text, caption)
        if not text:
            _emit_image_progress(
                progress_callback,
                status="complete",
                current=source_index,
                total=total,
                source=source,
            )
            continue
        items.append(
            ParsedPdfItem(
                index=start_index + len(items),
                text=text,
                item_type="image_text",
                page_start=source.page,
                page_end=source.page,
                bbox=effective_bbox,
                parser=parser_for_source_kind(source.source_kind),
                quality_flags=flags,
                confidence=analysis.confidence,
                image_asset_id=asset_id,
                image_source_kind=source.source_kind,
                image_content_type=source.content_type,
                extraction_method="vision_ocr_description",
            )
        )
        _emit_image_progress(
            progress_callback,
            status="complete",
            current=source_index,
            total=total,
            source=source,
        )
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
    callback(
        {
            "phase": "image_analysis",
            "status": status,
            "current": current,
            "total": total,
            "page": source.page,
            "source_kind": source.source_kind,
            "filename": source.filename,
        }
    )


def analyze_image_source(
    source: ImageSource, analyzer: ImageAnalyzer
) -> ImageAnalysisResult:
    analysis_content, analysis_content_type, analysis_flags = vision_analysis_payload(
        source
    )
    analysis = analyzer.analyze_image(
        content=analysis_content, content_type=analysis_content_type
    )
    if (
        "vision_input_resized" not in analysis_flags
        or not _analysis_needs_original_retry(source, analysis)
    ):
        return _with_analysis_flags(analysis, analysis_flags)
    original_analysis = analyzer.analyze_image(
        content=source.content, content_type=source.content_type
    )
    retry_flags = ["vision_retry_original"]
    if not _analysis_needs_original_retry(
        source, original_analysis
    ) or _analysis_signal_score(original_analysis) >= _analysis_signal_score(analysis):
        return _with_analysis_flags(original_analysis, retry_flags)
    return _with_analysis_flags(
        analysis, [*analysis_flags, "vision_retry_original_no_improvement"]
    )


def vision_analysis_payload(source: ImageSource) -> tuple[bytes, str, list[str]]:
    max_long_edge = _vision_analysis_max_long_edge(source)
    if max_long_edge <= 0:
        return source.content, source.content_type, []
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise WorkerStepError(
            "image_dependency_missing", "Pillow dependency is not installed."
        ) from exc
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
    if source.source_kind in {
        "pdf_page_image",
        "pdf_scanned_visual_region",
        "standalone_image",
    }:
        return VISION_ANALYSIS_OCR_MAX_LONG_EDGE
    if flags.intersection(
        {
            "scanned_or_handwritten_candidate",
            "vision_layout_repair_candidate",
            "visual_region_crop",
        }
    ):
        return VISION_ANALYSIS_OCR_MAX_LONG_EDGE
    return VISION_ANALYSIS_MAX_LONG_EDGE


def _analysis_needs_original_retry(
    source: ImageSource, analysis: ImageAnalysisResult
) -> bool:
    flags = set(analysis.quality_flags or [])
    if any(flag.startswith("vision_failed") for flag in flags) or flags.intersection(
        {"vision_empty_response"}
    ):
        return True
    if (
        analysis.confidence is not None
        and analysis.confidence < VISION_RETRY_MIN_CONFIDENCE
    ):
        return True
    extracted_text = clean_text(analysis.extracted_text)
    caption = clean_text(analysis.caption)
    if not extracted_text and not caption:
        return True
    return _source_expects_readable_text(source) and not extracted_text


def _source_expects_readable_text(source: ImageSource) -> bool:
    flags = set(source.quality_flags)
    return source.source_kind in {
        "pdf_page_image",
        "pdf_scanned_visual_region",
        "standalone_image",
    } or bool(
        flags.intersection(
            {"scanned_or_handwritten_candidate", "vision_layout_repair_candidate"}
        )
    )


def _analysis_signal_score(analysis: ImageAnalysisResult) -> float:
    score = float(
        len(clean_text(analysis.extracted_text)) * 2 + len(clean_text(analysis.caption))
    )
    if analysis.confidence is not None:
        score += analysis.confidence * 50
    if any(
        str(flag).startswith("vision_failed") for flag in (analysis.quality_flags or [])
    ):
        score -= 100
    return score


def _with_analysis_flags(
    analysis: ImageAnalysisResult, extra_flags: list[str]
) -> ImageAnalysisResult:
    if not extra_flags:
        return analysis
    return ImageAnalysisResult(
        extracted_text=analysis.extracted_text,
        caption=analysis.caption,
        confidence=analysis.confidence,
        quality_flags=sorted({*(analysis.quality_flags or []), *extra_flags}),
    )


def _standalone_image_bbox(
    source: ImageSource, width: int | None, height: int | None
) -> BBox | None:
    if (
        source.source_kind != "standalone_image"
        or source.page != 1
        or not width
        or not height
    ):
        return None
    return (0.0, 0.0, float(width), float(height))


def image_item_text(extracted_text: str, caption: str) -> str:
    parts = []
    if extracted_text:
        parts.append(f"Visible image text:\n{extracted_text}")
    if caption:
        parts.append(f"Image description:\n{caption}")
    return "\n\n".join(parts).strip()


def _standalone_image_placeholder_item(
    source: ImageSource, asset: ParsedImageAsset
) -> ParsedPdfItem:
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


def clean_text(value: str) -> str:
    return "\n".join(
        line.strip() for line in str(value or "").splitlines() if line.strip()
    ).strip()


def parser_for_source_kind(source_kind: str) -> str:
    if source_kind == "docx_media":
        return "docx_image"
    if source_kind.startswith("pdf"):
        return "pdf_image"
    return "image"
