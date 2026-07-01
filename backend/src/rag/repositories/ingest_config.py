"""Persistent workspace ingestion worker configuration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import lru_cache
from typing import Protocol

from rag.shared.ingestion_quality import DEFAULT_INGESTION_QUALITY_PRESET, normalize_ingestion_quality_preset

from ..core.config import Settings, settings
from .postgres import PostgresConnectionMixin

ACTIVE_CONFIG_KEY = "active"


@dataclass(frozen=True)
class IngestConfigRecord:
    worker_concurrency: int = 1
    quality_preset: str = DEFAULT_INGESTION_QUALITY_PRESET
    ocr_review_confidence_threshold: float = 0.9
    vision_layout_repair_enabled: bool = False
    updated_by: str | None = None
    updated_at: datetime | None = None
    source: str = "workspace"


class IngestConfigRepository(Protocol):
    def get_active(self) -> IngestConfigRecord | None: ...
    def save_active(self, config: IngestConfigRecord) -> IngestConfigRecord: ...


class InMemoryIngestConfigRepository:
    def __init__(self) -> None:
        self.active: IngestConfigRecord | None = None

    def get_active(self) -> IngestConfigRecord | None:
        return self.active

    def save_active(self, config: IngestConfigRecord) -> IngestConfigRecord:
        self.active = replace(config, updated_at=datetime.now(UTC))
        return self.active


class PostgresIngestConfigRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def get_active(self) -> IngestConfigRecord | None:
        self._ensure_table()
        row = self._execute_optional(
            """
            SELECT worker_concurrency, quality_preset, ocr_review_confidence_threshold, vision_layout_repair_enabled, updated_by, updated_at
            FROM workspace_ingest_config
            WHERE config_key = %s
            """,
            (ACTIVE_CONFIG_KEY,),
        )
        if not row:
            return None
        return IngestConfigRecord(
            worker_concurrency=int(row["worker_concurrency"]),
            quality_preset=normalize_ingestion_quality_preset(row.get("quality_preset")),
            ocr_review_confidence_threshold=float(row["ocr_review_confidence_threshold"]),
            vision_layout_repair_enabled=bool(row["vision_layout_repair_enabled"]),
            updated_by=str(row["updated_by"]) if row.get("updated_by") else None,
            updated_at=row.get("updated_at"),
        )

    def save_active(self, config: IngestConfigRecord) -> IngestConfigRecord:
        self._ensure_table()
        row = self._execute_one(
            """
            INSERT INTO workspace_ingest_config (
                config_key, worker_concurrency, quality_preset, ocr_review_confidence_threshold,
                vision_layout_repair_enabled, updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s::uuid)
            ON CONFLICT (config_key) DO UPDATE SET
                worker_concurrency = EXCLUDED.worker_concurrency,
                quality_preset = EXCLUDED.quality_preset,
                ocr_review_confidence_threshold = EXCLUDED.ocr_review_confidence_threshold,
                vision_layout_repair_enabled = EXCLUDED.vision_layout_repair_enabled,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            RETURNING worker_concurrency, quality_preset, ocr_review_confidence_threshold, vision_layout_repair_enabled, updated_by, updated_at
            """,
            (
                ACTIVE_CONFIG_KEY,
                config.worker_concurrency,
                normalize_ingestion_quality_preset(config.quality_preset),
                config.ocr_review_confidence_threshold,
                config.vision_layout_repair_enabled,
                config.updated_by,
            ),
        )
        return IngestConfigRecord(
            worker_concurrency=int(row["worker_concurrency"]),
            quality_preset=normalize_ingestion_quality_preset(row.get("quality_preset")),
            ocr_review_confidence_threshold=float(row["ocr_review_confidence_threshold"]),
            vision_layout_repair_enabled=bool(row["vision_layout_repair_enabled"]),
            updated_by=str(row["updated_by"]) if row.get("updated_by") else None,
            updated_at=row.get("updated_at"),
        )

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_ingest_config (
                    config_key TEXT PRIMARY KEY DEFAULT 'active',
                    worker_concurrency INTEGER NOT NULL DEFAULT 1,
                    quality_preset TEXT NOT NULL DEFAULT 'fast',
                    ocr_review_confidence_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.9,
                    vision_layout_repair_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT workspace_ingest_config_singleton CHECK (config_key = 'active'),
                    CONSTRAINT workspace_ingest_config_concurrency CHECK (worker_concurrency BETWEEN 1 AND 10),
                    CONSTRAINT workspace_ingest_config_quality_preset CHECK (
                        quality_preset IN ('fast', 'balanced', 'high_accuracy')
                    ),
                    CONSTRAINT workspace_ingest_config_ocr_review_threshold CHECK (
                        ocr_review_confidence_threshold >= 0 AND ocr_review_confidence_threshold <= 1
                    )
                )
                """
            )
            conn.execute(
                """
                ALTER TABLE workspace_ingest_config
                ADD COLUMN IF NOT EXISTS quality_preset TEXT NOT NULL DEFAULT 'fast'
                """
            )
            conn.execute(
                """
                ALTER TABLE workspace_ingest_config
                ADD COLUMN IF NOT EXISTS ocr_review_confidence_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.9
                """
            )
            conn.execute(
                """
                ALTER TABLE workspace_ingest_config
                ADD COLUMN IF NOT EXISTS vision_layout_repair_enabled BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
            conn.execute(
                """
                ALTER TABLE workspace_ingest_config
                DROP CONSTRAINT IF EXISTS workspace_ingest_config_quality_preset
                """
            )
            conn.execute(
                """
                ALTER TABLE workspace_ingest_config
                ADD CONSTRAINT workspace_ingest_config_quality_preset CHECK (
                    quality_preset IN ('fast', 'balanced', 'high_accuracy')
                )
                """
            )
            conn.execute(
                """
                ALTER TABLE workspace_ingest_config
                DROP CONSTRAINT IF EXISTS workspace_ingest_config_ocr_review_threshold
                """
            )
            conn.execute(
                """
                ALTER TABLE workspace_ingest_config
                ADD CONSTRAINT workspace_ingest_config_ocr_review_threshold CHECK (
                    ocr_review_confidence_threshold >= 0 AND ocr_review_confidence_threshold <= 1
                )
                """
            )


def effective_ingest_config(
    *,
    config: Settings = settings,
    repo: IngestConfigRepository | None = None,
) -> IngestConfigRecord:
    repository = repo or ingest_config_repository_from_settings(config)
    return repository.get_active() or IngestConfigRecord(
        worker_concurrency=config.ingest_worker_boot_concurrency,
        quality_preset=normalize_ingestion_quality_preset(config.ingestion_quality_preset),
        ocr_review_confidence_threshold=config.ocr_review_confidence_threshold,
        vision_layout_repair_enabled=False,
        source="env",
    )


def ingest_config_repository_from_settings(config: Settings) -> IngestConfigRepository:
    if config.document_repository == "memory":
        return InMemoryIngestConfigRepository()
    return PostgresIngestConfigRepository(config.database_url)


@lru_cache
def default_ingest_config_repository() -> IngestConfigRepository:
    return ingest_config_repository_from_settings(settings)


def get_ingest_config_repository() -> IngestConfigRepository:
    return default_ingest_config_repository()
