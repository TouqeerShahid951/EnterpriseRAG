from __future__ import annotations

import time
from types import SimpleNamespace

from rag_ingestion.messages import IngestJobPayload
from rag_ingestion.stages import steps
from rag_ingestion.stages.state import IngestDependencies


class FakeBackend:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.updates: list[dict[str, object]] = []

    def update_job(self, **kwargs) -> None:
        self.updates.append(kwargs)

    def record_event(self, **kwargs) -> None:
        self.events.append(kwargs)


class SlowFallbackInference:
    chat_model = "slow-metadata-model"

    def generate_metadata(self, text: str) -> dict[str, object]:
        time.sleep(0.03)
        return {
            "_warnings": ["ollama_metadata_timeout"],
            "_metadata_errors": [
                {
                    "warning": "ollama_metadata_timeout",
                    "service": "ollama",
                    "attempts": 3,
                    "message": "request timed out",
                }
            ],
        }


def test_generate_metadata_reports_active_progress_and_degraded_reason(monkeypatch) -> None:
    monkeypatch.setattr(steps, "METADATA_PROGRESS_INTERVAL_SECONDS", 0.01)
    backend = FakeBackend()
    deps = IngestDependencies(
        backend=backend,
        storage=None,
        image_asset_writer=None,
        ollama=SlowFallbackInference(),
        vision=None,
        sparse_embedder=None,
        qdrant=None,
        min_chars_per_page=10,
        chunk_target_tokens=512,
        chunk_overlap_tokens=64,
        parent_max_tokens=2048,
    )
    payload = IngestJobPayload(
        job_id="job-1",
        doc_id="doc-1",
        file_path="memory://doc",
        group_path="/admin",
        effective_date=None,
        supersedes=[],
    )
    state = {"payload": payload, "parsed_items": [SimpleNamespace(text="image text")]}

    result = steps.generate_metadata(state, deps)

    progress_values = [int(update["progress_pct"]) for update in backend.updates]
    progress_labels = [
        update["stage_progress"]["label"]
        for update in backend.updates
        if isinstance(update.get("stage_progress"), dict)
    ]
    assert 36 in progress_values
    assert any(37 <= value <= 49 for value in progress_values)
    assert 50 in progress_values
    assert "Requesting metadata from metadata model slow-metadata-model" in progress_labels
    assert any(label.startswith("Waiting on metadata model slow-metadata-model for ") for label in progress_labels)
    assert "Using deterministic metadata fallback" in progress_labels
    assert result["warnings"] == ["ollama_metadata_timeout", "metadata_extraction_unavailable"]
    assert result["metadata"]["metadata_flags"]["metadata_error"]["message"] == "request timed out"
    assert backend.events[0]["payload"]["metadata_errors"][0]["warning"] == "ollama_metadata_timeout"


def test_docling_progress_label_names_selected_and_pdf_pages() -> None:
    label = steps._docling_progress_label(
        {
            "phase": "ocr_repair",
            "status": "running",
            "current": 8,
            "total": 40,
            "pages": (120, 121, 122, 123),
        }
    )

    assert label == "Docling OCR repairing selected pages 9-12 of 40 (PDF pages 120-123)"
