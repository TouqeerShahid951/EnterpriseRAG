"""Typed worker failures surfaced as safe job errors."""

from __future__ import annotations


class WorkerStepError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


class UnsupportedPdfError(WorkerStepError):
    def __init__(self) -> None:
        super().__init__("unsupported_pdf_type", "PDF does not contain enough native text for this milestone.")


class UnsupportedDocumentError(WorkerStepError):
    def __init__(self) -> None:
        super().__init__("unsupported_document_type", "Document format is not supported for ingestion.")


class HumanReviewRequired(RuntimeError):
    def __init__(self, *, review_batch_id: str) -> None:
        super().__init__("human review required")
        self.review_batch_id = review_batch_id


class IngestJobCancelled(RuntimeError):
    def __init__(self, *, job_id: str) -> None:
        super().__init__("ingestion job was cancelled")
        self.job_id = job_id


class EmbeddingUnavailable(WorkerStepError):
    def __init__(self, message: str = "The embedding model is temporarily unavailable.") -> None:
        super().__init__("embedding_unavailable", message)
