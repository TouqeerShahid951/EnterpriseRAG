from __future__ import annotations

from types import SimpleNamespace

import pytest

from rag.ingestion.contracts import IngestJobPayload
from rag.ingestion.errors import HumanReviewRequired
from rag.ingestion.parsers.models import DocumentParseResult, ParsedImageAsset, ParsedPdfItem
from rag.ingestion.pipeline import steps


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
            ocr_review_confidence_threshold=0.9,
        ),
    )

    assert [item.text for item in state["parsed_items"]] == ["Stored parsed text.", "Image description:\nApproved figure."]
    assert storage.reads == ["minio://processed/review-candidate.png"]
    assert backend.parser_provenance == {"routing_mode": "image_review_resume", "image_analysis_selected_count": 1}
    assert backend.replaced_assets[0]["id"] == "asset-1"
    assert backend.updates[-1]["status"] == "processing"


def test_image_review_resume_requires_ocr_approval_then_resumes_without_reanalysis(monkeypatch) -> None:
    backend = FakeBackend()
    item = ParsedPdfItem(
        index=0, text="Visible image text:\nUncertain text\n\nImage description:\nA form.",
        item_type="image_text", page_start=2, page_end=2,
        confidence=0.5, quality_flags=["source:ocr", "ocr_image_consolidated"],
        extraction_method="vision_ocr_description", quote_texts=["Uncertain text"],
    )
    calls = []
    monkeypatch.setattr(steps, "resume_pdf_image_review", lambda *args, **kwargs: (
        calls.append(True) or DocumentParseResult(items=[item], provenance={})
    ))
    batches = []
    backend.create_review_batch = lambda **kwargs: batches.append(kwargs) or "ocr-batch"
    payload = IngestJobPayload(
        job_id="job-1", doc_id="doc-1", file_path="memory://doc.pdf", group_path="/ops",
        effective_date=None, supersedes=[], content_type="application/pdf", image_review_batch_id="batch-1",
    )
    deps = SimpleNamespace(
        backend=backend, storage=FakeStorage(), image_asset_writer=object(), vision=object(),
        ocr_review_confidence_threshold=0.9,
    )
    with pytest.raises(HumanReviewRequired):
        steps.extract_text({"payload": payload, "file_bytes": b"unused"}, deps)
    assert len(batches) == 1
    assert batches[0]["review_items"][0]["partial_text"] == "Uncertain text"
    assert batches[0]["resume_payload"]["image_review_batch_id"] == "batch-1"
    assert backend.updates[-1]["status"] == "human_review"
    backend.get_review_batch_parsed_items = lambda **kwargs: batches[0]["parsed_items"]
    resumed_payload = IngestJobPayload.from_dict({**payload.to_dict(), "review_batch_id": "ocr-batch"})
    for _ in range(2):
        result = steps.extract_text({"payload": resumed_payload, "file_bytes": b"unused"}, deps)
        assert result["parsed_items"] == [item]
    assert len(calls) == 1
    assert len(batches) == 1


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
