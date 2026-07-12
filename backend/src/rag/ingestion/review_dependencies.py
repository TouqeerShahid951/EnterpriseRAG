"""Human- and image-review repository composition."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from ..repositories.document_models import DocumentRepository
from ..repositories.document_postgres import PostgresDocumentRepository
from ..repositories.documents import get_document_repository
from .adapters.human_review_postgres import PostgresHumanReviewRepository
from .adapters.image_review_postgres import PostgresImageReviewRepository
from .review_models import HumanReviewRepository, ImageReviewRepository


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
