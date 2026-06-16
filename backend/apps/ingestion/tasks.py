"""Celery task entrypoints for the ingestion runtime."""

from __future__ import annotations

from typing import Any

from apps.ingestion.celery_app import celery_app
from rag_ingestion.service import run_ingest_document


@celery_app.task(bind=True, name="apps.ingestion.tasks.ingest_document")
def ingest_document(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)


@celery_app.task(bind=True, name="apps.ingestion.tasks.reextract_document_metadata")
def reextract_document_metadata(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)


@celery_app.task(bind=True, name="apps.ingestion.tasks.reextract_document_topics")
def reextract_document_topics(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)


@celery_app.task(bind=True, name="apps.ingestion.tasks.reextract_document_claims")
def reextract_document_claims(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)


@celery_app.task(bind=True, name="apps.ingestion.tasks.reextract_document_type")
def reextract_document_type(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)
