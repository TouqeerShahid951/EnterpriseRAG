"""Upload object reader for MinIO-backed ingestion."""

from __future__ import annotations

from pathlib import Path
from io import BytesIO
from urllib.parse import urlparse

from ..config import MinioConfig
from ..errors import WorkerStepError


class UploadObjectReader:
    def __init__(self, config: MinioConfig) -> None:
        self.config = config

    def read(self, file_path: str) -> bytes:
        if file_path.startswith("minio://"):
            return self._read_minio(file_path)
        path = Path(file_path)
        if not path.exists():
            raise WorkerStepError("file_not_found", "Uploaded file was not found.")
        return path.read_bytes()

    def _read_minio(self, file_path: str) -> bytes:
        try:
            from minio import Minio
        except ImportError as exc:
            raise WorkerStepError("storage_dependency_missing", "MinIO dependency is not installed.") from exc

        bucket, object_name = _parse_minio_url(file_path)
        client = Minio(
            self.config.endpoint,
            access_key=self.config.access_key,
            secret_key=self.config.secret_key,
            secure=self.config.secure,
        )
        response = client.get_object(bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()


def _parse_minio_url(file_path: str) -> tuple[str, str]:
    parsed = urlparse(file_path)
    bucket = parsed.netloc
    object_name = parsed.path.lstrip("/")
    if not bucket or not object_name:
        raise WorkerStepError("invalid_file_path", "Uploaded file path is invalid.")
    return bucket, object_name


class DocumentImageAssetWriter:
    def __init__(self, config: MinioConfig) -> None:
        self.config = config

    def put_image_asset(
        self,
        *,
        doc_id: str,
        asset_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> str:
        if not content:
            raise WorkerStepError("image_asset_empty", "Extracted image asset was empty.")
        if self.config.bucket:
            return self._put_minio(
                doc_id=doc_id,
                asset_id=asset_id,
                filename=filename,
                content=content,
                content_type=content_type,
            )
        raise WorkerStepError("image_asset_storage_unavailable", "Image asset storage is not configured.")

    def _put_minio(self, *, doc_id: str, asset_id: str, filename: str, content: bytes, content_type: str) -> str:
        try:
            from minio import Minio
        except ImportError as exc:
            raise WorkerStepError("storage_dependency_missing", "MinIO dependency is not installed.") from exc
        object_name = f"processed/{_safe_segment(doc_id)}/images/{_safe_segment(asset_id)}-{_safe_filename(filename)}"
        client = Minio(
            self.config.endpoint,
            access_key=self.config.access_key,
            secret_key=self.config.secret_key,
            secure=self.config.secure,
        )
        if not client.bucket_exists(self.config.bucket):
            client.make_bucket(self.config.bucket)
        client.put_object(self.config.bucket, object_name, BytesIO(content), length=len(content), content_type=content_type)
        return f"minio://{self.config.bucket}/{object_name}"


def _safe_segment(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in value).strip(".-")
    return cleaned or "asset"


def _safe_filename(value: str) -> str:
    name = value.strip().split("/")[-1].split("\\")[-1]
    return _safe_segment(name) or "image.jpg"
