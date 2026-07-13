"""Image decoding, normalization, and geometry helpers."""

from __future__ import annotations

from io import BytesIO

from ..errors import WorkerStepError
from .image_contracts import ImageSource, JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE
from .models import BBox


def image_dimensions(content: bytes) -> tuple[int | None, int | None]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise WorkerStepError(
            "image_dependency_missing", "Pillow dependency is not installed."
        ) from exc
    try:
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
            return int(width), int(height)
    except Exception as exc:
        raise WorkerStepError(
            "image_parse_failed", "Image metadata could not be read."
        ) from exc


def normalized_image_source(
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
    normalized, content_type = normalize_image(
        content, target_content_type=target_content_type
    )
    return ImageSource(
        content=normalized,
        content_type=content_type,
        filename=normalized_filename(filename, content_type),
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
        raise WorkerStepError(
            "image_dependency_missing", "Pillow dependency is not installed."
        ) from exc
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
        raise WorkerStepError(
            "image_parse_failed", "Image could not be parsed."
        ) from exc


def bbox_from_value(value: object) -> BBox | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        left, top, right, bottom = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def page_bbox(page: object) -> BBox | None:
    rect = getattr(page, "rect", None)
    width = getattr(rect, "width", None)
    height = getattr(rect, "height", None)
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        return None
    return (0.0, 0.0, float(width), float(height))


def bbox_area(bbox: BBox) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def content_type_for_filename(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return JPEG_CONTENT_TYPE
    if lowered.endswith(".png"):
        return PNG_CONTENT_TYPE
    return "application/octet-stream"


def target_content_type_for_standalone(content_type: str | None, filename: str) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized in {JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE}:
        return normalized
    detected = content_type_for_filename(filename)
    if detected in {JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE}:
        return detected
    return JPEG_CONTENT_TYPE


def content_type_for_extension(extension: str) -> str:
    normalized = extension.strip().lower().lstrip(".")
    if normalized in {"jpg", "jpeg"}:
        return JPEG_CONTENT_TYPE
    if normalized == "png":
        return PNG_CONTENT_TYPE
    return "application/octet-stream"


def extension_for_content_type(content_type: str) -> str:
    return "png" if content_type == PNG_CONTENT_TYPE else "jpg"


def normalized_filename(filename: str, content_type: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0] or "image"
    return f"{stem}.{extension_for_content_type(content_type)}"
