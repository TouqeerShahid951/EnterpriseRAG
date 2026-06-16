"""Object storage adapters for extracted document image assets."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import re
from typing import Protocol
from urllib.parse import urlparse

from ..core.config import settings


IMAGE_ASSET_PREFIX = "processed"


@dataclass(frozen=True)
class StoredDocumentImageAsset:
    object_path: str
    size_bytes: int
    content_type: str


@dataclass(frozen=True)
class StoredDocumentImageAssetContent:
    content: bytes
    content_type: str
    filename: str


class DocumentImageAssetStorage(Protocol):
    def put(self, *, doc_id: str, asset_id: str, filename: str, content: bytes, content_type: str) -> StoredDocumentImageAsset: ...
    def read(self, object_path: str) -> StoredDocumentImageAssetContent: ...
    def delete(self, object_path: str) -> None: ...


class LocalDocumentImageAssetStorage:
    def __init__(self, root_dir: str) -> None:
        self.root_dir = Path(root_dir)

    def put(self, *, doc_id: str, asset_id: str, filename: str, content: bytes, content_type: str) -> StoredDocumentImageAsset:
        safe_name = _safe_filename(filename)
        target = self.root_dir / IMAGE_ASSET_PREFIX / _safe_segment(doc_id) / "images" / f"{_safe_segment(asset_id)}-{safe_name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return StoredDocumentImageAsset(object_path=str(target), size_bytes=len(content), content_type=content_type)

    def read(self, object_path: str) -> StoredDocumentImageAssetContent:
        target = self._safe_local_path(object_path)
        try:
            content = target.read_bytes()
        except OSError as exc:
            raise RuntimeError("unable to read local document image asset") from exc
        return StoredDocumentImageAssetContent(content=content, content_type=_content_type_for(target.name), filename=target.name)

    def delete(self, object_path: str) -> None:
        target = self._safe_local_path(object_path)
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError("unable to delete local document image asset") from exc

    def _safe_local_path(self, object_path: str) -> Path:
        root = self.root_dir.resolve()
        target = Path(object_path)
        if not target.is_absolute():
            target = self.root_dir / target
        target = target.resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise RuntimeError("refusing to access image asset outside the configured storage directory") from exc
        return target


class MinioDocumentImageAssetStorage:
    def __init__(self, *, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool) -> None:
        try:
            from minio import Minio
        except ImportError as exc:
            raise RuntimeError("minio package is required for MinIO document image asset storage") from exc
        self.bucket = bucket
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)

    def put(self, *, doc_id: str, asset_id: str, filename: str, content: bytes, content_type: str) -> StoredDocumentImageAsset:
        safe_name = _safe_filename(filename)
        object_name = f"{IMAGE_ASSET_PREFIX}/{_safe_segment(doc_id)}/images/{_safe_segment(asset_id)}-{safe_name}"
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
        self.client.put_object(self.bucket, object_name, BytesIO(content), length=len(content), content_type=content_type)
        return StoredDocumentImageAsset(object_path=f"minio://{self.bucket}/{object_name}", size_bytes=len(content), content_type=content_type)

    def read(self, object_path: str) -> StoredDocumentImageAssetContent:
        bucket, object_name = self._parse_object_path(object_path)
        try:
            stat = self.client.stat_object(bucket, object_name)
            response = self.client.get_object(bucket, object_name)
            try:
                content = response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception as exc:
            raise RuntimeError("unable to read MinIO document image asset") from exc
        return StoredDocumentImageAssetContent(
            content=content,
            content_type=getattr(stat, "content_type", None) or _content_type_for(object_name),
            filename=Path(object_name).name,
        )

    def delete(self, object_path: str) -> None:
        bucket, object_name = self._parse_object_path(object_path)
        try:
            self.client.remove_object(bucket, object_name)
        except Exception as exc:
            raise RuntimeError("unable to delete MinIO document image asset") from exc

    def _parse_object_path(self, object_path: str) -> tuple[str, str]:
        parsed = urlparse(object_path)
        object_name = parsed.path.lstrip("/")
        if parsed.scheme != "minio" or parsed.netloc != self.bucket or not object_name:
            raise RuntimeError("document image asset path is not a valid MinIO object for this bucket")
        if not object_name.startswith(f"{IMAGE_ASSET_PREFIX}/"):
            raise RuntimeError("refusing to read a non-image-asset object")
        return parsed.netloc, object_name


def _safe_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-") or "asset"


def _safe_filename(filename: str) -> str:
    candidate = filename.strip().split("/")[-1].split("\\")[-1]
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate).strip(".-")
    return candidate or "image.jpg"


def _content_type_for(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".png"):
        return "image/png"
    return "application/octet-stream"


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
        raise RuntimeError(f"unsupported document image asset storage backend: {settings.upload_storage_backend}")
    return LocalDocumentImageAssetStorage(settings.upload_storage_dir)


def get_document_image_asset_storage() -> DocumentImageAssetStorage:
    return default_document_image_asset_storage()
