"""Worker-side checkpoint client: upload first, then fence the registry commit."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from .models import CheckpointDescriptor
from .service import CHECKPOINT_SCHEMA_VERSION, CheckpointService, encode_payload

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
logger = logging.getLogger(__name__)


class WorkerCheckpointClient:
    def __init__(self, *, backend: Any, storage: Any) -> None:
        self.backend = backend
        self.storage = storage

    def commit(
        self,
        *,
        job_id: str,
        document_id: str,
        stage_key: str,
        payload: dict[str, Any],
        upstream_sha256: str,
        configuration_digest: str,
        range_start: int | None = None,
        range_end: int | None = None,
        model_identity: str | None = None,
        vector_dimension: int | None = None,
    ) -> CheckpointDescriptor:
        encoded, decoded_size = encode_payload(payload)
        body_sha256 = hashlib.sha256(encoded).hexdigest()
        safe_stage = re.sub(r"[^A-Za-z0-9._-]+", "-", stage_key).strip(".-")[:180]
        if not safe_stage:
            raise ValueError("stage_key must contain a safe segment")
        if not _HEX64.fullmatch(upstream_sha256) or not _HEX64.fullmatch(configuration_digest):
            raise ValueError("checkpoint fingerprints must be lowercase SHA-256 digests")
        if (range_start is None) != (range_end is None) or (range_start is not None and range_end is not None and range_end <= range_start):
            raise ValueError("checkpoint range must be a valid half-open interval")
        object_key = f"ingest-checkpoints/{document_id}/{job_id}/{safe_stage}-{body_sha256}.json.gz"
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
        return self.backend.commit_checkpoint(descriptor)

    def load(
        self,
        *,
        job_id: str,
        stage_key: str,
        upstream_sha256: str,
        configuration_digest: str,
        model_identity: str | None = None,
    ) -> tuple[CheckpointDescriptor, dict[str, Any]] | None:
        descriptor = self.backend.get_checkpoint(job_id=job_id, stage_key=stage_key)
        if descriptor is None:
            return None
        if (descriptor.schema_version != CHECKPOINT_SCHEMA_VERSION
            or descriptor.upstream_sha256 != upstream_sha256
            or descriptor.configuration_digest != configuration_digest
            or (model_identity is not None and descriptor.model_identity != model_identity)):
            self.invalidate(descriptor)
            return None
        try:
            content = self.storage.read(object_key=descriptor.object_key)
            return descriptor, CheckpointService.load_bytes(descriptor, content)
        except (FileNotFoundError, ValueError):
            self.invalidate(descriptor)
            return None

    def invalidate(self, descriptor: CheckpointDescriptor) -> None:
        if not self.backend.invalidate_checkpoint(descriptor):
            raise ValueError("checkpoint changed during invalidation")
        logger.info("ingestion checkpoint invalidated job_id=%s stage=%s", descriptor.job_id, descriptor.stage_key)

    def adopt_predecessor(
        self, *, job_id: str, document_id: str, predecessor_job_id: str
    ) -> int:
        # Keep completed copies independent of predecessor cleanup, but finish an
        # interrupted copy without replacing work already produced by this job.
        local_stages = {
            item.stage_key for item in self.backend.list_checkpoints(job_id=job_id, stage_prefix="")
        }
        predecessor = self.backend.get_job_status(job_id=predecessor_job_id)
        if predecessor.doc_id != document_id or predecessor.status not in {"failed", "cancelled"}:
            return 0
        copied = 0
        for source in self.backend.list_checkpoints(job_id=predecessor_job_id, stage_prefix=""):
            if source.stage_key in local_stages or source.schema_version != CHECKPOINT_SCHEMA_VERSION:
                continue
            try:
                content = self.storage.read(object_key=source.object_key)
                CheckpointService.load_bytes(source, content)
            except (FileNotFoundError, ValueError):
                continue
            object_key = (
                f"ingest-checkpoints/{document_id}/{job_id}/"
                f"{source.stage_key.replace(':', '-')}-{source.body_sha256}.json.gz"
            )
            self.storage.put(object_key=object_key, content=content)
            self.backend.commit_checkpoint(
                CheckpointDescriptor(
                    job_id=job_id,
                    document_id=document_id,
                    stage_key=source.stage_key,
                    object_key=object_key,
                    schema_version=source.schema_version,
                    body_sha256=source.body_sha256,
                    compressed_size=source.compressed_size,
                    decoded_size=source.decoded_size,
                    upstream_sha256=source.upstream_sha256,
                    configuration_digest=source.configuration_digest,
                    range_start=source.range_start,
                    range_end=source.range_end,
                    model_identity=source.model_identity,
                    vector_dimension=source.vector_dimension,
                )
            )
            copied += 1
        return copied
