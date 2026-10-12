"""Checkpoint validation, compression and fenced commit policy."""

from __future__ import annotations

import gzip
import hashlib
from io import BytesIO
import json
import re
import zlib
from typing import Any

from .models import CheckpointDescriptor
from .repository import CheckpointRepository

MAX_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_DECODED_BYTES = 256 * 1024 * 1024
CHECKPOINT_SCHEMA_VERSION = 2
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CheckpointTooLarge(ValueError):
    """The checkpoint exceeds its bounded wire representation."""


class CheckpointService:
    def __init__(self, repository: CheckpointRepository, storage: Any) -> None:
        self.repository = repository
        self.storage = storage

    def commit(
        self,
        *,
        job_id: str,
        document_id: str,
        run_token: str,
        stage_key: str,
        payload: dict[str, Any],
        upstream_sha256: str,
        configuration_digest: str,
        range_start: int | None = None,
        range_end: int | None = None,
        model_identity: str | None = None,
        vector_dimension: int | None = None,
    ) -> CheckpointDescriptor:
        upstream_sha256 = _digest(upstream_sha256, "upstream_sha256")
        configuration_digest = _digest(configuration_digest, "configuration_digest")
        encoded, decoded_size = encode_payload(payload)
        _validate_range(range_start, range_end)
        body_sha256 = hashlib.sha256(encoded).hexdigest()
        object_key = (
            f"ingest-checkpoints/{document_id}/{job_id}/"
            f"{_safe_stage(stage_key)}-{body_sha256}.json.gz"
        )
        self.storage.put(object_key=object_key, content=encoded)
        descriptor = CheckpointDescriptor(
            job_id=job_id,
            document_id=document_id,
            stage_key=stage_key,
            object_key=object_key,
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            body_sha256=body_sha256,
            compressed_size=len(encoded),
            decoded_size=decoded_size,
            upstream_sha256=upstream_sha256,
            configuration_digest=configuration_digest,
            range_start=range_start,
            range_end=range_end,
            model_identity=model_identity,
            vector_dimension=vector_dimension,
        )
        return self.repository.commit(descriptor, run_token=run_token)

    def load(
        self,
        *,
        job_id: str,
        run_token: str,
        stage_key: str,
        upstream_sha256: str,
        configuration_digest: str,
    ) -> tuple[CheckpointDescriptor, dict[str, Any]] | None:
        descriptor = self.repository.get(job_id=job_id, stage_key=stage_key, run_token=run_token)
        if descriptor is None:
            return None
        if (descriptor.schema_version != CHECKPOINT_SCHEMA_VERSION
            or descriptor.upstream_sha256 != _digest(upstream_sha256, "upstream_sha256")
            or descriptor.configuration_digest != _digest(configuration_digest, "configuration_digest")):
            self._invalidate(descriptor, run_token)
            return None
        try:
            content = self.storage.read(object_key=descriptor.object_key)
            return descriptor, self.load_bytes(descriptor, content)
        except (FileNotFoundError, ValueError):
            self._invalidate(descriptor, run_token)
            return None

    def _invalidate(self, descriptor: CheckpointDescriptor, run_token: str) -> None:
        if not self.repository.invalidate(descriptor, run_token=run_token):
            raise ValueError("checkpoint changed during invalidation")

    @staticmethod
    def load_bytes(descriptor: CheckpointDescriptor, content: bytes) -> dict[str, Any]:
        if len(content) > MAX_COMPRESSED_BYTES:
            raise CheckpointTooLarge("checkpoint compressed payload exceeds its limit")
        if len(content) != descriptor.compressed_size or hashlib.sha256(content).hexdigest() != descriptor.body_sha256:
            raise ValueError("checkpoint body checksum or size is invalid")
        try:
            with gzip.GzipFile(fileobj=BytesIO(content)) as stream:
                decoded = stream.read(MAX_DECODED_BYTES + 1)
        except (OSError, EOFError, zlib.error) as exc:
            raise ValueError("checkpoint body is not valid gzip") from exc
        if len(decoded) != descriptor.decoded_size or len(decoded) > MAX_DECODED_BYTES:
            raise CheckpointTooLarge("checkpoint decoded payload exceeds its limit")
        payload = json.loads(decoded, parse_constant=_reject_nonfinite)
        if not isinstance(payload, dict):
            raise ValueError("checkpoint payload must be an object")
        return payload


def encode_payload(payload: dict[str, Any]) -> tuple[bytes, int]:
    if not isinstance(payload, dict):
        raise ValueError("checkpoint payload must be an object")
    decoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    if len(decoded) > MAX_DECODED_BYTES:
        raise CheckpointTooLarge("checkpoint decoded payload exceeds its limit")
    encoded = gzip.compress(decoded, compresslevel=6, mtime=0)
    if len(encoded) > MAX_COMPRESSED_BYTES:
        raise CheckpointTooLarge("checkpoint compressed payload exceeds its limit")
    return encoded, len(decoded)


def _digest(value: str, name: str) -> str:
    if not _HEX64.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _validate_range(start: int | None, end: int | None) -> None:
    if (start is None) != (end is None) or (start is not None and end is not None and end <= start):
        raise ValueError("checkpoint range must be a valid half-open interval")


def _safe_stage(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    if not cleaned:
        raise ValueError("stage_key must contain a safe segment")
    return cleaned[:180]


def _reject_nonfinite(value: str):
    raise ValueError("checkpoint contains a nonfinite number")
