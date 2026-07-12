"""Public document repository dependency."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from ..core.config import settings
from .document_memory import InMemoryDocumentRepository
from .document_models import (
    AuditEventRecord,
    DocumentImageAssetRecord,
    DocumentRecord,
    DocumentRepository,
    HumanReviewRepository,
    ImageReviewBatchRecord,
    ImageReviewCandidateRecord,
    ImageReviewDecisionRecord,
    ImageReviewRepository,
    IngestJobRecord,
    ReviewBatchRecord,
    ReviewDecisionRecord,
    ReviewItemRecord,
)
from .document_postgres import PostgresDocumentRepository
from .human_review_postgres import PostgresHumanReviewRepository
from .image_review_postgres import PostgresImageReviewRepository


@lru_cache
def default_document_repository() -> DocumentRepository:
    if settings.document_repository == "memory":
        return InMemoryDocumentRepository()
    return PostgresDocumentRepository(settings.database_url)


def get_document_repository() -> DocumentRepository:
    return default_document_repository()


def get_human_review_repository(
    document_repo: Annotated[DocumentRepository, Depends(get_document_repository)],
) -> HumanReviewRepository:
    if isinstance(document_repo, PostgresDocumentRepository):
        return PostgresHumanReviewRepository(document_repo.database_url)
    if isinstance(document_repo, InMemoryDocumentRepository):
        return document_repo
    raise RuntimeError("human-review repository must be configured for this document adapter")


def get_image_review_repository(
    document_repo: Annotated[DocumentRepository, Depends(get_document_repository)],
) -> ImageReviewRepository:
    if isinstance(document_repo, PostgresDocumentRepository):
        return PostgresImageReviewRepository(document_repo.database_url)
    if isinstance(document_repo, InMemoryDocumentRepository):
        return document_repo
    raise RuntimeError("image-review repository must be configured for this document adapter")


__all__ = [
    "DocumentRecord",
    "DocumentImageAssetRecord",
    "ImageReviewBatchRecord",
    "ImageReviewCandidateRecord",
    "ImageReviewDecisionRecord",
    "ImageReviewRepository",
    "DocumentRepository",
    "AuditEventRecord",
    "InMemoryDocumentRepository",
    "IngestJobRecord",
    "HumanReviewRepository",
    "ReviewBatchRecord",
    "ReviewDecisionRecord",
    "ReviewItemRecord",
    "PostgresDocumentRepository",
    "get_document_repository",
    "get_human_review_repository",
    "get_image_review_repository",
]
