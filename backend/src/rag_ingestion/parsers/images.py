"""Image extraction helpers for document ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import hashlib
from typing import Protocol
from uuid import uuid4
import zipfile

from ..errors import UnsupportedDocumentError, WorkerStepError
from .models import BBox, DocumentParseResult, ParsedImageAsset, ParsedPdfItem
from .provenance import base_report

JPEG_CONTENT_TYPE = "image/jpeg"
PNG_CONTENT_TYPE = "image/png"


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


@dataclass(frozen=True)
class ImageSource:
    content: bytes
    content_type: str
    filename: str
    source_kind: str
    quality_flags: list[str]
    page: int | None = None
    bbox: BBox | None = None


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
                for image_index, block in enumerate(image_blocks):
                    bbox = _bbox(block.get("bbox"))
                    raw = block.get("image")
                    if not isinstance(raw, bytes) or not raw or bbox is None or _bbox_area(bbox) < 1024:
                        continue
                    content_type = _content_type_for_extension(str(block.get("ext") or ""))
                    if content_type not in {JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE}:
                        content_type = PNG_CONTENT_TYPE
                    try:
                        sources.append(
                            _normalized_image_source(
                                raw,
                                filename=f"page-{page_no}-image-{image_index + 1}.{_extension_for_content_type(content_type)}",
                                source_kind="pdf_image",
                                quality_flags=["source:pdf_image"],
                                page=page_no,
                                bbox=bbox,
                                target_content_type=content_type,
                            )
                        )
                    except WorkerStepError:
                        continue
                if not image_blocks and _page_text_chars(page) < 40:
                    pixmap = page.get_pixmap(dpi=150)
                    try:
                        sources.append(
                            _normalized_image_source(
                                pixmap.tobytes("png"),
                                filename=f"page-{page_no}.png",
                                source_kind="pdf_page_image",
                                quality_flags=["source:pdf_page_image", "scanned_or_handwritten_candidate"],
                                page=page_no,
                                bbox=_page_bbox(page),
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


def image_sources_to_items(
    sources: list[ImageSource],
    *,
    doc_id: str,
    store: ImageAssetStore,
    analyzer: ImageAnalyzer,
    start_index: int = 0,
) -> tuple[list[ParsedPdfItem], list[ParsedImageAsset]]:
    items: list[ParsedPdfItem] = []
    assets: list[ParsedImageAsset] = []
    for source in sources:
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
        analysis = analyzer.analyze_image(content=source.content, content_type=source.content_type)
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
    return items, assets


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


def _clean_text(value: str) -> str:
    return "\n".join(line.strip() for line in str(value or "").splitlines() if line.strip()).strip()


def _parser_for_source_kind(source_kind: str) -> str:
    if source_kind == "docx_media":
        return "docx_image"
    if source_kind.startswith("pdf"):
        return "pdf_image"
    return "image"
