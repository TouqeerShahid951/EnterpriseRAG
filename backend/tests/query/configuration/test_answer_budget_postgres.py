"""Optional real PostgreSQL coverage for upgrading saved answer budgets."""
import os
from dataclasses import replace
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from rag.query.adapters.rag_config_postgres import PostgresRagConfigRepository
from rag.query.configuration.models import RagConfigRecord


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL required")
def test_answer_budget_upgrade_is_idempotent_and_preserves_saved_values(monkeypatch):
    database_url = os.environ["TEST_DATABASE_URL"]
    schema = "answer_budget_" + uuid4().hex
    with psycopg.connect(database_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            repo = PostgresRagConfigRepository(database_url)
            monkeypatch.setattr(repo, "_connect", lambda: psycopg.connect(
                database_url, options=f"-c search_path={schema}", row_factory=dict_row,
            ))
            with repo._connect() as conn:
                conn.execute("CREATE TABLE users (id UUID PRIMARY KEY)")
            record = RagConfigRecord(
                provider="ollama", embedding_provider="ollama", base_url="http://model:11434",
                embedding_base_url="http://model:11434", chat_model="chat", embed_model="embed",
                faithfulness_model=None, chat_timeout_seconds=30, embed_timeout_seconds=30,
                answer_output_tokens=8192, answer_context_tokens=32768,
            )
            repo.save_active(record)
            with repo._connect() as conn:
                conn.execute("ALTER TABLE workspace_rag_config DROP COLUMN answer_context_tokens")
                conn.execute("ALTER TABLE workspace_rag_config DROP COLUMN answer_output_tokens")
            migrated = repo.get_active()
            assert (migrated.answer_output_tokens, migrated.answer_context_tokens) == (4096, 16384)
            for output in (8192, 4096):
                saved = replace(record, answer_output_tokens=output)
                repo.save_active(saved)
                restored = repo.get_active()
                assert (restored.answer_output_tokens, restored.answer_context_tokens) == (output, 32768)
                assert restored.chat_model == record.chat_model
            with pytest.raises(psycopg.errors.CheckViolation), repo._connect() as conn:
                conn.execute("UPDATE workspace_rag_config SET answer_output_tokens=32768")
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
