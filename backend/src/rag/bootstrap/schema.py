"""Idempotent PostgreSQL schema bootstrap for local deployments."""

from __future__ import annotations

from rag.artifact_jobs.adapters.generated_postgres import GENERATED_ARTIFACT_SCHEMA_SQL
from rag.abbreviations.schema import ABBREVIATION_SCHEMA_SQL
from rag.artifact_jobs.adapters.job_postgres import ARTIFACT_JOB_SCHEMA_SQL
from rag.artifact_jobs.adapters.schema_compat import GENERATED_ARTIFACT_COMPAT_SQL
from rag.bootstrap.base_schema import BASE_SCHEMA_SQL, DEFAULT_GROUP_CLEANUP_SQL
from rag.connectors.persistence_schema import CONNECTOR_SCHEMA_SQL
from rag.core.config import Settings, settings
from rag.documents.image_asset_schema import DOCUMENT_IMAGE_ASSET_SCHEMA_SQL
from rag.evaluations.repository import EVALUATION_SCHEMA_SQL
from rag.ingestion.adapters.configuration_postgres import PostgresIngestConfigRepository
from rag.ingestion.delivery.schema import ensure_ingest_delivery_schema
from rag.ingestion.publication.schema import ensure_ingest_publication_schema
from rag.ops.migrate_folder_ingest_cli import MIGRATION_SQL as FOLDER_INGEST_MIGRATION_SQL
from rag.ops.migrate_image_review_cli import DDL as IMAGE_REVIEW_DDL
from rag.ops.migrate_ingest_job_origin_cli import MIGRATION_SQL as INGEST_JOB_ORIGIN_MIGRATION_SQL
from rag.ops.migrate_ingest_progress_cli import DDL as INGEST_PROGRESS_DDL
from rag.ops.migrate_ingest_resilience_cli import DDL as INGEST_RESILIENCE_DDL
from rag.ops.migrate_ocr_review_cli import DDL as OCR_REVIEW_DDL
from rag.ops.migrate_parser_provenance_cli import DDL as PARSER_PROVENANCE_DDL
from rag.ops.migrate_user_deletion_cli import MIGRATION_SQL as USER_DELETION_MIGRATION_SQL
from rag.query.adapters.chat_history_postgres import CHAT_HISTORY_SCHEMA_SQL
from rag.query.adapters.rag_config_postgres import PostgresRagConfigRepository
from rag.deployment.adapters.vllm_config_postgres import PostgresVllmDeploymentConfigRepository
from rag.query.claim_schema import CLAIM_SCHEMA_SQL
from rag.shared.persistence import PostgresConnectionMixin


class _SchemaBootstrap(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def ensure_postgres_schema(config: Settings = settings) -> None:
    """Create or repair the application schema before repositories are used."""
    if config.identity_repository == "memory" and config.document_repository == "memory":
        return

    bootstrap = _SchemaBootstrap(config.database_url)
    with bootstrap._connect() as conn:
        conn.execute(BASE_SCHEMA_SQL)

    # This table is referenced by later ingestion-resilience migration SQL.
    PostgresRagConfigRepository(config.database_url).get_active()

    with bootstrap._connect() as conn:
        conn.execute(FOLDER_INGEST_MIGRATION_SQL)
        conn.execute(INGEST_JOB_ORIGIN_MIGRATION_SQL)
        conn.execute(INGEST_PROGRESS_DDL)
        conn.execute(PARSER_PROVENANCE_DDL)
        conn.execute(INGEST_RESILIENCE_DDL)
        ensure_ingest_delivery_schema(conn)
        ensure_ingest_publication_schema(conn)
        conn.execute(OCR_REVIEW_DDL)
        conn.execute(IMAGE_REVIEW_DDL)
        conn.execute(USER_DELETION_MIGRATION_SQL)
        conn.execute(CLAIM_SCHEMA_SQL)
        conn.execute(DOCUMENT_IMAGE_ASSET_SCHEMA_SQL)
        conn.execute(CHAT_HISTORY_SCHEMA_SQL)
        conn.execute(ARTIFACT_JOB_SCHEMA_SQL)
        conn.execute(GENERATED_ARTIFACT_SCHEMA_SQL)
        conn.execute(GENERATED_ARTIFACT_COMPAT_SQL)
        conn.execute(EVALUATION_SCHEMA_SQL)
        conn.execute(CONNECTOR_SCHEMA_SQL)
        conn.execute(ABBREVIATION_SCHEMA_SQL)
        conn.execute(DEFAULT_GROUP_CLEANUP_SQL)

    # Reuse repository-owned schema repair for workspace configuration tables.
    PostgresIngestConfigRepository(config.database_url).get_active()
    PostgresVllmDeploymentConfigRepository(config.database_url).get_active()
