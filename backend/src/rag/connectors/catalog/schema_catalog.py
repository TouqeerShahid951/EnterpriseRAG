"""Approved connector schema catalog helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from copy import deepcopy
from typing import Any

from rag.shared.contracts.group_paths import normalize_group_path

_TERM_RE = re.compile(r"[A-Za-z0-9_]{3,}")
_ROUTING_LIST_FIELDS = (
    "domains",
    "entities",
    "metrics",
    "synonyms",
    "example_questions",
    "exclusions",
)
_NUMERIC_TYPE_PARTS = ("decimal", "double", "float", "int", "money", "numeric", "real")
_TEMPORAL_TYPE_PARTS = ("date", "time")


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
        "version": 2,
        "source": "connector_introspection",
        "sample_values_included": False,
        "name": "",
        "description": "",
        "routing_profile": {field: [] for field in _ROUTING_LIST_FIELDS},
        "verified_queries": [],
        "tables": tables,
        "relationships": relationships,
        "business_rules": [],
    }


def schema_catalog_routing_card(catalog_json: dict[str, Any]) -> dict[str, object]:
    """Return compact, non-sensitive catalog metadata suitable for source routing."""

    profile = catalog_json.get("routing_profile")
    profile = profile if isinstance(profile, dict) else {}
    card: dict[str, object] = {
        "name": _compact_routing_text(catalog_json.get("name"), max_chars=120),
        "description": _compact_routing_text(
            catalog_json.get("description"), max_chars=500
        ),
    }
    for field in _ROUTING_LIST_FIELDS:
        card[field] = _routing_values(profile.get(field), limit=20)
    card["capabilities"] = _routing_values(
        profile.get("capabilities", catalog_json.get("capabilities")), limit=20
    )
    for field in ("freshness", "data_origin", "provenance"):
        card[field] = _compact_routing_text(
            profile.get(field, catalog_json.get(field)), max_chars=240
        )
    card["schema_terms"] = _schema_routing_terms(catalog_json, limit=60)
    return card


def schema_catalog_routing_text(catalog_json: dict[str, Any]) -> str:
    """Render the routing card as searchable text without exposing physical schema."""

    card = schema_catalog_routing_card(catalog_json)
    values = [str(card["name"]), str(card["description"])]
    for field in _ROUTING_LIST_FIELDS:
        values.extend(str(item) for item in card[field])  # type: ignore[union-attr]
    values.extend(str(item) for item in card["capabilities"])  # type: ignore[union-attr]
    values.extend(str(item) for item in card["schema_terms"])  # type: ignore[union-attr]
    values.extend(
        str(card[field]) for field in ("freshness", "data_origin", "provenance")
    )
    return " ".join(value for value in values if value).strip()


def populate_schema_catalog_routing_profile(
    catalog_json: dict[str, Any],
    *,
    profile_name: str,
) -> dict[str, Any]:
    """Fill missing routing metadata from approved schema facts without replacing admin edits."""

    result = deepcopy(catalog_json)
    tables = [
        table
        for table in result.get("tables") or []
        if isinstance(table, dict) and table_allowed(table)
    ]
    entities = _unique_routing_values(
        _humanize_identifier(table.get("name") or table.get("key"))
        for table in tables
    )[:20]
    synonyms = _unique_routing_values(
        str(item)
        for table in tables
        for value in (table.get("synonyms"),)
        for item in (value if isinstance(value, list) else [])
    )
    metrics: list[str] = []
    has_temporal_column = False
    for table in tables:
        primary_keys = {
            str(item).strip().lower()
            for item in table.get("primary_keys") or []
            if isinstance(item, str)
        }
        for column in table.get("columns") or []:
            if not isinstance(column, dict) or not column_allowed(column):
                continue
            column_name = str(column.get("name") or "").strip()
            data_type = str(column.get("data_type") or column.get("type") or "").lower()
            has_temporal_column = has_temporal_column or any(
                part in data_type for part in _TEMPORAL_TYPE_PARTS
            )
            column_synonyms = column.get("synonyms")
            if isinstance(column_synonyms, list):
                synonyms.extend(str(item) for item in column_synonyms)
            if (
                column_name
                and column_name.lower() not in primary_keys
                and not column_name.lower().endswith("_id")
                and any(part in data_type for part in _NUMERIC_TYPE_PARTS)
            ):
                metrics.append(_humanize_identifier(column_name))
    metrics = _unique_routing_values(metrics)[:20]
    synonyms = _unique_routing_values(synonyms)[:20]
    verified_questions = _unique_routing_values(
        str(item.get("question") or "")
        for item in result.get("verified_queries") or []
        if isinstance(item, dict)
    )
    example_questions = verified_questions[:20] or [
        f"Show records for {entity}." for entity in entities[:3]
    ]
    capabilities = ["exact_lookup", "filtering"]
    if metrics:
        capabilities.append("aggregation")
    if has_temporal_column:
        capabilities.append("temporal_filtering")
    if any(
        isinstance(item, dict) and item.get("allowed") is not False
        for item in result.get("relationships") or []
    ):
        capabilities.append("joins")

    existing = result.get("routing_profile")
    profile = dict(existing) if isinstance(existing, dict) else {}
    generated_lists = {
        "domains": [profile_name] if profile_name.strip() else [],
        "entities": entities,
        "metrics": metrics,
        "synonyms": synonyms,
        "example_questions": example_questions,
        "exclusions": [],
        "capabilities": capabilities,
    }
    for field, generated in generated_lists.items():
        if not _routing_values(profile.get(field), limit=20):
            profile[field] = generated
    for field, value in {
        "freshness": "unspecified",
        "data_origin": "unspecified",
        "provenance": "connector_introspection",
    }.items():
        if not _compact_routing_text(profile.get(field), max_chars=240):
            profile[field] = value
    result["routing_profile"] = profile

    if not _compact_routing_text(result.get("name"), max_chars=120):
        result["name"] = (
            f"{profile_name.strip()} structured data"
            if profile_name.strip()
            else "Approved structured data"
        )
    if not _compact_routing_text(result.get("description"), max_chars=500):
        entity_summary = ", ".join(entities[:4]) or "approved schema records"
        result["description"] = f"Approved structured access to {entity_summary}."
    return result


def _routing_values(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    for item in value:
        cleaned = _compact_routing_text(item, max_chars=240)
        if cleaned and cleaned.lower() not in {existing.lower() for existing in values}:
            values.append(cleaned)
        if len(values) >= limit:
            break
    return values


def _schema_routing_terms(catalog_json: dict[str, Any], *, limit: int) -> list[str]:
    values: list[str] = []
    for table in catalog_json.get("tables") or []:
        if not isinstance(table, dict) or not table_allowed(table):
            continue
        values.extend(
            str(table.get(field) or "")
            for field in ("name", "description")
        )
        values.extend(str(item) for item in table.get("synonyms") or [])
        for column in table.get("columns") or []:
            if not isinstance(column, dict) or not column_allowed(column):
                continue
            values.extend(
                str(column.get(field) or "")
                for field in ("name", "description")
            )
            values.extend(str(item) for item in column.get("synonyms") or [])
    return _unique_routing_values(values)[:limit]


def _unique_routing_values(values: Iterable[object]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _compact_routing_text(value, max_chars=240)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        unique.append(cleaned)
        seen.add(key)
    return unique


def _humanize_identifier(value: object) -> str:
    text = str(value or "").rsplit(".", 1)[-1]
    return " ".join(part for part in re.split(r"[_\s]+", text) if part).strip()


def _compact_routing_text(value: object, *, max_chars: int) -> str:
    return " ".join(str(value or "").split())[:max_chars].strip()


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
    verified_queries = [
        item
        for item in catalog_json.get("verified_queries") or []
        if isinstance(item, dict)
        and str(item.get("question") or "").strip()
        and str(item.get("sql") or "").strip()
    ]
    if verified_queries:
        lines.append("Admin-verified query examples:")
        for item in verified_queries[:10]:
            lines.append(f"- Question: {str(item['question']).strip()[:500]}")
            lines.append(f"  SQL: {str(item['sql']).strip()[:2000]}")
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
