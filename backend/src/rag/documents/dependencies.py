"""Composition providers for document upload adapters."""

from __future__ import annotations

from functools import lru_cache

from ..core.config import settings
from .adapters.file_scanning import ClamAvFileScanner, NoopFileScanner
from .adapters.image_asset_storage import (
    LocalDocumentImageAssetStorage,
    MinioDocumentImageAssetStorage,
)
from .adapters.upload_storage import LocalUploadStorage, MinioUploadStorage
from .image_asset_storage import DocumentImageAssetStorage
from .scanning import FileScanner
from .storage import UploadStorage


@lru_cache
def default_upload_storage() -> UploadStorage:
    if settings.upload_storage_backend == "minio":
        return MinioUploadStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    if settings.upload_storage_backend != "local":
        raise RuntimeError(
            f"unsupported upload storage backend: {settings.upload_storage_backend}"
        )
    return LocalUploadStorage(settings.upload_storage_dir)


def get_upload_storage() -> UploadStorage:
    return default_upload_storage()


@lru_cache
def default_document_image_asset_storage() -> DocumentImageAssetStorage:
    if settings.upload_storage_backend == "minio":
        return MinioDocumentImageAssetStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    if settings.upload_storage_backend != "local":
        raise RuntimeError(
            "unsupported document image asset storage backend: "
            f"{settings.upload_storage_backend}"
        )
    return LocalDocumentImageAssetStorage(settings.upload_storage_dir)


def get_document_image_asset_storage() -> DocumentImageAssetStorage:
    return default_document_image_asset_storage()


@lru_cache
def default_file_scanner() -> FileScanner:
    if not settings.clamav_scan_enabled:
        return NoopFileScanner()
    return ClamAvFileScanner(
        host=settings.clamav_host,
        port=settings.clamav_port,
        timeout_seconds=settings.clamav_timeout_seconds,
    )


def get_file_scanner() -> FileScanner:
    return default_file_scanner()
