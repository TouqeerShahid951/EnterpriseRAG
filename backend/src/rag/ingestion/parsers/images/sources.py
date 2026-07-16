"""Document-container and PDF source extraction for ingestion images."""

from __future__ import annotations

from io import BytesIO
import zipfile

from rag.ingestion.errors import WorkerStepError
from rag.ingestion.parsers.images.contracts import ImageSource, JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE
from rag.ingestion.parsers.images.normalization import (
    bbox_area,
    bbox_from_value,
    content_type_for_extension,
    content_type_for_filename,
    extension_for_content_type,
    normalized_image_source,
    page_bbox,
)
from rag.ingestion.parsers.models import BBox


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
            content_type = content_type_for_filename(name)
            if content_type not in {JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE}:
                continue
            try:
                raw = archive.read(name)
            except KeyError:
                continue
            try:
                sources.append(
                    normalized_image_source(
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
        raise WorkerStepError(
            "pdf_dependency_missing", "PyMuPDF dependency is not installed."
        ) from exc
    sources: list[ImageSource] = []
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as document:
            for page_index in range(int(document.page_count)):
                page_no = page_index + 1
                page = document.load_page(page_index)
                blocks = page_blocks(page)
                image_blocks = [block for block in blocks if block.get("type") == 1]
                page_box = page_bbox(page)
                page_area = bbox_area(page_box) if page_box is not None else 0.0
                extracted_for_page = 0
                page_text_count = page_text_chars(page)
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
                    content_type = content_type_for_extension(
                        str(block.get("ext") or "")
                    )
                    if content_type not in {JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE}:
                        content_type = PNG_CONTENT_TYPE
                    source_kind, flags = pdf_image_source_kind_and_flags(
                        bbox=bbox,
                        page_area=page_area,
                        page_text_chars=page_text_count,
                    )
                    page_area_ratio = (
                        bbox_area(bbox) / page_area if page_area > 0 else None
                    )
                    try:
                        sources.append(
                            normalized_image_source(
                                raw,
                                filename=f"page-{page_no}-image-{image_index + 1}.{extension_for_content_type(content_type)}",
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
                if extracted_for_page == 0 and page_text_count < 40:
                    pixmap = page.get_pixmap(dpi=150)
                    try:
                        sources.append(
                            normalized_image_source(
                                pixmap.tobytes("png"),
                                filename=f"page-{page_no}.png",
                                source_kind="pdf_page_image",
                                quality_flags=[
                                    "source:pdf_page_image",
                                    "scanned_or_handwritten_candidate",
                                    "vision_layout_repair_candidate",
                                ],
                                page=page_no,
                                bbox=page_bbox(page),
                                page_area_ratio=1.0,
                                target_content_type=PNG_CONTENT_TYPE,
                            )
                        )
                    except WorkerStepError:
                        continue
    except WorkerStepError:
        raise
    except Exception as exc:
        raise WorkerStepError(
            "pdf_image_extract_failed", "PyMuPDF failed to extract PDF images."
        ) from exc
    return sources


def pdf_page_image_sources(
    file_bytes: bytes, pages: set[int], *, dpi: int = 150
) -> list[ImageSource]:
    if not pages:
        return []
    try:
        import fitz
    except ImportError as exc:
        raise WorkerStepError(
            "pdf_dependency_missing", "PyMuPDF dependency is not installed."
        ) from exc
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
                        normalized_image_source(
                            pixmap.tobytes("png"),
                            filename=f"page-{page_no}-layout.png",
                            source_kind="pdf_page_layout",
                            quality_flags=[
                                "source:pdf_page_image",
                                "vision_layout_repair_candidate",
                            ],
                            page=page_no,
                            bbox=page_bbox(page),
                            page_area_ratio=1.0,
                            target_content_type=PNG_CONTENT_TYPE,
                        )
                    )
                except WorkerStepError:
                    continue
    except WorkerStepError:
        raise
    except Exception as exc:
        raise WorkerStepError(
            "pdf_page_render_failed",
            "PyMuPDF failed to render PDF pages for vision layout repair.",
        ) from exc
    return sources


def page_blocks(page: object) -> list[dict[str, object]]:
    get_text = getattr(page, "get_text", None)
    if get_text is None:
        return []
    try:
        blocks = get_text("dict").get("blocks", [])
    except Exception:
        return []
    return [block for block in blocks if isinstance(block, dict)]


def fitz_module() -> object:
    try:
        import fitz
    except ImportError as exc:
        raise WorkerStepError(
            "pdf_dependency_missing", "PyMuPDF dependency is not installed."
        ) from exc
    return fitz


def pdf_image_source_kind_and_flags(
    *, bbox: BBox, page_area: float, page_text_chars: int
) -> tuple[str, list[str]]:
    area_ratio = bbox_area(bbox) / page_area if page_area > 0 else 0.0
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


def page_text_chars(page: object) -> int:
    get_text = getattr(page, "get_text", None)
    if get_text is None:
        return 0
    try:
        return len(" ".join(str(get_text("text")).split()))
    except Exception:
        return 0
