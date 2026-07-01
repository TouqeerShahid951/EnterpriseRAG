"""Connector runtime registry."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from .models import ConnectorQueryResult, ConnectorRecord, ConnectorTestResult
from .sql_safety import validate_read_only_sql


class Connector(Protocol):
    connector_type: str

    def test_connection(self, *, config: dict[str, Any], secrets: dict[str, Any]) -> ConnectorTestResult: ...
    def introspect(self, *, config: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]: ...
    def iter_records(
        self,
        *,
        config: dict[str, Any],
        secrets: dict[str, Any],
        selection: dict[str, Any],
        identity_fields: list[str],
        batch_size: int,
    ) -> list[ConnectorRecord]: ...
    def execute_query(
        self,
        *,
        config: dict[str, Any],
        secrets: dict[str, Any],
        query: str,
        row_limit: int,
        timeout_seconds: int,
    ) -> ConnectorQueryResult: ...


class FakeConnector:
    connector_type = "fake"

    def test_connection(self, *, config: dict[str, Any], secrets: dict[str, Any]) -> ConnectorTestResult:
        _ = secrets
        records = config.get("records")
        count = len(records) if isinstance(records, list) else 0
        return ConnectorTestResult(status="ok", message=f"Fake connector ready with {count} records.")

    def introspect(self, *, config: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
        _ = secrets
        records = [item for item in config.get("records", []) if isinstance(item, dict)]
        fields = sorted({key for record in records for key in record})
        return {
            "connector_type": self.connector_type,
            "collections": [
                {
                    "name": "fake.records",
                    "columns": [{"name": field, "type": type(records[0].get(field)).__name__ if records else "unknown"} for field in fields],
                    "sample_count": len(records),
                }
            ],
        }

    def iter_records(
        self,
        *,
        config: dict[str, Any],
        secrets: dict[str, Any],
        selection: dict[str, Any],
        identity_fields: list[str],
        batch_size: int,
    ) -> list[ConnectorRecord]:
        _ = secrets, selection, batch_size
        records = [item for item in config.get("records", []) if isinstance(item, dict)]
        return [_record_from_mapping("fake", record, identity_fields) for record in records]

    def execute_query(
        self,
        *,
        config: dict[str, Any],
        secrets: dict[str, Any],
        query: str,
        row_limit: int,
        timeout_seconds: int,
    ) -> ConnectorQueryResult:
        _ = secrets, timeout_seconds
        rows = [item for item in config.get("live_query_rows", config.get("records", [])) if isinstance(item, dict)]
        bounded = [_json_safe(row) for row in rows[: max(1, row_limit)]]
        columns = sorted({key for row in bounded for key in row})
        return ConnectorQueryResult(query=query, columns=columns, rows=bounded)


class SqlServerConnector:
    connector_type = "sql_server"

    def test_connection(self, *, config: dict[str, Any], secrets: dict[str, Any]) -> ConnectorTestResult:
        with self._connect(config, secrets) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return ConnectorTestResult(status="ok", message="SQL Server connection succeeded.")

    def introspect(self, *, config: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
        sample_limit = _sample_limit(config)
        with self._connect(config, secrets) as conn:
            cursor = conn.cursor()
            tables = _tables_from_column_rows(self.connector_type, _fetch_pyodbc_dicts(cursor, _SQL_SERVER_COLUMNS_SQL))
            _add_primary_key_rows(tables, _fetch_pyodbc_dicts(cursor, _SQL_SERVER_PRIMARY_KEYS_SQL))
            _add_foreign_key_rows(tables, _fetch_pyodbc_dicts(cursor, _SQL_SERVER_FOREIGN_KEYS_SQL))
            _add_index_rows(tables, _fetch_pyodbc_dicts(cursor, _SQL_SERVER_INDEXES_SQL))
            _add_sample_estimate_rows(tables, _fetch_pyodbc_dicts(cursor, _SQL_SERVER_ROW_ESTIMATES_SQL))
            _attach_sql_server_sample_counts(cursor, tables, sample_limit)
        return {"connector_type": self.connector_type, "tables": _finalize_tables(tables)}

    def iter_records(
        self,
        *,
        config: dict[str, Any],
        secrets: dict[str, Any],
        selection: dict[str, Any],
        identity_fields: list[str],
        batch_size: int,
    ) -> list[ConnectorRecord]:
        query = validate_read_only_sql(str(selection.get("query") or ""), connector_type=self.connector_type)
        timeout_seconds = int(selection.get("timeout_seconds") or config.get("timeout_seconds") or 30)
        row_limit = int(selection.get("row_limit") or config.get("row_limit") or 5000)
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
            records: list[ConnectorRecord] = []
            while len(records) < row_limit:
                rows = cursor.fetchmany(max(1, min(batch_size, row_limit - len(records))))
                if not rows:
                    break
                for row in rows:
                    records.append(_record_from_mapping(self.connector_type, _row_dict(cursor, row), identity_fields))
            try:
                conn.rollback()
            except Exception:
                pass
        return records

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
                columns=_column_names(cursor),
                rows=[_row_dict(cursor, row) for row in rows],
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
            raise RuntimeError("pyodbc and the native unixODBC driver manager are required for SQL Server connectors.") from exc
        connection_string = _sql_server_connection_string(config, secrets)
        return pyodbc.connect(connection_string, timeout=int(config.get("connect_timeout_seconds") or 10), readonly=True)


class PostgresConnector:
    connector_type = "postgres"

    def test_connection(self, *, config: dict[str, Any], secrets: dict[str, Any]) -> ConnectorTestResult:
        with self._connect(config, secrets) as conn:
            _prepare_postgres_session(conn, config)
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            conn.rollback()
        return ConnectorTestResult(status="ok", message="PostgreSQL connection succeeded.")

    def introspect(self, *, config: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
        sample_limit = _sample_limit(config)
        with self._connect(config, secrets) as conn:
            _prepare_postgres_session(conn, config)
            tables = _tables_from_column_rows(self.connector_type, _fetch_postgres_dicts(conn, _POSTGRES_COLUMNS_SQL))
            _add_primary_key_rows(tables, _fetch_postgres_dicts(conn, _POSTGRES_PRIMARY_KEYS_SQL))
            _add_foreign_key_rows(tables, _fetch_postgres_dicts(conn, _POSTGRES_FOREIGN_KEYS_SQL))
            _add_index_rows(tables, _fetch_postgres_dicts(conn, _POSTGRES_INDEXES_SQL))
            _add_sample_estimate_rows(tables, _fetch_postgres_dicts(conn, _POSTGRES_ROW_ESTIMATES_SQL))
            _attach_postgres_sample_counts(conn, tables, sample_limit)
            conn.rollback()
        return {"connector_type": self.connector_type, "tables": _finalize_tables(tables)}

    def iter_records(
        self,
        *,
        config: dict[str, Any],
        secrets: dict[str, Any],
        selection: dict[str, Any],
        identity_fields: list[str],
        batch_size: int,
    ) -> list[ConnectorRecord]:
        query = validate_read_only_sql(str(selection.get("query") or ""), connector_type=self.connector_type)
        row_limit = int(selection.get("row_limit") or config.get("row_limit") or 5000)
        with self._connect(config, secrets) as conn:
            _prepare_postgres_session(conn, {**config, "timeout_seconds": selection.get("timeout_seconds") or config.get("timeout_seconds")})
            records: list[ConnectorRecord] = []
            with conn.cursor() as cursor:
                cursor.execute(query)
                while len(records) < row_limit:
                    rows = cursor.fetchmany(max(1, min(batch_size, row_limit - len(records))))
                    if not rows:
                        break
                    for row in rows:
                        records.append(_record_from_mapping(self.connector_type, dict(row), identity_fields))
            conn.rollback()
        return records

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
            _prepare_postgres_session(conn, {**config, "timeout_seconds": timeout_seconds})
            with conn.cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchmany(max(1, row_limit))
                result = ConnectorQueryResult(
                    query=query,
                    columns=_column_names(cursor),
                    rows=[_json_safe(dict(row)) for row in rows],
                )
            conn.rollback()
        return result

    def _connect(self, config: dict[str, Any], secrets: dict[str, Any]):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg is required for PostgreSQL connectors.") from exc
        return psycopg.connect(**_postgres_connection_kwargs(config, secrets), row_factory=dict_row)


class UnsupportedConnector:
    def __init__(self, connector_type: str) -> None:
        self.connector_type = connector_type

    def test_connection(self, *, config: dict[str, Any], secrets: dict[str, Any]) -> ConnectorTestResult:
        _ = config, secrets
        raise RuntimeError(f"{self.connector_type} connector runtime is not implemented yet.")

    def introspect(self, *, config: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
        _ = config, secrets
        raise RuntimeError(f"{self.connector_type} connector introspection is not implemented yet.")

    def iter_records(self, **kwargs: Any) -> list[ConnectorRecord]:
        _ = kwargs
        raise RuntimeError(f"{self.connector_type} connector sync is not implemented yet.")

    def execute_query(self, **kwargs: Any) -> ConnectorQueryResult:
        _ = kwargs
        raise RuntimeError(f"{self.connector_type} connector live query is not implemented yet.")


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {
            "fake": FakeConnector(),
            "postgres": PostgresConnector(),
            "sql_server": SqlServerConnector(),
        }

    def get(self, connector_type: str) -> Connector:
        return self._connectors.get(connector_type, UnsupportedConnector(connector_type))


def default_connector_registry() -> ConnectorRegistry:
    return ConnectorRegistry()


def _record_from_mapping(connector_type: str, row: dict[str, Any], identity_fields: list[str]) -> ConnectorRecord:
    identity = {field: row.get(field) for field in identity_fields}
    if any(value is None or str(value) == "" for value in identity.values()):
        missing = [field for field, value in identity.items() if value is None or str(value) == ""]
        raise ValueError(f"Connector record is missing identity field: {missing[0]}")
    identity_text = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(identity_text.encode("utf-8")).hexdigest()[:24]
    title = f"{connector_type} record {', '.join(str(value) for value in identity.values())}"
    return ConnectorRecord(
        source_path=f"{connector_type}/{digest}.json",
        title=title,
        data=_json_safe(row),
        identity=_json_safe(identity),
        updated_at=str(row.get("updated_at") or row.get("modified_at") or "") or None,
    )


def _fetch_pyodbc_dicts(cursor, query: str) -> list[dict[str, Any]]:
    cursor.execute(query)
    return [_row_dict(cursor, row) for row in cursor.fetchall()]


def _fetch_postgres_dicts(conn, query: str) -> list[dict[str, Any]]:
    with conn.cursor() as cursor:
        cursor.execute(query)
        return [dict(row) for row in cursor.fetchall()]


def _row_dict(cursor, row) -> dict[str, Any]:
    names = [column[0] for column in cursor.description]
    return {name: _json_safe_value(value) for name, value in zip(names, row)}


def _column_names(cursor) -> list[str]:
    names: list[str] = []
    for column in cursor.description or []:
        name = getattr(column, "name", None)
        if name is None:
            try:
                name = column[0]
            except Exception:
                name = None
        if name is not None:
            names.append(str(name))
    return names


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe_value(item) for key, item in value.items()}


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _sql_server_connection_string(config: dict[str, Any], secrets: dict[str, Any]) -> str:
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
        "TrustServerCertificate=yes" if config.get("trust_server_certificate", True) else "TrustServerCertificate=no",
    ]
    if trusted:
        parts.append("Trusted_Connection=yes")
    else:
        parts.extend([f"UID={username}", f"PWD={password}"])
    return ";".join(parts)


def _postgres_connection_kwargs(config: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
    timeout = int(config.get("connect_timeout_seconds") or 10)
    if config.get("connection_string") or config.get("dsn"):
        return {"conninfo": str(config.get("connection_string") or config.get("dsn")), "connect_timeout": timeout}
    kwargs: dict[str, Any] = {
        "host": str(config.get("host") or config.get("server") or "localhost"),
        "port": int(config.get("port") or 5432),
        "dbname": str(config.get("database") or config.get("dbname") or ""),
        "user": str(secrets.get("username") or config.get("username") or config.get("user") or ""),
        "password": str(secrets.get("password") or ""),
        "connect_timeout": timeout,
    }
    sslmode = str(config.get("sslmode") or config.get("ssl_mode") or "prefer")
    if sslmode:
        kwargs["sslmode"] = sslmode
    return kwargs


def _prepare_postgres_session(conn, config: dict[str, Any]) -> None:
    timeout_seconds = int(config.get("timeout_seconds") or 30)
    timeout_ms = max(1, min(timeout_seconds, 300)) * 1000
    try:
        conn.read_only = True
    except Exception:
        pass
    with conn.cursor() as cursor:
        cursor.execute("SELECT set_config('statement_timeout', %s, false)", (str(timeout_ms),))


def _tables_from_column_rows(connector_type: str, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    tables: dict[str, dict[str, Any]] = {}
    for row in rows:
        table = _ensure_table(tables, row)
        column = {
            "name": row["column_name"],
            "type": row["data_type"],
            "nullable": str(row.get("is_nullable") or "").upper() == "YES" or row.get("is_nullable") is True,
            "ordinal": row["ordinal_position"],
        }
        if row.get("character_maximum_length") is not None:
            column["max_length"] = row["character_maximum_length"]
        if row.get("numeric_precision") is not None:
            column["numeric_precision"] = row["numeric_precision"]
        if row.get("numeric_scale") is not None:
            column["numeric_scale"] = row["numeric_scale"]
        table["columns"].append(column)
    for table in tables.values():
        table["connector_type"] = connector_type
    return tables


def _ensure_table(tables: dict[str, dict[str, Any]], row: dict[str, Any]) -> dict[str, Any]:
    schema = str(row["table_schema"])
    name = str(row["table_name"])
    key = _table_key(schema, name)
    raw_kind = str(row.get("table_type") or row.get("kind") or "")
    kind = "view" if "VIEW" in raw_kind.upper() else "table"
    return tables.setdefault(
        key,
        {
            "schema": schema,
            "name": name,
            "kind": kind,
            "columns": [],
            "primary_keys": [],
            "foreign_keys": [],
            "indexes": [],
            "sample_metadata": {},
        },
    )


def _add_primary_key_rows(tables: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    for row in rows:
        table = tables.get(_table_key(row["table_schema"], row["table_name"]))
        if table is None:
            continue
        mapping = table.setdefault("_primary_key_map", {})
        name = str(row.get("constraint_name") or row.get("primary_key_name") or "primary")
        entry = mapping.setdefault(name, {"name": name, "columns": []})
        column = str(row["column_name"])
        if column not in entry["columns"]:
            entry["columns"].append(column)


def _add_foreign_key_rows(tables: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    for row in rows:
        table = tables.get(_table_key(row["table_schema"], row["table_name"]))
        if table is None:
            continue
        mapping = table.setdefault("_foreign_key_map", {})
        name = str(row.get("constraint_name") or row.get("foreign_key_name") or "foreign_key")
        entry = mapping.setdefault(
            name,
            {
                "name": name,
                "columns": [],
                "referenced_table": _table_key(row["referenced_table_schema"], row["referenced_table_name"]),
                "referenced_columns": [],
            },
        )
        column = str(row["column_name"])
        referenced_column = str(row["referenced_column_name"])
        if column not in entry["columns"]:
            entry["columns"].append(column)
        if referenced_column not in entry["referenced_columns"]:
            entry["referenced_columns"].append(referenced_column)


def _add_index_rows(tables: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    for row in rows:
        table = tables.get(_table_key(row["table_schema"], row["table_name"]))
        if table is None:
            continue
        mapping = table.setdefault("_index_map", {})
        name = str(row.get("index_name") or "index")
        entry = mapping.setdefault(
            name,
            {
                "name": name,
                "columns": [],
                "unique": bool(row.get("is_unique")),
                "type": row.get("index_type") or row.get("type_desc"),
            },
        )
        if row.get("index_definition"):
            entry["definition"] = row["index_definition"]
        column = row.get("column_name")
        if column and str(column) not in entry["columns"]:
            entry["columns"].append(str(column))


def _add_sample_estimate_rows(tables: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    for row in rows:
        table = tables.get(_table_key(row["table_schema"], row["table_name"]))
        if table is None:
            continue
        metadata = table.setdefault("sample_metadata", {})
        try:
            metadata["estimated_row_count"] = int(row.get("estimated_row_count") or 0)
        except (TypeError, ValueError):
            metadata["estimated_row_count"] = row.get("estimated_row_count")


def _attach_sql_server_sample_counts(cursor, tables: dict[str, dict[str, Any]], sample_limit: int) -> None:
    for table in tables.values():
        if sample_limit <= 0:
            table.setdefault("sample_metadata", {})["sample_row_count"] = 0
            continue
        query = (
            "SELECT COUNT_BIG(*) AS sample_row_count FROM "
            f"(SELECT TOP ({sample_limit}) 1 AS marker FROM {_quote_sql_server_ident(table['schema'])}.{_quote_sql_server_ident(table['name'])}) AS sample_rows"
        )
        try:
            cursor.execute(query)
            row = cursor.fetchone()
            table.setdefault("sample_metadata", {})["sample_row_count"] = int(row[0]) if row else 0
        except Exception as exc:
            table.setdefault("sample_metadata", {})["sample_error"] = str(exc)[:200]


def _attach_postgres_sample_counts(conn, tables: dict[str, dict[str, Any]], sample_limit: int) -> None:
    for table in tables.values():
        if sample_limit <= 0:
            table.setdefault("sample_metadata", {})["sample_row_count"] = 0
            continue
        query = (
            "SELECT COUNT(*) AS sample_row_count FROM "
            f"(SELECT 1 FROM {_quote_postgres_ident(table['schema'])}.{_quote_postgres_ident(table['name'])} LIMIT {sample_limit}) sample_rows"
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(query)
                row = cursor.fetchone()
                table.setdefault("sample_metadata", {})["sample_row_count"] = int(row["sample_row_count"]) if row else 0
        except Exception as exc:
            table.setdefault("sample_metadata", {})["sample_error"] = str(exc)[:200]


def _finalize_tables(tables: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    finalized: list[dict[str, Any]] = []
    for table in sorted(tables.values(), key=lambda item: (item["schema"], item["name"])):
        table["primary_keys"] = list(table.pop("_primary_key_map", {}).values())
        table["foreign_keys"] = list(table.pop("_foreign_key_map", {}).values())
        table["indexes"] = list(table.pop("_index_map", {}).values())
        finalized.append(table)
    return finalized


def _sample_limit(config: dict[str, Any]) -> int:
    return max(0, min(int(config.get("sample_limit") or 3), 25))


def _table_key(schema: Any, name: Any) -> str:
    return f"{schema}.{name}"


def _quote_sql_server_ident(value: str) -> str:
    return f"[{value.replace(']', ']]')}]"


def _quote_postgres_ident(value: str) -> str:
    return f"\"{value.replace(chr(34), chr(34) + chr(34))}\""


_SQL_SERVER_COLUMNS_SQL = """
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

_SQL_SERVER_PRIMARY_KEYS_SQL = """
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

_SQL_SERVER_FOREIGN_KEYS_SQL = """
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

_SQL_SERVER_INDEXES_SQL = """
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

_SQL_SERVER_ROW_ESTIMATES_SQL = """
SELECT
    sch.name AS table_schema,
    tab.name AS table_name,
    SUM(part.rows) AS estimated_row_count
FROM sys.tables tab
JOIN sys.schemas sch ON sch.schema_id = tab.schema_id
JOIN sys.partitions part ON part.object_id = tab.object_id AND part.index_id IN (0, 1)
GROUP BY sch.name, tab.name
"""

_POSTGRES_COLUMNS_SQL = """
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

_POSTGRES_PRIMARY_KEYS_SQL = """
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

_POSTGRES_FOREIGN_KEYS_SQL = """
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

_POSTGRES_INDEXES_SQL = """
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

_POSTGRES_ROW_ESTIMATES_SQL = """
SELECT
    n.nspname AS table_schema,
    c.relname AS table_name,
    GREATEST(c.reltuples::bigint, 0) AS estimated_row_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
"""
