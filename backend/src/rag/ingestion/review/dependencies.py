"""Human- and image-review repository composition."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from rag.documents.models import DocumentRepository
from rag.documents.adapters.postgres import PostgresDocumentRepository
from rag.documents.repository import get_document_repository
from rag.ingestion.adapters.human_review_postgres import PostgresHumanReviewRepository
from rag.ingestion.adapters.image_review_postgres import PostgresImageReviewRepository
from .models import HumanReviewRepository, ImageReviewRepository


def human_review_repository_for(
    document_repo: DocumentRepository,
) -> HumanReviewRepository:
    if isinstance(document_repo, PostgresDocumentRepository):
        return PostgresHumanReviewRepository(document_repo.database_url)
    if isinstance(document_repo, HumanReviewRepository):
        return document_repo
    raise RuntimeError(
        "human-review repository must be configured for this document adapter"
    )


def image_review_repository_for(
    document_repo: DocumentRepository,
) -> ImageReviewRepository:
    if isinstance(document_repo, PostgresDocumentRepository):
        return PostgresImageReviewRepository(document_repo.database_url)
    if isinstance(document_repo, ImageReviewRepository):
        return document_repo
    raise RuntimeError(
        "image-review repository must be configured for this document adapter"
    )


def get_human_review_repository(
    document_repo: Annotated[
        DocumentRepository,
        Depends(get_document_repository),
    ],
) -> HumanReviewRepository:
    return human_review_repository_for(document_repo)


def get_image_review_repository(
    document_repo: Annotated[
        DocumentRepository,
        Depends(get_document_repository),
    ],
) -> ImageReviewRepository:
    return image_review_repository_for(document_repo)


__all__ = [
    "HumanReviewRepository",
    "ImageReviewRepository",
    "PostgresHumanReviewRepository",
    "PostgresImageReviewRepository",
    "get_human_review_repository",
    "get_image_review_repository",
    "human_review_repository_for",
    "image_review_repository_for",
]
