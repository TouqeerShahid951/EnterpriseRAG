"""Bounded MinIO checkpoint I/O with explicit missing/outage semantics."""

from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO

from minio import Minio
from minio.error import MinioException, S3Error
from urllib3.exceptions import HTTPError

from ...adapters.http import ServiceRequestError
from ...config import MinioConfig
from ..service import MAX_COMPRESSED_BYTES, CheckpointTooLarge


class CheckpointObjectStorage:
    def __init__(self, config: MinioConfig) -> None:
        self.config = config

    def put(self, *, object_key: str, content: bytes) -> None:
        with _storage_errors("write"):
            client = self._client()
            if not client.bucket_exists(self.config.bucket):
                try:
                    client.make_bucket(self.config.bucket)
                except S3Error as exc:
                    if exc.code not in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}:
                        raise
            client.put_object(
                self.config.bucket, object_key, BytesIO(content), length=len(content),
                content_type="application/json+gzip",
            )

    def read(self, *, object_key: str) -> bytes:
        with _storage_errors("read"):
            response = self._client().get_object(self.config.bucket, object_key)
            try:
                content = response.read(MAX_COMPRESSED_BYTES + 1)
                if len(content) > MAX_COMPRESSED_BYTES:
                    raise CheckpointTooLarge("checkpoint compressed payload exceeds its limit")
                return content
            finally:
                response.close()
                response.release_conn()

    def delete(self, *, object_key: str) -> None:
        with _storage_errors("delete"):
            self._client().remove_object(self.config.bucket, object_key)

    def _client(self):
        return Minio(
            self.config.endpoint, access_key=self.config.access_key,
            secret_key=self.config.secret_key, secure=self.config.secure,
        )


@contextmanager
def _storage_errors(operation: str):
    try:
        yield
    except S3Error as exc:
        if operation == "read" and exc.code in {"NoSuchKey", "NoSuchObject"}:
            raise FileNotFoundError("checkpoint object is missing") from exc
        raise ServiceRequestError("checkpoint_storage", f"Checkpoint storage {operation} failed", 503) from exc
    except (MinioException, HTTPError, OSError) as exc:
        raise ServiceRequestError("checkpoint_storage", f"Checkpoint storage {operation} unavailable", 503) from exc
