"""Shared document upload validation helpers."""

from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO
import json
import zipfile

from fastapi import HTTPException, status

from ..core.config import settings
from .file_scanning import FileScanner, MalwareDetectedError, ScannerUnavailableError

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
JPEG_CONTENT_TYPE = "image/jpeg"
PNG_CONTENT_TYPE = "image/png"
JSON_CONTENT_TYPE = "application/json"


def validate_upload_size(content: bytes, *, max_bytes: int | None = None) -> None:
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "empty_upload", "message": "Uploaded file is empty."},
        )
    limit = settings.upload_max_bytes if max_bytes is None else max_bytes
    if len(content) > limit:
        limit_mb = limit / (1024 * 1024)
        formatted_limit = f"{limit_mb:g}"
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "upload_too_large", "message": f"Uploaded file exceeds the {formatted_limit} MB size limit."},
        )


def validate_declared_dates(effective_date: date | None, expiry_date: date | None) -> None:
    if effective_date is not None and effective_date > date.today() + timedelta(days=365):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_effective_date", "message": "Effective date cannot be more than 1 year in the future."},
        )
    if effective_date is not None and expiry_date is not None and expiry_date < effective_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_expiry_date", "message": "Expiry date cannot be before the effective date."},
        )


def validated_description(description: str | None) -> str | None:
    if description is None:
        return None
    normalized = description.strip()
    if not normalized:
        return None
    if len(normalized) > 2000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_description", "message": "Description cannot exceed 2000 characters."},
        )
    return normalized


def validated_document_type(content: bytes, filename: str | None, declared_content_type: str | None) -> str:
    declared = (declared_content_type or "").split(";", 1)[0].strip().lower()
    lowered_name = (filename or "").strip().lower()
    if _looks_like_json_upload(declared, lowered_name):
        validate_json_content(content)
        return JSON_CONTENT_TYPE
    if content.startswith(b"%PDF-") and (declared in {"", PDF_CONTENT_TYPE, "application/octet-stream"} or lowered_name.endswith(".pdf")):
        return PDF_CONTENT_TYPE
    if is_docx(content) and (declared in {"", DOCX_CONTENT_TYPE, "application/octet-stream"} or lowered_name.endswith(".docx")):
        return DOCX_CONTENT_TYPE
    if is_jpeg(content) and (declared in {"", JPEG_CONTENT_TYPE, "image/pjpeg", "application/octet-stream"} or lowered_name.endswith((".jpg", ".jpeg"))):
        return JPEG_CONTENT_TYPE
    if is_png(content) and (declared in {"", PNG_CONTENT_TYPE, "image/x-png", "application/octet-stream"} or lowered_name.endswith(".png")):
        return PNG_CONTENT_TYPE
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "unsupported_file_type", "message": "Only PDF, DOCX, JPG, PNG, and JSON uploads are accepted by this endpoint."},
    )


def is_supported_document_name(filename: str | None) -> bool:
    lowered = (filename or "").strip().lower()
    return lowered.endswith((".pdf", ".docx", ".jpg", ".jpeg", ".png", ".json"))


def validate_json_content(content: bytes) -> None:
    try:
        text = content.decode("utf-8-sig")
        json.loads(text)
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_json", "message": "JSON uploads must be valid UTF-8."},
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_json", "message": "Uploaded JSON could not be parsed."},
        ) from exc


def is_docx(content: bytes) -> bool:
    if not content.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return False
    return "[Content_Types].xml" in names and "word/document.xml" in names


def is_jpeg(content: bytes) -> bool:
    return len(content) >= 4 and content.startswith(b"\xff\xd8\xff") and content.rstrip().endswith(b"\xff\xd9")


def is_png(content: bytes) -> bool:
    return len(content) >= 8 and content.startswith(b"\x89PNG\r\n\x1a\n")


def scan_upload(scanner: FileScanner, content: bytes) -> None:
    try:
        scanner.scan(content)
    except MalwareDetectedError as exc:
        raise HTTPException(status_code=400, detail={"code": "malware_detected", "message": "Upload failed virus scanning."}) from exc
    except ScannerUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": "scanner_unavailable", "message": f"File scanner unavailable: {exc}"}) from exc


def default_filename(content_type: str) -> str:
    if content_type == DOCX_CONTENT_TYPE:
        return "upload.docx"
    if content_type == JPEG_CONTENT_TYPE:
        return "upload.jpg"
    if content_type == PNG_CONTENT_TYPE:
        return "upload.png"
    if content_type == JSON_CONTENT_TYPE:
        return "upload.json"
    return "upload.pdf"


def default_title(content_type: str) -> str:
    if content_type == DOCX_CONTENT_TYPE:
        return "Uploaded DOCX"
    if content_type == JPEG_CONTENT_TYPE:
        return "Uploaded JPG"
    if content_type == PNG_CONTENT_TYPE:
        return "Uploaded PNG"
    if content_type == JSON_CONTENT_TYPE:
        return "Uploaded JSON"
    return "Uploaded PDF"


def _looks_like_json_upload(declared: str, lowered_name: str) -> bool:
    return declared == JSON_CONTENT_TYPE or lowered_name.endswith(".json")
