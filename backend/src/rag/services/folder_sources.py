"""Folder source adapters for scheduled ingestion."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.config import settings


@dataclass(frozen=True)
class SourceObject:
    bucket: str
    object_name: str
    size_bytes: int

    @property
    def source_path(self) -> str:
        return self.object_name

    @property
    def filename(self) -> str:
        return self.object_name.rsplit("/", 1)[-1] or self.object_name

    @property
    def object_path(self) -> str:
        return f"minio://{self.bucket}/{self.object_name}"


class MinioPrefixSource:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool,
    ) -> None:
        try:
            from minio import Minio
        except ImportError as exc:
            raise RuntimeError("minio package is required for MinIO folder sync") from exc
        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)

    def list_objects(self, *, bucket: str, prefix: str) -> list[SourceObject]:
        objects = self._client.list_objects(bucket, prefix=prefix, recursive=True)
        return [
            SourceObject(bucket=bucket, object_name=item.object_name, size_bytes=int(item.size or 0))
            for item in objects
            if item.object_name and not item.object_name.endswith("/")
        ]

    def read_object(self, *, bucket: str, object_name: str) -> bytes:
        response = self._client.get_object(bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()


def default_minio_prefix_source() -> MinioPrefixSource:
    return MinioPrefixSource(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def get_minio_prefix_source() -> MinioPrefixSource:
    return default_minio_prefix_source()

