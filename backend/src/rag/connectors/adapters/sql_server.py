"""SQL Server connector runtime adapter."""

from __future__ import annotations

from typing import Any

from ..models import ConnectorQueryResult, ConnectorTestResult
from rag.connectors.catalog.row_mapping import column_names, row_dict
from rag.connectors.catalog.introspection import (
    add_foreign_key_rows,
    add_index_rows,
    add_primary_key_rows,
    add_sample_estimate_rows,
    attach_sql_server_sample_counts,
    fetch_pyodbc_dicts,
    finalize_tables,
    sample_limit,
    tables_from_column_rows,
)
from ..sql_safety import validate_read_only_sql


class SqlServerConnector:
    connector_type = "sql_server"

    def test_connection(
        self, *, config: dict[str, Any], secrets: dict[str, Any]
    ) -> ConnectorTestResult:
        with self._connect(config, secrets) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return ConnectorTestResult(
            status="ok", message="SQL Server connection succeeded."
        )

    def introspect(
        self, *, config: dict[str, Any], secrets: dict[str, Any]
    ) -> dict[str, Any]:
        bounded_sample_limit = sample_limit(config)
        with self._connect(config, secrets) as conn:
            cursor = conn.cursor()
            tables = tables_from_column_rows(
                self.connector_type, fetch_pyodbc_dicts(cursor, SQL_SERVER_COLUMNS_SQL)
            )
            add_primary_key_rows(
                tables, fetch_pyodbc_dicts(cursor, SQL_SERVER_PRIMARY_KEYS_SQL)
            )
            add_foreign_key_rows(
                tables, fetch_pyodbc_dicts(cursor, SQL_SERVER_FOREIGN_KEYS_SQL)
            )
            add_index_rows(tables, fetch_pyodbc_dicts(cursor, SQL_SERVER_INDEXES_SQL))
            add_sample_estimate_rows(
                tables, fetch_pyodbc_dicts(cursor, SQL_SERVER_ROW_ESTIMATES_SQL)
            )
            attach_sql_server_sample_counts(cursor, tables, bounded_sample_limit)
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
            try:
                conn.autocommit = False
            except Exception:
                pass
            try:
                conn.timeout = max(1, min(timeout_seconds, 300))
            except Exception:
                pass
            cursor = conn.cursor()
            try:
                cursor.timeout = max(1, min(timeout_seconds, 300))
            except Exception:
                pass
            cursor.execute(query)
            rows = cursor.fetchmany(max(1, row_limit))
            result = ConnectorQueryResult(
                query=query,
                columns=column_names(cursor),
                rows=[row_dict(cursor, row) for row in rows],
            )
            try:
                conn.rollback()
            except Exception:
                pass
        return result

    def _connect(self, config: dict[str, Any], secrets: dict[str, Any]):
        try:
            import pyodbc
        except ImportError as exc:
            raise RuntimeError(
                "pyodbc and the native unixODBC driver manager are required for SQL Server connectors."
            ) from exc
        connection_string = sql_server_connection_string(config, secrets)
        return pyodbc.connect(
            connection_string,
            timeout=int(config.get("connect_timeout_seconds") or 10),
            readonly=True,
        )


def sql_server_connection_string(
    config: dict[str, Any], secrets: dict[str, Any]
) -> str:
    if config.get("connection_string"):
        return str(config["connection_string"])
    driver = str(config.get("driver") or "ODBC Driver 18 for SQL Server")
    server = str(config.get("server") or config.get("host") or "")
    database = str(config.get("database") or "")
    username = str(secrets.get("username") or config.get("username") or "")
    password = str(secrets.get("password") or "")
    trusted = bool(config.get("trusted_connection") or config.get("windows_auth"))
    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
        "Encrypt=yes" if config.get("encrypt", True) else "Encrypt=no",
        "TrustServerCertificate=yes"
        if config.get("trust_server_certificate", True)
        else "TrustServerCertificate=no",
    ]
    if trusted:
        parts.append("Trusted_Connection=yes")
    else:
        parts.extend([f"UID={username}", f"PWD={password}"])
    return ";".join(parts)


