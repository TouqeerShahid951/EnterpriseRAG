from __future__ import annotations

from types import SimpleNamespace

import pytest

from rag_ingestion.messages import IngestJobPayload
from rag_ingestion.parsers.models import DocumentParseResult, ParsedImageAsset, ParsedPdfItem
from rag_ingestion.stages import steps


def test_image_review_resume_skips_pdf_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = FakeBackend()
    storage = FakeStorage()

    def fail_parse(*args, **kwargs):
        raise AssertionError("image review resume should not parse the PDF again")

    def fake_resume_pdf_image_review(parsed_items, approved_sources, **kwargs):
        assert [item.text for item in parsed_items] == ["Stored parsed text."]
        assert len(approved_sources) == 1
        assert approved_sources[0].content == b"approved-image"
        assert approved_sources[0].quality_flags == ["image_review_approved", "source:pdf_image"]
        assert kwargs["candidate_count"] == 3
        return DocumentParseResult(
            items=[
                *parsed_items,
                ParsedPdfItem(
                    index=1,
                    text="Image description:\nApproved figure.",
                    item_type="image_text",
                    page_start=2,
                    page_end=2,
                    parser="pdf_image",
                    quality_flags=["source:vision"],
                ),
            ],
            provenance={"routing_mode": "image_review_resume", "image_analysis_selected_count": 1},
            assets=[
                ParsedImageAsset(
                    id="asset-1",
                    source_kind="pdf_image",
                    object_path="minio://processed/asset-1.png",
                    content_type="image/png",
                    content_hash="hash",
                    page=2,
                    quality_flags=["source:vision"],
                )
            ],
        )

    monkeypatch.setattr(steps, "parse_document", fail_parse)
    monkeypatch.setattr(steps, "resume_pdf_image_review", fake_resume_pdf_image_review)

    state = steps.extract_text(
        {
            "payload": IngestJobPayload(
                job_id="job-1",
                doc_id="doc-1",
                file_path="minio://uploads/apollo.pdf",
                group_path="/ops",
                effective_date=None,
                supersedes=[],
                content_type="application/pdf",
                image_review_batch_id="batch-1",
            ),
            "file_bytes": b"pdf-bytes",
        },
        SimpleNamespace(
            backend=backend,
            storage=storage,
            image_asset_writer=object(),
            vision=object(),
        ),
    )

    assert [item.text for item in state["parsed_items"]] == ["Stored parsed text.", "Image description:\nApproved figure."]
    assert storage.reads == ["minio://processed/review-candidate.png"]
    assert backend.parser_provenance == {"routing_mode": "image_review_resume", "image_analysis_selected_count": 1}
    assert backend.replaced_assets[0]["id"] == "asset-1"
    assert backend.updates[-1]["status"] == "processing"


class FakeBackend:
    def __init__(self) -> None:
        self.parser_provenance: dict[str, object] | None = None
        self.replaced_assets: list[dict[str, object]] = []
        self.updates: list[dict[str, object]] = []

    def get_image_review_resume(self, *, image_review_batch_id: str) -> dict[str, object]:
        assert image_review_batch_id == "batch-1"
        return {
            "parsed_items": [
                {
                    "index": 0,
                    "text": "Stored parsed text.",
                    "item_type": "text",
                    "page_start": 2,
                    "page_end": 2,
                    "parser": "pymupdf",
                    "quality_flags": ["source:pymupdf_native"],
                }
            ],
            "candidates": [
                {
                    "candidate_key": "candidate-1",
                    "filename": "review-candidate.png",
                    "source_kind": "pdf_image",
                    "page": 2,
                    "bbox": [1, 2, 3, 4],
                    "page_area_ratio": 0.2,
                    "object_path": "minio://processed/review-candidate.png",
                    "content_type": "image/png",
                    "content_hash": "hash",
                    "quality_flags": ["source:pdf_image"],
                }
            ],
            "candidate_count": 3,
        }

    def record_parser_provenance(self, *, job_id: str, provenance: dict[str, object]) -> None:
        assert job_id == "job-1"
        self.parser_provenance = provenance

    def replace_document_image_assets(self, *, doc_id: str, job_id: str, assets: list[dict[str, object]]) -> None:
        assert doc_id == "doc-1"
        assert job_id == "job-1"
        self.replaced_assets = assets

    def update_job(self, **kwargs: object) -> None:
        self.updates.append(dict(kwargs))


class FakeStorage:
    def __init__(self) -> None:
        self.reads: list[str] = []

    def read(self, file_path: str) -> bytes:
        self.reads.append(file_path)
        return b"approved-image"
