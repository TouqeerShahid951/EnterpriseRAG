"""Local and MinIO adapters for uploaded document source files."""

from __future__ import annotations

from io import BytesIO
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

from ..storage import StoredUpload, StoredUploadContent


class LocalUploadStorage:
    def __init__(self, root_dir: str) -> None:
        self.root_dir = Path(root_dir)

    def put(
        self, *, filename: str, content: bytes, content_type: str | None
    ) -> StoredUpload:
        safe_name = _safe_filename(filename)
        object_name = f"{uuid4()}-{safe_name}"
        self.root_dir.mkdir(parents=True, exist_ok=True)
        target = self.root_dir / object_name
        target.write_bytes(content)
        return StoredUpload(
            object_path=str(target),
            size_bytes=len(content),
            content_type=content_type,
        )

    def read(self, object_path: str) -> StoredUploadContent:
        target = self._safe_local_path(object_path)
        try:
            content = target.read_bytes()
        except OSError as exc:
            raise RuntimeError("unable to read local upload") from exc
        return StoredUploadContent(
            content=content,
            content_type=_content_type_for(target.name),
            filename=_original_filename(target.name),
        )

    def delete(self, object_path: str) -> None:
        target = self._safe_local_path(object_path)
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError("unable to delete local upload") from exc

    def _safe_local_path(self, object_path: str) -> Path:
        root = self.root_dir.resolve()
        target = Path(object_path)
        if not target.is_absolute():
            target = self.root_dir / target
        target = target.resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(
                "refusing to access upload outside the configured storage directory"
            ) from exc
        return target


class MinioUploadStorage:
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
                "minio package is required for MinIO upload storage"
            ) from exc

        self.bucket = bucket
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def put(
        self, *, filename: str, content: bytes, content_type: str | None
    ) -> StoredUpload:
        safe_name = _safe_filename(filename)
        object_name = f"raw/{uuid4()}-{safe_name}"
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
        self.client.put_object(
            self.bucket,
            object_name,
            BytesIO(content),
            length=len(content),
            content_type=content_type or "application/octet-stream",
        )
        return StoredUpload(
            object_path=f"minio://{self.bucket}/{object_name}",
            size_bytes=len(content),
            content_type=content_type,
        )

    def read(self, object_path: str) -> StoredUploadContent:
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
            raise RuntimeError("unable to read MinIO upload") from exc
        return StoredUploadContent(
            content=content,
            content_type=getattr(stat, "content_type", None)
            or _content_type_for(object_name),
            filename=_original_filename(Path(object_name).name),
        )

    def delete(self, object_path: str) -> None:
        bucket, object_name = self._parse_object_path(object_path)
        try:
            self.client.remove_object(bucket, object_name)
        except Exception as exc:
            raise RuntimeError("unable to delete MinIO upload") from exc

    def _parse_object_path(self, object_path: str) -> tuple[str, str]:
        parsed = urlparse(object_path)
        object_name = parsed.path.lstrip("/")
        if parsed.scheme != "minio" or parsed.netloc != self.bucket or not object_name:
            raise RuntimeError(
                "uploaded file path is not a valid MinIO object for this bucket"
            )
        return parsed.netloc, object_name


def _safe_filename(filename: str) -> str:
    candidate = filename.strip().split("/")[-1].split("\\")[-1]
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate).strip(".-")
    return candidate or "upload.bin"


def _original_filename(stored_name: str) -> str:
    if len(stored_name) > 37 and stored_name[36] == "-":
        try:
            UUID(stored_name[:36])
        except ValueError:
            pass
        else:
            return stored_name[37:] or "upload.bin"
    return stored_name or "upload.bin"


def _content_type_for(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".pdf"):
        return "application/pdf"
    if lowered.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".json"):
        return "application/json"
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"
