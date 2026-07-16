"""PostgreSQL connector runtime adapter."""

from __future__ import annotations

from typing import Any

from ..models import ConnectorQueryResult, ConnectorTestResult
from rag.connectors.catalog.row_mapping import column_names, json_safe
from rag.connectors.catalog.introspection import (
    add_foreign_key_rows,
    add_index_rows,
    add_primary_key_rows,
    add_sample_estimate_rows,
    attach_postgres_sample_counts,
    fetch_postgres_dicts,
    finalize_tables,
    sample_limit,
    tables_from_column_rows,
)
from ..sql_safety import validate_read_only_sql


class PostgresConnector:
    connector_type = "postgres"

    def test_connection(
        self, *, config: dict[str, Any], secrets: dict[str, Any]
    ) -> ConnectorTestResult:
        with self._connect(config, secrets) as conn:
            prepare_postgres_session(conn, config)
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            conn.rollback()
        return ConnectorTestResult(
            status="ok", message="PostgreSQL connection succeeded."
        )

    def introspect(
        self, *, config: dict[str, Any], secrets: dict[str, Any]
    ) -> dict[str, Any]:
        bounded_sample_limit = sample_limit(config)
        with self._connect(config, secrets) as conn:
            prepare_postgres_session(conn, config)
            tables = tables_from_column_rows(
                self.connector_type, fetch_postgres_dicts(conn, POSTGRES_COLUMNS_SQL)
            )
            add_primary_key_rows(
                tables, fetch_postgres_dicts(conn, POSTGRES_PRIMARY_KEYS_SQL)
            )
            add_foreign_key_rows(
                tables, fetch_postgres_dicts(conn, POSTGRES_FOREIGN_KEYS_SQL)
            )
            add_index_rows(tables, fetch_postgres_dicts(conn, POSTGRES_INDEXES_SQL))
            add_sample_estimate_rows(
                tables, fetch_postgres_dicts(conn, POSTGRES_ROW_ESTIMATES_SQL)
            )
            attach_postgres_sample_counts(conn, tables, bounded_sample_limit)
            conn.rollback()
        return {
            "connector_type": self.connector_type,
            "tables": finalize_tables(tables),
        }

    def execute_query(
        self,
        *,
        config: dict[str, Any],
        secrets: dict[str, Any],
        query: str,
        row_limit: int,
        timeout_seconds: int,
    ) -> ConnectorQueryResult:
        query = validate_read_only_sql(query, connector_type=self.connector_type)
        with self._connect(config, secrets) as conn:
            prepare_postgres_session(
                conn, {**config, "timeout_seconds": timeout_seconds}
            )
            with conn.cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchmany(max(1, row_limit))
                result = ConnectorQueryResult(
                    query=query,
                    columns=column_names(cursor),
                    rows=[json_safe(dict(row)) for row in rows],
                )
            conn.rollback()
        return result

    def _connect(self, config: dict[str, Any], secrets: dict[str, Any]):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "psycopg is required for PostgreSQL connectors."
            ) from exc
        return psycopg.connect(
            **postgres_connection_kwargs(config, secrets), row_factory=dict_row
        )


def postgres_connection_kwargs(
    config: dict[str, Any], secrets: dict[str, Any]
) -> dict[str, Any]:
    timeout = int(config.get("connect_timeout_seconds") or 10)
    if config.get("connection_string") or config.get("dsn"):
        return {
            "conninfo": str(config.get("connection_string") or config.get("dsn")),
            "connect_timeout": timeout,
        }
    kwargs: dict[str, Any] = {
        "host": str(config.get("host") or config.get("server") or "localhost"),
        "port": int(config.get("port") or 5432),
        "dbname": str(config.get("database") or config.get("dbname") or ""),
        "user": str(
            secrets.get("username")
            or config.get("username")
            or config.get("user")
            or ""
        ),
        "password": str(secrets.get("password") or ""),
        "connect_timeout": timeout,
    }
    sslmode = str(config.get("sslmode") or config.get("ssl_mode") or "prefer")
    if sslmode:
        kwargs["sslmode"] = sslmode
    return kwargs


def prepare_postgres_session(conn, config: dict[str, Any]) -> None:
    timeout_seconds = int(config.get("timeout_seconds") or 30)
    timeout_ms = max(1, min(timeout_seconds, 300)) * 1000
    try:
        conn.read_only = True
    except Exception:
        pass
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, false)", (str(timeout_ms),)
        )


POSTGRES_COLUMNS_SQL = """
SELECT
    t.table_schema,
    t.table_name,
    t.table_type,
    c.column_name,
    c.ordinal_position,
    c.data_type,
    c.character_maximum_length,
    c.numeric_precision,
    c.numeric_scale,
    c.is_nullable
FROM information_schema.tables t
JOIN information_schema.columns c
  ON t.table_schema = c.table_schema
 AND t.table_name = c.table_name
WHERE t.table_schema NOT IN ('pg_catalog', 'information_schema')
  AND t.table_type IN ('BASE TABLE', 'VIEW')
ORDER BY t.table_schema, t.table_name, c.ordinal_position
"""

POSTGRES_PRIMARY_KEYS_SQL = """
SELECT
    tc.table_schema,
    tc.table_name,
    tc.constraint_name,
    kcu.column_name,
    kcu.ordinal_position
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_schema = kcu.constraint_schema
 AND tc.constraint_name = kcu.constraint_name
WHERE tc.constraint_type = 'PRIMARY KEY'
  AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY tc.table_schema, tc.table_name, tc.constraint_name, kcu.ordinal_position
"""

POSTGRES_FOREIGN_KEYS_SQL = """
SELECT
    child_ns.nspname AS table_schema,
    child.relname AS table_name,
    con.conname AS constraint_name,
    child_att.attname AS column_name,
    parent_ns.nspname AS referenced_table_schema,
    parent.relname AS referenced_table_name,
    parent_att.attname AS referenced_column_name,
    keys.ordinality AS ordinal_position
FROM pg_constraint con
JOIN pg_class child ON child.oid = con.conrelid
JOIN pg_namespace child_ns ON child_ns.oid = child.relnamespace
JOIN pg_class parent ON parent.oid = con.confrelid
JOIN pg_namespace parent_ns ON parent_ns.oid = parent.relnamespace
JOIN unnest(con.conkey, con.confkey) WITH ORDINALITY AS keys(child_attnum, parent_attnum, ordinality) ON true
JOIN pg_attribute child_att
  ON child_att.attrelid = child.oid
 AND child_att.attnum = keys.child_attnum
JOIN pg_attribute parent_att
  ON parent_att.attrelid = parent.oid
 AND parent_att.attnum = keys.parent_attnum
WHERE con.contype = 'f'
  AND child_ns.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY child_ns.nspname, child.relname, con.conname, keys.ordinality
"""

POSTGRES_INDEXES_SQL = """
SELECT
    schemaname AS table_schema,
    tablename AS table_name,
    indexname AS index_name,
    indexdef AS index_definition,
    position(' UNIQUE ' in indexdef) > 0 AS is_unique,
    NULL AS index_type,
    NULL AS column_name
FROM pg_indexes
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY schemaname, tablename, indexname
"""

POSTGRES_ROW_ESTIMATES_SQL = """
SELECT
    n.nspname AS table_schema,
    c.relname AS table_name,
    GREATEST(c.reltuples::bigint, 0) AS estimated_row_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
"""
