from __future__ import annotations

import rag.connectors.registry as connector_registry
from rag.connectors.adapters.fake import FakeConnector as FakeConnectorAdapter
from rag.connectors.adapters.postgres import PostgresConnector as PostgresConnectorAdapter
from rag.connectors.adapters.sql_server import (
    SqlServerConnector as SqlServerConnectorAdapter,
)
from rag.connectors.registry import (
    PostgresConnector,
    SqlServerConnector,
    _add_foreign_key_rows,
    _add_index_rows,
    _add_primary_key_rows,
    _add_sample_estimate_rows,
    _finalize_tables,
    _postgres_connection_kwargs,
    _quote_postgres_ident,
    _tables_from_column_rows,
    default_connector_registry,
)


def test_connector_registry_exposes_sql_server_and_postgres() -> None:
    registry = default_connector_registry()

    assert isinstance(registry.get("sql_server"), SqlServerConnector)
    assert isinstance(registry.get("postgres"), PostgresConnector)
    try:
        registry.get("mysql")
    except ValueError as exc:
        assert str(exc) == "Unsupported connector type: mysql"
    else:
        raise AssertionError("unsupported connector type was accepted")


def test_connector_registry_preserves_adapter_compatibility_imports() -> None:
    assert connector_registry.FakeConnector is FakeConnectorAdapter
    assert connector_registry.PostgresConnector is PostgresConnectorAdapter
    assert connector_registry.SqlServerConnector is SqlServerConnectorAdapter


def test_postgres_connection_kwargs_use_public_config_and_encrypted_secrets() -> None:
    kwargs = _postgres_connection_kwargs(
        {
            "host": "postgres.internal",
            "port": "5433",
            "database": "cases",
            "sslmode": "require",
            "connect_timeout_seconds": 7,
        },
        {"username": "readonly", "password": "secret"},
    )

    assert kwargs == {
        "host": "postgres.internal",
        "port": 5433,
        "dbname": "cases",
        "user": "readonly",
        "password": "secret",
        "connect_timeout": 7,
        "sslmode": "require",
    }


def test_connector_introspection_helpers_shape_relational_metadata() -> None:
    tables = _tables_from_column_rows(
        "postgres",
        [
            {
                "table_schema": "public",
                "table_name": "cases",
                "table_type": "BASE TABLE",
                "column_name": "id",
                "ordinal_position": 1,
                "data_type": "uuid",
                "is_nullable": "NO",
                "character_maximum_length": None,
                "numeric_precision": None,
                "numeric_scale": None,
            },
            {
                "table_schema": "public",
                "table_name": "cases",
                "table_type": "BASE TABLE",
                "column_name": "person_id",
                "ordinal_position": 2,
                "data_type": "uuid",
                "is_nullable": "NO",
                "character_maximum_length": None,
                "numeric_precision": None,
                "numeric_scale": None,
            },
            {
                "table_schema": "public",
                "table_name": "people",
                "table_type": "BASE TABLE",
                "column_name": "id",
                "ordinal_position": 1,
                "data_type": "uuid",
                "is_nullable": "NO",
                "character_maximum_length": None,
                "numeric_precision": None,
                "numeric_scale": None,
            },
        ],
    )
    _add_primary_key_rows(
        tables,
        [
            {
                "table_schema": "public",
                "table_name": "cases",
                "constraint_name": "cases_pkey",
                "column_name": "id",
            }
        ],
    )
    _add_foreign_key_rows(
        tables,
        [
            {
                "table_schema": "public",
                "table_name": "cases",
                "constraint_name": "cases_person_id_fkey",
                "column_name": "person_id",
                "referenced_table_schema": "public",
                "referenced_table_name": "people",
                "referenced_column_name": "id",
            }
        ],
    )
    _add_index_rows(
        tables,
        [
            {
                "table_schema": "public",
                "table_name": "cases",
                "index_name": "cases_person_idx",
                "is_unique": False,
                "index_type": "btree",
                "column_name": "person_id",
            }
        ],
    )
    _add_sample_estimate_rows(
        tables,
        [
            {
                "table_schema": "public",
                "table_name": "cases",
                "estimated_row_count": 25,
            }
        ],
    )

    finalized = _finalize_tables(tables)
    cases = next(table for table in finalized if table["name"] == "cases")

    assert cases["connector_type"] == "postgres"
    assert cases["primary_keys"] == [{"name": "cases_pkey", "columns": ["id"]}]
    assert cases["foreign_keys"] == [
        {
            "name": "cases_person_id_fkey",
            "columns": ["person_id"],
            "referenced_table": "public.people",
            "referenced_columns": ["id"],
        }
    ]
    assert cases["indexes"] == [
        {
            "name": "cases_person_idx",
            "columns": ["person_id"],
            "unique": False,
            "type": "btree",
        }
    ]
    assert cases["sample_metadata"]["estimated_row_count"] == 25
    assert _quote_postgres_ident('case"records') == '"case""records"'
