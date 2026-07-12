"""Object storage adapters for generated query artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
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
    def put(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        object_key: str | None = None,
    ) -> StoredGeneratedArtifact: ...
    def read(self, object_path: str) -> StoredGeneratedArtifactContent: ...
    def delete(self, object_path: str) -> bool: ...
    def list_objects(
        self,
        *,
        modified_before: datetime,
        limit: int = 100,
    ) -> list[str]: ...


class LocalGeneratedArtifactStorage:
    def __init__(self, root_dir: str) -> None:
        self.root_dir = Path(root_dir)

    def put(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        object_key: str | None = None,
    ) -> StoredGeneratedArtifact:
        target = self.root_dir / _storage_object_name(
            filename=filename, object_key=object_key
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4()}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(target)
        except OSError as exc:
            raise RuntimeError("unable to write local generated artifact") from exc
        finally:
            temporary.unlink(missing_ok=True)
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

    def delete(self, object_path: str) -> bool:
        target = self._safe_local_path(object_path)
        try:
            target.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise RuntimeError("unable to delete local generated artifact") from exc
        return True

    def list_objects(
        self,
        *,
        modified_before: datetime,
        limit: int = 100,
    ) -> list[str]:
        _validate_object_listing(modified_before=modified_before, limit=limit)
        artifact_root = self.root_dir / ARTIFACT_PREFIX
        if not artifact_root.exists():
            return []
        candidates: list[tuple[datetime, str]] = []
        try:
            for path in artifact_root.rglob("*"):
                if not path.is_file() or (
                    path.name.startswith(".") and path.name.endswith(".tmp")
                ):
                    continue
                modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
                if modified_at <= modified_before:
                    candidates.append((modified_at, str(path.resolve())))
        except OSError as exc:
            raise RuntimeError("unable to list local generated artifacts") from exc
        return [path for _modified_at, path in sorted(candidates)[:limit]]

    def _safe_local_path(self, object_path: str) -> Path:
        root = self.root_dir.resolve()
        artifact_root = (root / ARTIFACT_PREFIX).resolve()
        target = Path(object_path)
        if not target.is_absolute():
            target = self.root_dir / target
        target = target.resolve(strict=False)
        try:
            target.relative_to(artifact_root)
        except ValueError as exc:
            raise RuntimeError(
                "refusing to access an object outside generated-artifact storage"
            ) from exc
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
            raise RuntimeError(
                "minio package is required for MinIO generated artifact storage"
            ) from exc

        self.bucket = bucket
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def put(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        object_key: str | None = None,
    ) -> StoredGeneratedArtifact:
        object_name = _storage_object_name(
            filename=filename, object_key=object_key
        ).as_posix()
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
            content_type=getattr(stat, "content_type", None)
            or _content_type_for(object_name),
            filename=_original_filename(Path(object_name).name),
        )

    def delete(self, object_path: str) -> bool:
        bucket, object_name = self._parse_object_path(object_path)
        try:
            self.client.remove_object(bucket, object_name)
        except Exception as exc:
            raise RuntimeError("unable to delete MinIO generated artifact") from exc
        return True

    def list_objects(
        self,
        *,
        modified_before: datetime,
        limit: int = 100,
    ) -> list[str]:
        _validate_object_listing(modified_before=modified_before, limit=limit)
        try:
            if not self.client.bucket_exists(self.bucket):
                return []
            candidates: list[tuple[datetime, str]] = []
            for item in self.client.list_objects(
                self.bucket,
                prefix=f"{ARTIFACT_PREFIX}/",
                recursive=True,
            ):
                modified_at = getattr(item, "last_modified", None)
                object_name = str(getattr(item, "object_name", ""))
                if isinstance(modified_at, datetime) and modified_at.tzinfo is None:
                    modified_at = modified_at.replace(tzinfo=UTC)
                if (
                    isinstance(modified_at, datetime)
                    and modified_at <= modified_before
                    and object_name
                ):
                    candidates.append(
                        (modified_at, f"minio://{self.bucket}/{object_name}")
                    )
        except Exception as exc:
            raise RuntimeError("unable to list MinIO generated artifacts") from exc
        return [path for _modified_at, path in sorted(candidates)[:limit]]

    def _parse_object_path(self, object_path: str) -> tuple[str, str]:
        parsed = urlparse(object_path)
        object_name = parsed.path.lstrip("/")
        if parsed.scheme != "minio" or parsed.netloc != self.bucket or not object_name:
            raise RuntimeError(
                "generated artifact path is not a valid MinIO object for this bucket"
            )
        if not object_name.startswith(f"{ARTIFACT_PREFIX}/"):
            raise RuntimeError("refusing to read a non-generated-artifact object")
        return parsed.netloc, object_name


def _storage_object_name(*, filename: str, object_key: str | None) -> Path:
    if object_key is None:
        return Path(ARTIFACT_PREFIX) / f"{uuid4()}-{_safe_filename(filename)}"
    return Path(ARTIFACT_PREFIX) / _safe_object_key(object_key)


def _safe_object_key(object_key: str) -> Path:
    candidate = object_key.strip()
    if not candidate or candidate.startswith(("/", "\\")) or "\\" in candidate:
        raise ValueError(
            "generated artifact object_key must be a non-empty relative path"
        )
    if re.fullmatch(r"[A-Za-z0-9._/-]+", candidate) is None:
        raise ValueError(
            "generated artifact object_key contains unsupported characters"
        )
    parts = candidate.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(
            "generated artifact object_key contains an unsafe path segment"
        )
    return Path(*parts)


def _safe_filename(filename: str) -> str:
    candidate = filename.strip().split("/")[-1].split("\\")[-1]
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate).strip(".-")
    return candidate or "artifact.bin"


def _validate_object_listing(*, modified_before: datetime, limit: int) -> None:
    if modified_before.tzinfo is None or modified_before.utcoffset() is None:
        raise ValueError("modified_before must be timezone-aware")
    if limit < 1:
        raise ValueError("limit must be positive")


def _original_filename(stored_name: str) -> str:
    if len(stored_name) > 37 and stored_name[36] == "-":
        return stored_name[37:] or "artifact.bin"
    return stored_name or "artifact.bin"


def _content_type_for(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lowered.endswith(".pptx"):
        return (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
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
        raise RuntimeError(
            f"unsupported generated artifact storage backend: {settings.upload_storage_backend}"
        )
    return LocalGeneratedArtifactStorage(settings.upload_storage_dir)


def get_generated_artifact_storage() -> GeneratedArtifactStorage:
    return default_generated_artifact_storage()
