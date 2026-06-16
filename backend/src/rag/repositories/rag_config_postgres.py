"""PostgreSQL workspace RAG configuration repository."""

from __future__ import annotations

from .postgres import PostgresConnectionMixin
from .rag_config_models import ACTIVE_CONFIG_KEY, RagConfigRecord
from .rag_config_validation import record_from_row, with_updated_at


class PostgresRagConfigRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def get_active(self) -> RagConfigRecord | None:
        self._ensure_table()
        row = self._execute_optional("SELECT * FROM workspace_rag_config WHERE config_key = %s", (ACTIVE_CONFIG_KEY,))
        return record_from_row(row) if row else None

    def save_active(self, config: RagConfigRecord) -> RagConfigRecord:
        self._ensure_table()
        saved = with_updated_at(config)
        row = self._execute_one(
            """
            INSERT INTO workspace_rag_config (
                config_key, provider, base_url, embedding_base_url, reasoning_base_url, routing_base_url,
                faithfulness_base_url, ingestion_base_url, chat_model, embed_model, reasoning_model, routing_model,
                faithfulness_model, ingestion_model, vision_model, thinking_enabled, json_num_predict, retrieval_token_budget,
                reranker_model, chat_timeout_seconds, embed_timeout_seconds, health_status,
                health_message, embedding_dimension, chat_latency_ms, embed_latency_ms,
                last_checked_at, updated_by, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid, %s)
            ON CONFLICT (config_key) DO UPDATE SET
                provider = EXCLUDED.provider,
                base_url = EXCLUDED.base_url,
                embedding_base_url = EXCLUDED.embedding_base_url,
                reasoning_base_url = EXCLUDED.reasoning_base_url,
                routing_base_url = EXCLUDED.routing_base_url,
                faithfulness_base_url = EXCLUDED.faithfulness_base_url,
                ingestion_base_url = EXCLUDED.ingestion_base_url,
                chat_model = EXCLUDED.chat_model,
                embed_model = EXCLUDED.embed_model,
                reasoning_model = EXCLUDED.reasoning_model,
                routing_model = EXCLUDED.routing_model,
                faithfulness_model = EXCLUDED.faithfulness_model,
                ingestion_model = EXCLUDED.ingestion_model,
                vision_model = EXCLUDED.vision_model,
                thinking_enabled = EXCLUDED.thinking_enabled,
                json_num_predict = EXCLUDED.json_num_predict,
                retrieval_token_budget = EXCLUDED.retrieval_token_budget,
                reranker_model = EXCLUDED.reranker_model,
                chat_timeout_seconds = EXCLUDED.chat_timeout_seconds,
                embed_timeout_seconds = EXCLUDED.embed_timeout_seconds,
                health_status = EXCLUDED.health_status,
                health_message = EXCLUDED.health_message,
                embedding_dimension = EXCLUDED.embedding_dimension,
                chat_latency_ms = EXCLUDED.chat_latency_ms,
                embed_latency_ms = EXCLUDED.embed_latency_ms,
                last_checked_at = EXCLUDED.last_checked_at,
                updated_by = EXCLUDED.updated_by,
                updated_at = EXCLUDED.updated_at
            RETURNING *
            """,
            (
                ACTIVE_CONFIG_KEY,
                saved.provider,
                saved.base_url,
                saved.embedding_base_url,
                saved.effective_reasoning_base_url,
                saved.effective_routing_base_url,
                saved.effective_faithfulness_base_url,
                saved.effective_ingestion_base_url,
                saved.chat_model,
                saved.embed_model,
                saved.reasoning_model,
                saved.routing_model,
                saved.faithfulness_model,
                saved.ingestion_model,
                saved.vision_model,
                saved.thinking_enabled,
                saved.json_num_predict,
                saved.retrieval_token_budget,
                saved.reranker_model,
                saved.chat_timeout_seconds,
                saved.embed_timeout_seconds,
                saved.health_status,
                saved.health_message,
                saved.embedding_dimension,
                saved.chat_latency_ms,
                saved.embed_latency_ms,
                saved.last_checked_at,
                saved.updated_by,
                saved.updated_at,
            ),
        )
        return record_from_row(row)

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_rag_config (
                    config_key TEXT PRIMARY KEY DEFAULT 'active',
                    provider TEXT NOT NULL DEFAULT 'ollama',
                    base_url TEXT NOT NULL,
                    embedding_base_url TEXT NOT NULL,
                    reasoning_base_url TEXT NULL,
                    routing_base_url TEXT NULL,
                    faithfulness_base_url TEXT NULL,
                    ingestion_base_url TEXT NULL,
                    chat_model TEXT NOT NULL,
                    embed_model TEXT NOT NULL,
                    reasoning_model TEXT NULL,
                    routing_model TEXT NULL,
                    faithfulness_model TEXT NULL,
                    ingestion_model TEXT NULL,
                    vision_model TEXT NULL,
                    thinking_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    json_num_predict INTEGER NOT NULL DEFAULT 4096,
                    retrieval_token_budget INTEGER NOT NULL DEFAULT 12000,
                    reranker_model TEXT NOT NULL DEFAULT 'jinaai/jina-reranker-v1-turbo-en',
                    chat_timeout_seconds DOUBLE PRECISION NOT NULL DEFAULT 180,
                    embed_timeout_seconds DOUBLE PRECISION NOT NULL DEFAULT 45,
                    health_status TEXT NOT NULL DEFAULT 'unknown',
                    health_message TEXT NOT NULL DEFAULT 'Not checked.',
                    embedding_dimension INTEGER NULL,
                    chat_latency_ms INTEGER NULL,
                    embed_latency_ms INTEGER NULL,
                    last_checked_at TIMESTAMPTZ NULL,
                    updated_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT workspace_rag_config_singleton CHECK (config_key = 'active'),
                    CONSTRAINT workspace_rag_config_provider_known CHECK (provider IN ('ollama', 'vllm')),
                    CONSTRAINT workspace_rag_config_base_url_not_blank CHECK (length(btrim(base_url)) > 0),
                    CONSTRAINT workspace_rag_config_chat_model_not_blank CHECK (length(btrim(chat_model)) > 0),
                    CONSTRAINT workspace_rag_config_embed_model_not_blank CHECK (length(btrim(embed_model)) > 0),
                    CONSTRAINT workspace_rag_config_timeouts_positive CHECK (
                        chat_timeout_seconds > 0 AND embed_timeout_seconds > 0
                    ),
                    CONSTRAINT workspace_rag_config_json_num_predict_range CHECK (
                        json_num_predict BETWEEN 256 AND 32768
                    ),
                    CONSTRAINT workspace_rag_config_retrieval_token_budget_range CHECK (
                        retrieval_token_budget BETWEEN 1000 AND 200000
                    ),
                    CONSTRAINT workspace_rag_config_reranker_model_not_blank CHECK (length(btrim(reranker_model)) > 0),
                    CONSTRAINT workspace_rag_config_embedding_dimension_positive CHECK (
                        embedding_dimension IS NULL OR embedding_dimension > 0
                    )
                )
                """
            )
            conn.execute("ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS reasoning_model TEXT NULL")
            conn.execute("ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'ollama'")
            conn.execute("ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS embedding_base_url TEXT NULL")
            conn.execute("ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS reasoning_base_url TEXT NULL")
            conn.execute("ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS routing_base_url TEXT NULL")
            conn.execute("ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS faithfulness_base_url TEXT NULL")
            conn.execute("ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS ingestion_base_url TEXT NULL")
            conn.execute("UPDATE workspace_rag_config SET embedding_base_url = base_url WHERE embedding_base_url IS NULL")
            conn.execute("UPDATE workspace_rag_config SET reasoning_base_url = base_url WHERE reasoning_base_url IS NULL")
            conn.execute("UPDATE workspace_rag_config SET routing_base_url = COALESCE(reasoning_base_url, base_url) WHERE routing_base_url IS NULL")
            conn.execute("UPDATE workspace_rag_config SET faithfulness_base_url = base_url WHERE faithfulness_base_url IS NULL")
            conn.execute("UPDATE workspace_rag_config SET ingestion_base_url = base_url WHERE ingestion_base_url IS NULL")
            conn.execute("ALTER TABLE workspace_rag_config ALTER COLUMN embedding_base_url SET NOT NULL")
            conn.execute("ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS routing_model TEXT NULL")
            conn.execute("ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS ingestion_model TEXT NULL")
            conn.execute("ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS vision_model TEXT NULL")
            conn.execute("ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS thinking_enabled BOOLEAN NOT NULL DEFAULT FALSE")
            conn.execute("ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS json_num_predict INTEGER NOT NULL DEFAULT 4096")
            conn.execute("ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS retrieval_token_budget INTEGER NOT NULL DEFAULT 12000")
            conn.execute("ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS reranker_model TEXT NOT NULL DEFAULT 'jinaai/jina-reranker-v1-turbo-en'")
            conn.execute("UPDATE workspace_rag_config SET reasoning_model = routing_model WHERE reasoning_model IS NULL AND routing_model IS NOT NULL")