SQL_SERVER_COLUMNS_SQL = """
SELECT
    t.TABLE_SCHEMA AS table_schema,
    t.TABLE_NAME AS table_name,
    t.TABLE_TYPE AS table_type,
    c.COLUMN_NAME AS column_name,
    c.ORDINAL_POSITION AS ordinal_position,
    c.DATA_TYPE AS data_type,
    c.CHARACTER_MAXIMUM_LENGTH AS character_maximum_length,
    c.NUMERIC_PRECISION AS numeric_precision,
    c.NUMERIC_SCALE AS numeric_scale,
    c.IS_NULLABLE AS is_nullable
FROM INFORMATION_SCHEMA.TABLES t
JOIN INFORMATION_SCHEMA.COLUMNS c
  ON t.TABLE_SCHEMA = c.TABLE_SCHEMA
 AND t.TABLE_NAME = c.TABLE_NAME
WHERE t.TABLE_TYPE IN ('BASE TABLE', 'VIEW')
ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME, c.ORDINAL_POSITION
"""

SQL_SERVER_PRIMARY_KEYS_SQL = """
SELECT
    tc.TABLE_SCHEMA AS table_schema,
    tc.TABLE_NAME AS table_name,
    tc.CONSTRAINT_NAME AS constraint_name,
    kcu.COLUMN_NAME AS column_name,
    kcu.ORDINAL_POSITION AS ordinal_position
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
  ON tc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA
 AND tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
ORDER BY tc.TABLE_SCHEMA, tc.TABLE_NAME, tc.CONSTRAINT_NAME, kcu.ORDINAL_POSITION
"""

SQL_SERVER_FOREIGN_KEYS_SQL = """
SELECT
    fk.name AS constraint_name,
    sch.name AS table_schema,
    tab.name AS table_name,
    col.name AS column_name,
    ref_sch.name AS referenced_table_schema,
    ref_tab.name AS referenced_table_name,
    ref_col.name AS referenced_column_name,
    fkc.constraint_column_id AS ordinal_position
FROM sys.foreign_key_columns fkc
JOIN sys.foreign_keys fk ON fk.object_id = fkc.constraint_object_id
JOIN sys.tables tab ON tab.object_id = fkc.parent_object_id
JOIN sys.schemas sch ON sch.schema_id = tab.schema_id
JOIN sys.columns col ON col.object_id = tab.object_id AND col.column_id = fkc.parent_column_id
JOIN sys.tables ref_tab ON ref_tab.object_id = fkc.referenced_object_id
JOIN sys.schemas ref_sch ON ref_sch.schema_id = ref_tab.schema_id
JOIN sys.columns ref_col ON ref_col.object_id = ref_tab.object_id AND ref_col.column_id = fkc.referenced_column_id
ORDER BY sch.name, tab.name, fk.name, fkc.constraint_column_id
"""

SQL_SERVER_INDEXES_SQL = """
SELECT
    sch.name AS table_schema,
    tab.name AS table_name,
    idx.name AS index_name,
    idx.is_unique AS is_unique,
    idx.type_desc AS index_type,
    col.name AS column_name,
    ic.key_ordinal AS ordinal_position
FROM sys.indexes idx
JOIN sys.tables tab ON tab.object_id = idx.object_id
JOIN sys.schemas sch ON sch.schema_id = tab.schema_id
JOIN sys.index_columns ic ON ic.object_id = idx.object_id AND ic.index_id = idx.index_id
JOIN sys.columns col ON col.object_id = tab.object_id AND col.column_id = ic.column_id
WHERE idx.is_hypothetical = 0
  AND idx.name IS NOT NULL
ORDER BY sch.name, tab.name, idx.name, ic.key_ordinal
"""

SQL_SERVER_ROW_ESTIMATES_SQL = """
SELECT
    sch.name AS table_schema,
    tab.name AS table_name,
    SUM(part.rows) AS estimated_row_count
FROM sys.tables tab
JOIN sys.schemas sch ON sch.schema_id = tab.schema_id
JOIN sys.partitions part ON part.object_id = tab.object_id AND part.index_id IN (0, 1)
GROUP BY sch.name, tab.name
"""
