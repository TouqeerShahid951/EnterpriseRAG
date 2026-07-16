"""Composition provider for workspace ingestion configuration persistence."""

from __future__ import annotations

from functools import lru_cache

from rag.core.config import Settings, settings
from rag.ingestion.adapters.configuration_memory import InMemoryIngestConfigRepository
from rag.ingestion.adapters.configuration_postgres import PostgresIngestConfigRepository
from .models import IngestConfigRecord, IngestConfigRepository
from rag.ingestion.quality import normalize_ingestion_quality_preset


def effective_ingest_config(
    *,
    config: Settings = settings,
    repo: IngestConfigRepository | None = None,
) -> IngestConfigRecord:
    repository = repo or ingest_config_repository_from_settings(config)
    return repository.get_active() or IngestConfigRecord(
        worker_concurrency=config.ingest_worker_boot_concurrency,
        quality_preset=normalize_ingestion_quality_preset(
            config.ingestion_quality_preset
        ),
        ocr_review_confidence_threshold=config.ocr_review_confidence_threshold,
        pdf_image_review_threshold=config.pdf_image_review_threshold,
        vision_layout_repair_enabled=False,
        graph_enrichment_enabled=False,
        source="env",
    )


def ingest_config_repository_from_settings(
    config: Settings,
) -> IngestConfigRepository:
    if config.document_repository == "memory":
        return InMemoryIngestConfigRepository()
    return PostgresIngestConfigRepository(config.database_url)


@lru_cache
def default_ingest_config_repository() -> IngestConfigRepository:
    return ingest_config_repository_from_settings(settings)


def get_ingest_config_repository() -> IngestConfigRepository:
    return default_ingest_config_repository()
