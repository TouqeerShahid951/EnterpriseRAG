"""Celery task adapters for document ingestion workflows."""

from __future__ import annotations

from typing import Any

from celery import shared_task

from .execution import run_ingest_document


@shared_task(bind=True, name="apps.ingestion.tasks.ingest_document")
def ingest_document(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)


@shared_task(bind=True, name="apps.ingestion.tasks.reextract_document_metadata")
def reextract_document_metadata(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)


@shared_task(bind=True, name="apps.ingestion.tasks.reextract_document_topics")
def reextract_document_topics(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)


@shared_task(bind=True, name="apps.ingestion.tasks.reextract_document_claims")
def reextract_document_claims(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)


@shared_task(bind=True, name="apps.ingestion.tasks.reextract_document_type")
def reextract_document_type(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)
