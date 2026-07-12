"""HTTP-compatible facade for legacy folder-ingestion upload validation."""

from __future__ import annotations

from datetime import date
from typing import NoReturn

from fastapi import HTTPException, status

from ..core.config import settings
from ..documents.scanning import FileScanner
from ..documents.upload_validation import (
    DOCX_CONTENT_TYPE as DOCX_CONTENT_TYPE,
    JPEG_CONTENT_TYPE as JPEG_CONTENT_TYPE,
    JSON_CONTENT_TYPE as JSON_CONTENT_TYPE,
    PDF_CONTENT_TYPE as PDF_CONTENT_TYPE,
    PNG_CONTENT_TYPE as PNG_CONTENT_TYPE,
    UploadRejected,
    default_filename as default_filename,
    default_title as default_title,
    is_docx as is_docx,
    is_jpeg as is_jpeg,
    is_png as is_png,
    is_supported_document_name as is_supported_document_name,
    scan_upload as _scan_upload,
    validated_description as _validated_description,
    validated_document_type as _validated_document_type,
    validate_declared_dates as _validate_declared_dates,
    validate_json_content as _validate_json_content,
    validate_upload_size as _validate_upload_size,
)

_HTTP_STATUS_BY_CATEGORY = {
    "invalid": status.HTTP_400_BAD_REQUEST,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "conflict": status.HTTP_409_CONFLICT,
    "too_large": status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    "unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
}


def validate_upload_size(content: bytes, *, max_bytes: int | None = None) -> None:
    try:
        _validate_upload_size(
            content,
            max_bytes=settings.upload_max_bytes if max_bytes is None else max_bytes,
        )
    except UploadRejected as exc:
        _raise_http_exception(exc)


def validate_declared_dates(
    effective_date: date | None, expiry_date: date | None
) -> None:
    try:
        _validate_declared_dates(effective_date, expiry_date)
    except UploadRejected as exc:
        _raise_http_exception(exc)


def validated_description(description: str | None) -> str | None:
    try:
        return _validated_description(description)
    except UploadRejected as exc:
        _raise_http_exception(exc)


def validated_document_type(
    content: bytes, filename: str | None, declared_content_type: str | None
) -> str:
    try:
        return _validated_document_type(content, filename, declared_content_type)
    except UploadRejected as exc:
        _raise_http_exception(exc)


def validate_json_content(content: bytes) -> None:
    try:
        _validate_json_content(content)
    except UploadRejected as exc:
        _raise_http_exception(exc)


def scan_upload(scanner: FileScanner, content: bytes) -> None:
    try:
        _scan_upload(scanner, content)
    except UploadRejected as exc:
        _raise_http_exception(exc)


def _raise_http_exception(exc: UploadRejected) -> NoReturn:
    raise HTTPException(
        status_code=_HTTP_STATUS_BY_CATEGORY[exc.category],
        detail={"code": exc.code, "message": exc.message},
    ) from exc
