import pytest

from rag.ingestion.checkpoints.service import CheckpointService, CheckpointTooLarge
from rag.ingestion import maintenance


class _Repository:
    def __init__(self):
        self.values = {}

    def commit(self, descriptor, *, run_token):
        self.values[(descriptor.job_id, descriptor.stage_key)] = descriptor
        return descriptor

    def get(self, *, job_id, stage_key, run_token=None):
        return self.values.get((job_id, stage_key))


class _Storage:
    def __init__(self):
        self.values = {}

    def put(self, *, object_key, content):
        self.values[object_key] = content

    def read(self, *, object_key):
        return self.values[object_key]


def test_checkpoint_commit_and_load_round_trip() -> None:
    repository = _Repository()
    storage = _Storage()
    service = CheckpointService(repository, storage)
    descriptor = service.commit(
        job_id="job",
        document_id="doc",
        run_token="run",
        stage_key="prepared",
        payload={"citation_targets": [{"exact_text": "Clause 5"}]},
        upstream_sha256="1" * 64,
        configuration_digest="2" * 64,
    )
    loaded = service.load(
        job_id="job",
        run_token="run",
        stage_key="prepared",
        upstream_sha256="1" * 64,
        configuration_digest="2" * 64,
    )
    assert loaded is not None
    assert loaded[0] == descriptor
    assert loaded[1]["citation_targets"][0]["exact_text"] == "Clause 5"


def test_checkpoint_payload_limit_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    import rag.ingestion.checkpoints.service as module

    monkeypatch.setattr(module, "MAX_DECODED_BYTES", 4)
    with pytest.raises(CheckpointTooLarge, match="decoded"):
        module.encode_payload({"large": "value"})


def test_checkpoint_cleanup_is_disabled_for_memory_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(maintenance.settings, "document_repository", "memory")
    assert maintenance.cleanup_ingestion_checkpoints() == 0
