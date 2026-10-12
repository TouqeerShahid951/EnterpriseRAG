import asyncio

import pytest
from fastapi import HTTPException

from rag.ingestion.checkpoints.routes import commit_checkpoint
from rag.ingestion.checkpoints.schemas import CheckpointCommitRequest
from rag.ingestion.checkpoints.service import CheckpointService


class _Repository:
    def commit(self, descriptor, *, run_token):
        assert run_token == "run"
        return descriptor


def test_checkpoint_route_rejects_objects_outside_document_prefix() -> None:
    payload = CheckpointCommitRequest(
        run_token="run",
        document_id="doc",
        stage_key="prepared",
        object_key="raw/doc/job/file.json.gz",
        schema_version=1,
        body_sha256="0" * 64,
        compressed_size=1,
        decoded_size=1,
        upstream_sha256="1" * 64,
        configuration_digest="2" * 64,
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(commit_checkpoint("job", payload, CheckpointService(_Repository(), None)))
    assert getattr(exc_info.value, "status_code", None) == 422


def test_checkpoint_route_accepts_a_valid_generated_reference() -> None:
    payload = CheckpointCommitRequest(
        run_token="run",
        document_id="doc",
        stage_key="dense:0:16",
        object_key="ingest-checkpoints/doc/job/dense-0-16.bin",
        schema_version=1,
        body_sha256="0" * 64,
        compressed_size=1,
        decoded_size=1,
        upstream_sha256="1" * 64,
        configuration_digest="2" * 64,
        range_start=0,
        range_end=16,
        vector_dimension=3,
    )
    response = asyncio.run(commit_checkpoint("job", payload, CheckpointService(_Repository(), None)))
    assert response.stage_key == "dense:0:16"
    assert response.document_id == "doc"
