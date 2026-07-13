"""Normalize relational database catalogs into the connector schema contract."""

from __future__ import annotations

from typing import Any

from .row_mapping import row_dict


def fetch_pyodbc_dicts(cursor, query: str) -> list[dict[str, Any]]:
    cursor.execute(query)
    return [row_dict(cursor, row) for row in cursor.fetchall()]


def fetch_postgres_dicts(conn, query: str) -> list[dict[str, Any]]:
    with conn.cursor() as cursor:
        cursor.execute(query)
        return [dict(row) for row in cursor.fetchall()]


def tables_from_column_rows(
    connector_type: str, rows: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    tables: dict[str, dict[str, Any]] = {}
    for row in rows:
        table = _ensure_table(tables, row)
        column = {
            "name": row["column_name"],
            "type": row["data_type"],
            "nullable": str(row.get("is_nullable") or "").upper() == "YES"
            or row.get("is_nullable") is True,
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


def _ensure_table(
    tables: dict[str, dict[str, Any]], row: dict[str, Any]
) -> dict[str, Any]:
    schema = str(row["table_schema"])
    name = str(row["table_name"])
    key = table_key(schema, name)
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


def add_primary_key_rows(
    tables: dict[str, dict[str, Any]], rows: list[dict[str, Any]]
) -> None:
    for row in rows:
        table = tables.get(table_key(row["table_schema"], row["table_name"]))
        if table is None:
            continue
        mapping = table.setdefault("_primary_key_map", {})
        name = str(
            row.get("constraint_name") or row.get("primary_key_name") or "primary"
        )
        entry = mapping.setdefault(name, {"name": name, "columns": []})
        column = str(row["column_name"])
        if column not in entry["columns"]:
            entry["columns"].append(column)


def add_foreign_key_rows(
    tables: dict[str, dict[str, Any]], rows: list[dict[str, Any]]
) -> None:
    for row in rows:
        table = tables.get(table_key(row["table_schema"], row["table_name"]))
        if table is None:
            continue
        mapping = table.setdefault("_foreign_key_map", {})
        name = str(
            row.get("constraint_name") or row.get("foreign_key_name") or "foreign_key"
        )
        entry = mapping.setdefault(
            name,
            {
                "name": name,
                "columns": [],
                "referenced_table": table_key(
                    row["referenced_table_schema"], row["referenced_table_name"]
                ),
                "referenced_columns": [],
            },
        )
        column = str(row["column_name"])
        referenced_column = str(row["referenced_column_name"])
        if column not in entry["columns"]:
            entry["columns"].append(column)
        if referenced_column not in entry["referenced_columns"]:
            entry["referenced_columns"].append(referenced_column)


def add_index_rows(
    tables: dict[str, dict[str, Any]], rows: list[dict[str, Any]]
) -> None:
    for row in rows:
        table = tables.get(table_key(row["table_schema"], row["table_name"]))
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


def add_sample_estimate_rows(
    tables: dict[str, dict[str, Any]], rows: list[dict[str, Any]]
) -> None:
    for row in rows:
        table = tables.get(table_key(row["table_schema"], row["table_name"]))
        if table is None:
            continue
        metadata = table.setdefault("sample_metadata", {})
        try:
            metadata["estimated_row_count"] = int(row.get("estimated_row_count") or 0)
        except (TypeError, ValueError):
            metadata["estimated_row_count"] = row.get("estimated_row_count")


def attach_sql_server_sample_counts(
    cursor, tables: dict[str, dict[str, Any]], sample_limit: int
) -> None:
    for table in tables.values():
        if sample_limit <= 0:
            table.setdefault("sample_metadata", {})["sample_row_count"] = 0
            continue
        query = (
            "SELECT COUNT_BIG(*) AS sample_row_count FROM "
            f"(SELECT TOP ({sample_limit}) 1 AS marker FROM {quote_sql_server_ident(table['schema'])}.{quote_sql_server_ident(table['name'])}) AS sample_rows"
        )
        try:
            cursor.execute(query)
            row = cursor.fetchone()
            table.setdefault("sample_metadata", {})["sample_row_count"] = (
                int(row[0]) if row else 0
            )
        except Exception as exc:
            table.setdefault("sample_metadata", {})["sample_error"] = str(exc)[:200]


def attach_postgres_sample_counts(
    conn, tables: dict[str, dict[str, Any]], sample_limit: int
) -> None:
    for table in tables.values():
        if sample_limit <= 0:
            table.setdefault("sample_metadata", {})["sample_row_count"] = 0
            continue
        query = (
            "SELECT COUNT(*) AS sample_row_count FROM "
            f"(SELECT 1 FROM {quote_postgres_ident(table['schema'])}.{quote_postgres_ident(table['name'])} LIMIT {sample_limit}) sample_rows"
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(query)
                row = cursor.fetchone()
                table.setdefault("sample_metadata", {})["sample_row_count"] = (
                    int(row["sample_row_count"]) if row else 0
                )
        except Exception as exc:
            table.setdefault("sample_metadata", {})["sample_error"] = str(exc)[:200]


def finalize_tables(tables: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    finalized: list[dict[str, Any]] = []
    for table in sorted(
        tables.values(), key=lambda item: (item["schema"], item["name"])
    ):
        table["primary_keys"] = list(table.pop("_primary_key_map", {}).values())
        table["foreign_keys"] = list(table.pop("_foreign_key_map", {}).values())
        table["indexes"] = list(table.pop("_index_map", {}).values())
        finalized.append(table)
    return finalized


def sample_limit(config: dict[str, Any]) -> int:
    return max(0, min(int(config.get("sample_limit") or 3), 25))


def table_key(schema: Any, name: Any) -> str:
    return f"{schema}.{name}"


def quote_sql_server_ident(value: str) -> str:
    return f"[{value.replace(']', ']]')}]"


def quote_postgres_ident(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) + chr(34))}"'
