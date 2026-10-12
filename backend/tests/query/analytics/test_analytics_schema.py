from rag.query.analytics.schema import ANALYTICS_SCHEMA_SQL


def test_analytics_schema_accepts_opaque_chat_session_ids() -> None:
    assert "session_id TEXT NOT NULL" in ANALYTICS_SCHEMA_SQL
    assert "ALTER COLUMN session_id TYPE TEXT USING session_id::text" in ANALYTICS_SCHEMA_SQL
