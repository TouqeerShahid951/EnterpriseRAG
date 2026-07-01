"""Approved connector schema catalog helpers."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from rag.shared.contracts.group_paths import normalize_group_path

_TERM_RE = re.compile(r"[A-Za-z0-9_]{3,}")


def build_default_schema_catalog(schema_json: dict[str, Any]) -> dict[str, Any]:
    """Build an admin-review draft from connector introspection metadata."""

    tables: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    for raw_table in _raw_tables(schema_json):
        schema = str(raw_table.get("schema") or "")
        name = str(raw_table.get("name") or "")
        if not name:
            continue
        key = table_key(schema, name)
        columns = []
        for raw_column in raw_table.get("columns") or []:
            if not isinstance(raw_column, dict) or not raw_column.get("name"):
                continue
            columns.append(
                {
                    "name": str(raw_column["name"]),
                    "data_type": str(raw_column.get("type") or raw_column.get("data_type") or "unknown"),
                    "nullable": bool(raw_column.get("nullable")),
                    "ordinal": raw_column.get("ordinal"),
                    "allowed": True,
                    "sensitive": False,
                    "description": "",
                    "synonyms": [],
                }
            )
        sample_metadata = raw_table.get("sample_metadata") if isinstance(raw_table.get("sample_metadata"), dict) else {}
        table_entry = {
            "key": key,
            "schema": schema,
            "name": name,
            "kind": str(raw_table.get("kind") or "table"),
            "allowed": True,
            "sensitive": False,
            "description": "",
            "synonyms": [],
            "columns": columns,
            "primary_keys": raw_table.get("primary_keys") if isinstance(raw_table.get("primary_keys"), list) else [],
            "indexes": raw_table.get("indexes") if isinstance(raw_table.get("indexes"), list) else [],
            "estimated_row_count": sample_metadata.get("estimated_row_count"),
        }
        tables.append(table_entry)
        for raw_fk in raw_table.get("foreign_keys") or []:
            if not isinstance(raw_fk, dict):
                continue
            referenced = str(raw_fk.get("referenced_table") or "")
            if not referenced:
                continue
            relationships.append(
                {
                    "name": str(raw_fk.get("name") or ""),
                    "left_table": key,
                    "left_columns": [str(item) for item in raw_fk.get("columns") or []],
                    "right_table": normalize_table_key(referenced),
                    "right_columns": [str(item) for item in raw_fk.get("referenced_columns") or []],
                    "allowed": True,
                    "description": "",
                }
            )
    return {
        "version": 1,
        "source": "connector_introspection",
        "sample_values_included": False,
        "tables": tables,
        "relationships": relationships,
        "business_rules": [],
    }


def approved_schema_prompt(catalog_json: dict[str, Any], *, question: str, max_tables: int = 8) -> str:
    """Render compact approved schema context for SQL generation."""

    selected_tables = ranked_approved_tables(catalog_json, question=question, limit=max_tables)
    selected_keys = {str(table.get("key") or table_key(table.get("schema"), table.get("name"))) for table in selected_tables}
    lines = ["Approved database schema:"]
    for table in selected_tables:
        key = str(table.get("key") or table_key(table.get("schema"), table.get("name")))
        desc = str(table.get("description") or "").strip()
        row_count = table.get("estimated_row_count")
        table_line = f"- {key}"
        if desc:
            table_line += f": {desc}"
        if row_count is not None:
            table_line += f" (estimated rows: {row_count})"
        lines.append(table_line)
        columns = []
        for column in table.get("columns") or []:
            if not isinstance(column, dict) or not column_allowed(column):
                continue
            col_desc = str(column.get("description") or "").strip()
            col_type = str(column.get("data_type") or column.get("type") or "unknown")
            item = f"{column.get('name')} {col_type}"
            if col_desc:
                item += f" - {col_desc}"
            columns.append(item)
        if columns:
            lines.append(f"  columns: {', '.join(columns)}")
    relationship_lines = []
    for relationship in catalog_json.get("relationships") or []:
        if not isinstance(relationship, dict) or relationship.get("allowed") is False:
            continue
        left = normalize_table_key(relationship.get("left_table"))
        right = normalize_table_key(relationship.get("right_table"))
        if left not in selected_keys or right not in selected_keys:
            continue
        left_cols = ", ".join(str(item) for item in relationship.get("left_columns") or [])
        right_cols = ", ".join(str(item) for item in relationship.get("right_columns") or [])
        relationship_lines.append(f"- {left}({left_cols}) = {right}({right_cols})")
    if relationship_lines:
        lines.append("Approved joins:")
        lines.extend(relationship_lines)
    rules = [str(item).strip() for item in catalog_json.get("business_rules") or [] if str(item).strip()]
    if rules:
        lines.append("Business rules:")
        lines.extend(f"- {item}" for item in rules[:10])
    return "\n".join(lines)


def ranked_approved_tables(catalog_json: dict[str, Any], *, question: str, limit: int) -> list[dict[str, Any]]:
    tables = [table for table in catalog_json.get("tables") or [] if isinstance(table, dict) and table_allowed(table)]
    terms = set(term.lower() for term in _TERM_RE.findall(question))
    if not terms:
        return tables[:limit]

    def score(table: dict[str, Any]) -> tuple[int, str]:
        haystack: list[str] = [
            str(table.get("key") or ""),
            str(table.get("schema") or ""),
            str(table.get("name") or ""),
            str(table.get("description") or ""),
        ]
        haystack.extend(str(item) for item in table.get("synonyms") or [])
        for column in table.get("columns") or []:
            if isinstance(column, dict) and column_allowed(column):
                haystack.append(str(column.get("name") or ""))
                haystack.append(str(column.get("description") or ""))
                haystack.extend(str(item) for item in column.get("synonyms") or [])
        text = " ".join(haystack).lower()
        return (sum(1 for term in terms if term in text), str(table.get("key") or table.get("name") or ""))

    ranked = sorted(tables, key=score, reverse=True)
    return ranked[:limit]


def table_allowed(table: dict[str, Any]) -> bool:
    return table.get("allowed") is not False and table.get("sensitive") is not True


def column_allowed(column: dict[str, Any]) -> bool:
    return column.get("allowed") is not False and column.get("sensitive") is not True


def schema_catalog_shared_group_paths(catalog_json: dict[str, Any]) -> list[str]:
    raw_paths = catalog_json.get("shared_group_paths")
    if not isinstance(raw_paths, list):
        return []
    return _dedupe_group_paths(raw_paths)


def schema_catalog_access_group_paths(owner_group_path: str, catalog_json: dict[str, Any]) -> list[str]:
    return _dedupe_group_paths([owner_group_path, *schema_catalog_shared_group_paths(catalog_json)])


def schema_catalog_visible_group_path(owner_group_path: str, catalog_json: dict[str, Any], visible_group_paths: Sequence[str]) -> str | None:
    visible = {normalize_group_path(path) for path in visible_group_paths}
    for group_path in schema_catalog_access_group_paths(owner_group_path, catalog_json):
        if normalize_group_path(group_path) in visible:
            return group_path
    return None


def schema_catalog_with_shared_group_paths(catalog_json: dict[str, Any], shared_group_paths: Sequence[str]) -> dict[str, Any]:
    result = dict(catalog_json)
    shared = _dedupe_group_paths(shared_group_paths)
    if shared:
        result["shared_group_paths"] = shared
    else:
        result.pop("shared_group_paths", None)
    result.pop("access_group_paths", None)
    return result


def table_key(schema: object, name: object) -> str:
    schema_text = str(schema or "").strip()
    name_text = str(name or "").strip()
    return normalize_table_key(f"{schema_text}.{name_text}" if schema_text else name_text)


def normalize_table_key(value: object) -> str:
    text = str(value or "").strip().replace("[", "").replace("]", "").replace('"', "")
    return ".".join(part.strip().lower() for part in text.split(".") if part.strip())


def normalize_identifier(value: object) -> str:
    return str(value or "").strip().replace("[", "").replace("]", "").replace('"', "").lower()


def _dedupe_group_paths(group_paths: Sequence[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw_path in group_paths:
        try:
            group_path = normalize_group_path(str(raw_path))
        except (TypeError, ValueError):
            continue
        if group_path not in seen:
            seen.add(group_path)
            result.append(group_path)
    return result


def _raw_tables(schema_json: dict[str, Any]) -> list[dict[str, Any]]:
    tables = schema_json.get("tables")
    if isinstance(tables, list):
        return [table for table in tables if isinstance(table, dict)]
    collections = schema_json.get("collections")
    if isinstance(collections, list):
        return [
            {
                **collection,
                "schema": str(collection.get("name") or "").split(".", 1)[0] if "." in str(collection.get("name") or "") else "",
                "name": str(collection.get("name") or "").split(".")[-1],
            }
            for collection in collections
            if isinstance(collection, dict)
        ]
    return []
