"""Connector registry composition and compatibility imports."""

from __future__ import annotations

from typing import Any

from . import row_mapping as _row_mapping
from . import schema_introspection as _schema_introspection
from .adapters import postgres as _postgres
from .adapters import sql_server as _sql_server
from .adapters.fake import FakeConnector
from .adapters.postgres import PostgresConnector
from .adapters.sql_server import SqlServerConnector
from .contracts import Connector
from .models import ConnectorQueryResult, ConnectorTestResult
from .sql_safety import validate_read_only_sql

# Preserve imports used by older callers while implementation lives in focused modules.
_POSTGRES_COLUMNS_SQL = _postgres.POSTGRES_COLUMNS_SQL
_POSTGRES_FOREIGN_KEYS_SQL = _postgres.POSTGRES_FOREIGN_KEYS_SQL
_POSTGRES_INDEXES_SQL = _postgres.POSTGRES_INDEXES_SQL
_POSTGRES_PRIMARY_KEYS_SQL = _postgres.POSTGRES_PRIMARY_KEYS_SQL
_POSTGRES_ROW_ESTIMATES_SQL = _postgres.POSTGRES_ROW_ESTIMATES_SQL
_SQL_SERVER_COLUMNS_SQL = _sql_server.SQL_SERVER_COLUMNS_SQL
_SQL_SERVER_FOREIGN_KEYS_SQL = _sql_server.SQL_SERVER_FOREIGN_KEYS_SQL
_SQL_SERVER_INDEXES_SQL = _sql_server.SQL_SERVER_INDEXES_SQL
_SQL_SERVER_PRIMARY_KEYS_SQL = _sql_server.SQL_SERVER_PRIMARY_KEYS_SQL
_SQL_SERVER_ROW_ESTIMATES_SQL = _sql_server.SQL_SERVER_ROW_ESTIMATES_SQL
_add_foreign_key_rows = _schema_introspection.add_foreign_key_rows
_add_index_rows = _schema_introspection.add_index_rows
_add_primary_key_rows = _schema_introspection.add_primary_key_rows
_add_sample_estimate_rows = _schema_introspection.add_sample_estimate_rows
_attach_postgres_sample_counts = _schema_introspection.attach_postgres_sample_counts
_attach_sql_server_sample_counts = _schema_introspection.attach_sql_server_sample_counts
_column_names = _row_mapping.column_names
_ensure_table = _schema_introspection._ensure_table
_fetch_postgres_dicts = _schema_introspection.fetch_postgres_dicts
_fetch_pyodbc_dicts = _schema_introspection.fetch_pyodbc_dicts
_finalize_tables = _schema_introspection.finalize_tables
_json_safe = _row_mapping.json_safe
_json_safe_value = _row_mapping.json_safe_value
_postgres_connection_kwargs = _postgres.postgres_connection_kwargs
_prepare_postgres_session = _postgres.prepare_postgres_session
_quote_postgres_ident = _schema_introspection.quote_postgres_ident
_quote_sql_server_ident = _schema_introspection.quote_sql_server_ident
_row_dict = _row_mapping.row_dict
_sample_limit = _schema_introspection.sample_limit
_sql_server_connection_string = _sql_server.sql_server_connection_string
_table_key = _schema_introspection.table_key
_tables_from_column_rows = _schema_introspection.tables_from_column_rows


class UnsupportedConnector:
    def __init__(self, connector_type: str) -> None:
        self.connector_type = connector_type

    def test_connection(
        self, *, config: dict[str, Any], secrets: dict[str, Any]
    ) -> ConnectorTestResult:
        _ = config, secrets
        raise RuntimeError(
            f"{self.connector_type} connector runtime is not implemented yet."
        )

    def introspect(
        self, *, config: dict[str, Any], secrets: dict[str, Any]
    ) -> dict[str, Any]:
        _ = config, secrets
        raise RuntimeError(
            f"{self.connector_type} connector introspection is not implemented yet."
        )

    def execute_query(self, **kwargs: Any) -> ConnectorQueryResult:
        _ = kwargs
        raise RuntimeError(
            f"{self.connector_type} connector live query is not implemented yet."
        )


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {
            "fake": FakeConnector(),
            "postgres": PostgresConnector(),
            "sql_server": SqlServerConnector(),
        }

    def get(self, connector_type: str) -> Connector:
        return self._connectors.get(
            connector_type, UnsupportedConnector(connector_type)
        )


def default_connector_registry() -> ConnectorRegistry:
    return ConnectorRegistry()


__all__ = [
    "Connector",
    "ConnectorQueryResult",
    "ConnectorRegistry",
    "ConnectorTestResult",
    "FakeConnector",
    "PostgresConnector",
    "SqlServerConnector",
    "UnsupportedConnector",
    "default_connector_registry",
    "validate_read_only_sql",
]
