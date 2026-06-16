"""Object storage adapters for generated query artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import re
from typing import Protocol
from urllib.parse import urlparse
from uuid import uuid4

from ..core.config import settings


ARTIFACT_PREFIX = "generated-artifacts"


@dataclass(frozen=True)
class StoredGeneratedArtifact:
    object_path: str
    size_bytes: int
    content_type: str


@dataclass(frozen=True)
class StoredGeneratedArtifactContent:
    content: bytes
    content_type: str
    filename: str


class GeneratedArtifactStorage(Protocol):
    def put(self, *, filename: str, content: bytes, content_type: str) -> StoredGeneratedArtifact: ...
    def read(self, object_path: str) -> StoredGeneratedArtifactContent: ...


class LocalGeneratedArtifactStorage:
    def __init__(self, root_dir: str) -> None:
        self.root_dir = Path(root_dir)

    def put(self, *, filename: str, content: bytes, content_type: str) -> StoredGeneratedArtifact:
        safe_name = _safe_filename(filename)
        target = self.root_dir / ARTIFACT_PREFIX / f"{uuid4()}-{safe_name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return StoredGeneratedArtifact(
            object_path=str(target),
            size_bytes=len(content),
            content_type=content_type,
        )

    def read(self, object_path: str) -> StoredGeneratedArtifactContent:
        target = self._safe_local_path(object_path)
        try:
            content = target.read_bytes()
        except OSError as exc:
            raise RuntimeError("unable to read local generated artifact") from exc
        return StoredGeneratedArtifactContent(
            content=content,
            content_type=_content_type_for(target.name),
            filename=_original_filename(target.name),
        )

    def _safe_local_path(self, object_path: str) -> Path:
        root = self.root_dir.resolve()
        target = Path(object_path)
        if not target.is_absolute():
            target = self.root_dir / target
        target = target.resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise RuntimeError("refusing to access generated artifact outside the configured storage directory") from exc
        return target


class MinioGeneratedArtifactStorage:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool,
    ) -> None:
        try:
            from minio import Minio
        except ImportError as exc:
            raise RuntimeError("minio package is required for MinIO generated artifact storage") from exc

        self.bucket = bucket
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def put(self, *, filename: str, content: bytes, content_type: str) -> StoredGeneratedArtifact:
        safe_name = _safe_filename(filename)
        object_name = f"{ARTIFACT_PREFIX}/{uuid4()}-{safe_name}"
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
        self.client.put_object(
            self.bucket,
            object_name,
            BytesIO(content),
            length=len(content),
            content_type=content_type,
        )
        return StoredGeneratedArtifact(
            object_path=f"minio://{self.bucket}/{object_name}",
            size_bytes=len(content),
            content_type=content_type,
        )

    def read(self, object_path: str) -> StoredGeneratedArtifactContent:
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
            raise RuntimeError("unable to read MinIO generated artifact") from exc
        return StoredGeneratedArtifactContent(
            content=content,
            content_type=getattr(stat, "content_type", None) or _content_type_for(object_name),
            filename=_original_filename(Path(object_name).name),
        )

    def _parse_object_path(self, object_path: str) -> tuple[str, str]:
        parsed = urlparse(object_path)
        object_name = parsed.path.lstrip("/")
        if parsed.scheme != "minio" or parsed.netloc != self.bucket or not object_name:
            raise RuntimeError("generated artifact path is not a valid MinIO object for this bucket")
        if not object_name.startswith(f"{ARTIFACT_PREFIX}/"):
            raise RuntimeError("refusing to read a non-generated-artifact object")
        return parsed.netloc, object_name


def _safe_filename(filename: str) -> str:
    candidate = filename.strip().split("/")[-1].split("\\")[-1]
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate).strip(".-")
    return candidate or "artifact.bin"


def _original_filename(stored_name: str) -> str:
    if len(stored_name) > 37 and stored_name[36] == "-":
        return stored_name[37:] or "artifact.bin"
    return stored_name or "artifact.bin"


def _content_type_for(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lowered.endswith(".pptx"):
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if lowered.endswith(".pdf"):
        return "application/pdf"
    return "application/octet-stream"


@lru_cache
def default_generated_artifact_storage() -> GeneratedArtifactStorage:
    if settings.upload_storage_backend == "minio":
        return MinioGeneratedArtifactStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    if settings.upload_storage_backend != "local":
        raise RuntimeError(f"unsupported generated artifact storage backend: {settings.upload_storage_backend}")
    return LocalGeneratedArtifactStorage(settings.upload_storage_dir)


def get_generated_artifact_storage() -> GeneratedArtifactStorage:
    return default_generated_artifact_storage()
