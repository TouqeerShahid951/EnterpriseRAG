from __future__ import annotations

import pytest

from rag.connectors.crypto import (
    decrypt_secret,
    encrypt_secret,
    keyring_from_settings,
    redact_secrets,
)
from rag.connectors.sql_safety import (
    SqlValidationError,
    validate_live_sql_for_approved_catalog,
    validate_read_only_sql,
)


def test_secret_envelope_round_trips_and_redacts() -> None:
    keys = keyring_from_settings("unit-test-key")
    encrypted = encrypt_secret(
        {"username": "readonly", "password": "secret"},
        keys,
    )

    assert "secret" not in encrypted
    assert decrypt_secret(encrypted, keys) == {
        "username": "readonly",
        "password": "secret",
    }
    assert redact_secrets({"username": "readonly", "password": "secret"}) == {
        "username": "********",
        "password": "********",
    }


def test_sql_server_validation_blocks_unsafe_statements() -> None:
    assert (
        validate_read_only_sql(
            "WITH rows AS (SELECT id FROM dbo.Cases) SELECT * FROM rows;"
        )
        == "WITH rows AS (SELECT id FROM dbo.Cases) SELECT * FROM rows"
    )

    for query in [
        "UPDATE dbo.Cases SET status = 'x'",
        "SELECT * INTO dbo.Copy FROM dbo.Cases",
        "SELECT * FROM dbo.Cases; DROP TABLE dbo.Cases",
        "EXEC xp_cmdshell 'dir'",
        "SELECT * FROM OPENROWSET('SQLNCLI', 'x', 'SELECT 1')",
        "SELECT * FROM dbo.Cases -- hidden",
    ]:
        with pytest.raises(SqlValidationError):
            validate_read_only_sql(query, connector_type="sql_server")


def test_postgres_validation_blocks_unsafe_statements() -> None:
    assert (
        validate_read_only_sql(
            "SELECT id, status FROM public.cases",
            connector_type="postgres",
        )
        == "SELECT id, status FROM public.cases"
    )

    for query in [
        "CALL refresh_case_cache()",
        "COPY public.cases TO PROGRAM 'cat'",
        "SELECT * INTO public.case_copy FROM public.cases",
        "SELECT * FROM public.cases FOR UPDATE",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity",
    ]:
        with pytest.raises(SqlValidationError):
            validate_read_only_sql(query, connector_type="postgres")


def test_live_sql_validation_allows_only_approved_catalog_scope() -> None:
    catalog = {
        "tables": [
            {
                "key": "public.cases",
                "schema": "public",
                "name": "cases",
                "allowed": True,
                "sensitive": False,
                "columns": [
                    {"name": "id", "allowed": True, "sensitive": False},
                    {"name": "status", "allowed": True, "sensitive": False},
                    {"name": "person_id", "allowed": True, "sensitive": False},
                    {
                        "name": "secret_note",
                        "allowed": False,
                        "sensitive": True,
                    },
                ],
            },
            {
                "key": "public.people",
                "schema": "public",
                "name": "people",
                "allowed": True,
                "sensitive": False,
                "columns": [
                    {"name": "id", "allowed": True, "sensitive": False},
                    {"name": "name", "allowed": True, "sensitive": False},
                ],
            },
        ],
        "relationships": [
            {
                "left_table": "public.cases",
                "left_columns": ["person_id"],
                "right_table": "public.people",
                "right_columns": ["id"],
                "allowed": True,
            }
        ],
    }

    validated = validate_live_sql_for_approved_catalog(
        "SELECT c.status, COUNT(*) AS total FROM public.cases c GROUP BY c.status",
        catalog_json=catalog,
        connector_type="postgres",
        row_limit=10,
    )
    assert "LIMIT 10" in validated

    joined = validate_live_sql_for_approved_catalog(
        "SELECT c.status, p.name FROM public.cases c "
        "JOIN public.people p ON p.id = c.person_id LIMIT 5",
        catalog_json=catalog,
        connector_type="postgres",
        row_limit=10,
    )
    assert joined.endswith("LIMIT 5")

    for query in [
        "SELECT * FROM public.cases",
        "SELECT secret_note FROM public.cases",
        "SELECT status FROM public.incidents",
        "SELECT c.status, p.name FROM public.cases c "
        "JOIN public.people p ON p.name = c.status",
        "SELECT c.status, p.name FROM public.cases c, public.people p",
        "WITH leaked AS (SELECT status FROM public.cases) SELECT * FROM leaked",
        "SELECT status FROM public.cases; SELECT name FROM public.people",
        "DELETE FROM public.cases",
    ]:
        with pytest.raises(SqlValidationError):
            validate_live_sql_for_approved_catalog(
                query,
                catalog_json=catalog,
                connector_type="postgres",
                row_limit=10,
            )

    with pytest.raises(SqlValidationError) as excinfo:
        validate_live_sql_for_approved_catalog(
            "SELECT c.missing_id FROM public.cases c LIMIT 5",
            catalog_json=catalog,
            connector_type="postgres",
            row_limit=10,
        )
    message = str(excinfo.value)
    assert "c.missing_id" in message
    assert "public.cases" in message
    assert "status" in message
