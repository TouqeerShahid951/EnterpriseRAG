"""LLM-assisted draft enrichment for connector schema catalogs."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from .schema_catalog import normalize_table_key

_MAX_PROMPT_TABLES = 4
_MAX_PROMPT_COLUMNS_PER_TABLE = 8
_MAX_PROMPT_INDEXES_PER_TABLE = 4
_MAX_PROMPT_RELATIONSHIPS = 8
_RETRY_PROMPT_TABLES = 2
_RETRY_PROMPT_COLUMNS_PER_TABLE = 6
_RETRY_PROMPT_INDEXES_PER_TABLE = 2
_RETRY_PROMPT_RELATIONSHIPS = 4
_SCHEMA_ENRICHMENT_MAX_OUTPUT_TOKENS = 1024
_SCHEMA_ENRICHMENT_RETRY_MAX_OUTPUT_TOKENS = 768
_TABLE_ENRICHMENT_MAX_OUTPUT_TOKENS = 4096
_TABLE_ENRICHMENT_RETRY_MAX_OUTPUT_TOKENS = 3072
_MAX_DESCRIPTION_CHARS = 600
_MAX_SYNONYMS = 8
_MAX_BUSINESS_RULES = 20


class SchemaEnrichmentError(RuntimeError):
    """Raised when schema enrichment cannot produce usable JSON."""


def initialize_schema_catalog_enrichment(catalog_json: dict[str, Any]) -> dict[str, Any]:
    """Prepare a complete raw catalog for checkpointed table enrichment."""

    result = deepcopy(catalog_json)
    table_statuses = [
        {"table_key": key, "status": "pending"}
        for key in schema_catalog_table_keys(result)
    ]
    result["source"] = "connector_introspection_ai_draft"
    result["sample_values_included"] = False
    result["ai_enrichment"] = {
        "status": "pending" if table_statuses else "generated",
        "source": "llm_schema_enrichment",
        "requires_admin_review": True,
        "total_tables": len(table_statuses),
        "completed_tables": 0,
        "failed_tables": 0,
        "table_statuses": table_statuses,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    return result


def schema_catalog_table_keys(catalog_json: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for table in catalog_json.get("tables") or []:
        if not isinstance(table, dict):
            continue
        key = normalize_table_key(table.get("key") or _table_key(table))
        if not key or key in seen:
            continue
        keys.append(key)
        seen.add(key)
    return keys


def enrich_schema_table_with_llm(
    catalog_json: dict[str, Any],
    *,
    table_key: str,
    connector_type: str,
    profile_name: str,
    llm: object,
    model: str | None,
) -> dict[str, Any]:
    """Enrich one existing table and checkpoint the result in the catalog."""

    normalized_key = normalize_table_key(table_key)
    table = _catalog_table(catalog_json, normalized_key)
    if table is None:
        raise SchemaEnrichmentError("schema enrichment table was not found in this catalog")
    generator = getattr(llm, "generate_json", None)
    if generator is None:
        raise SchemaEnrichmentError("language client does not support JSON generation")

    scoped_catalog = _table_scoped_catalog(catalog_json, normalized_key)
    last_error: SchemaEnrichmentError | None = None
    enriched = deepcopy(catalog_json)
    for retry, max_tokens in ((False, _TABLE_ENRICHMENT_MAX_OUTPUT_TOKENS), (True, _TABLE_ENRICHMENT_RETRY_MAX_OUTPUT_TOKENS)):
        try:
            raw = generator(
                prompt=_table_enrichment_prompt(
                    scoped_catalog,
                    connector_type=connector_type,
                    profile_name=profile_name,
                    table_key=normalized_key,
                    retry=retry,
                ),
                model=model,
                system=(
                    "Return exactly one valid JSON object. No markdown, prose, comments, or trailing text."
                    if retry
                    else "You draft concise business metadata for one database table. Return strict JSON only."
                ),
                max_tokens=max_tokens,
            )
            payload = _load_json_object(str(raw))
            candidate = merge_schema_enrichment(enriched, payload)
            enriched = candidate
            if not _table_has_ai_metadata(candidate, normalized_key):
                raise SchemaEnrichmentError("schema enrichment did not describe the requested table and every column")
            break
        except SchemaEnrichmentError as exc:
            last_error = exc
    else:
        if _table_has_any_ai_metadata(enriched, normalized_key):
            return _set_table_enrichment_status(
                enriched,
                normalized_key,
                status="failed",
                error_message=str(last_error) if last_error else "Schema table enrichment was incomplete.",
            )
        raise SchemaEnrichmentError(f"{last_error}; retry after invalid table enrichment also failed") from last_error

    return _set_table_enrichment_status(enriched, normalized_key, status="generated")


def schema_catalog_with_table_enrichment_failure(
    catalog_json: dict[str, Any],
    *,
    table_key: str,
    error_message: str,
) -> dict[str, Any]:
    return _set_table_enrichment_status(
        catalog_json,
        normalize_table_key(table_key),
        status="failed",
        error_message=error_message,
    )


def enrich_schema_catalog_with_llm(
    catalog_json: dict[str, Any],
    *,
    connector_type: str,
    profile_name: str,
    llm: object,
    model: str | None,
) -> dict[str, Any]:
    """Return a draft catalog with LLM-proposed descriptions merged in.

    The merge is deliberately one-way: the LLM may describe known tables,
    columns, joins, and business rules, but it may not add schema objects or
    change access-control fields such as allowed/sensitive.
    """

    generator = getattr(llm, "generate_json", None)
    if generator is None:
        raise SchemaEnrichmentError("language client does not support JSON generation")

    try:
        raw = generator(
            prompt=_schema_enrichment_prompt(
                catalog_json,
                connector_type=connector_type,
                profile_name=profile_name,
            ),
            model=model,
            system="You draft concise business metadata for database schemas. Return strict JSON only.",
            max_tokens=_SCHEMA_ENRICHMENT_MAX_OUTPUT_TOKENS,
        )
        payload = _load_json_object(str(raw))
        enriched = _merge_payload_or_raise(catalog_json, payload)
    except SchemaEnrichmentError as exc:
        try:
            raw = generator(
                prompt=_schema_enrichment_prompt(
                    catalog_json,
                    connector_type=connector_type,
                    profile_name=profile_name,
                    max_tables=_RETRY_PROMPT_TABLES,
                    max_columns_per_table=_RETRY_PROMPT_COLUMNS_PER_TABLE,
                    max_indexes_per_table=_RETRY_PROMPT_INDEXES_PER_TABLE,
                    max_relationships=_RETRY_PROMPT_RELATIONSHIPS,
                    retry=True,
                ),
                model=model,
                system="Return exactly one valid JSON object. No markdown, prose, comments, or trailing text.",
                max_tokens=_SCHEMA_ENRICHMENT_RETRY_MAX_OUTPUT_TOKENS,
            )
            payload = _load_json_object(str(raw))
            enriched = _merge_payload_or_raise(catalog_json, payload)
        except SchemaEnrichmentError as retry_exc:
            raise SchemaEnrichmentError(f"{retry_exc}; retry after invalid JSON also failed") from exc
    metadata = dict(enriched.get("ai_enrichment") if isinstance(enriched.get("ai_enrichment"), dict) else {})
    metadata.update(
        {
            "status": "generated",
            "generated_at": datetime.now(UTC).isoformat(),
            "source": "llm_schema_enrichment",
            "requires_admin_review": True,
        }
    )
    enriched["ai_enrichment"] = metadata
    return enriched


def _merge_payload_or_raise(catalog_json: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    enriched = merge_schema_enrichment(catalog_json, payload)
    if not (catalog_json.get("tables") or catalog_json.get("relationships")):
        return enriched
    if _catalog_has_ai_metadata(enriched):
        return enriched
    raise SchemaEnrichmentError("schema enrichment did not describe approved schema objects")


def _catalog_has_ai_metadata(catalog_json: dict[str, Any]) -> bool:
    if any(_clean_text(item, max_chars=_MAX_DESCRIPTION_CHARS) for item in catalog_json.get("business_rules") or []):
        return True
    for table in catalog_json.get("tables") or []:
        if not isinstance(table, dict):
            continue
        if _clean_text(table.get("description"), max_chars=_MAX_DESCRIPTION_CHARS) or _clean_synonyms(table.get("synonyms")):
            return True
        for column in table.get("columns") or []:
            if not isinstance(column, dict):
                continue
            if _clean_text(column.get("description"), max_chars=_MAX_DESCRIPTION_CHARS) or _clean_synonyms(column.get("synonyms")):
                return True
    for relationship in catalog_json.get("relationships") or []:
        if isinstance(relationship, dict) and _clean_text(relationship.get("description"), max_chars=_MAX_DESCRIPTION_CHARS):
            return True
    return False


def schema_catalog_with_enrichment_failure(catalog_json: dict[str, Any], *, error_message: str) -> dict[str, Any]:
    result = deepcopy(catalog_json)
    result["source"] = "connector_introspection_ai_draft_fallback"
    result["sample_values_included"] = False
    metadata = dict(result.get("ai_enrichment") if isinstance(result.get("ai_enrichment"), dict) else {})
    metadata.update(
        {
            "status": "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "source": "llm_schema_enrichment",
            "requires_admin_review": True,
            "error_message": _clean_text(error_message, max_chars=_MAX_DESCRIPTION_CHARS) or "Schema enrichment failed.",
        }
    )
    result["ai_enrichment"] = metadata
    return result


def merge_schema_enrichment(catalog_json: dict[str, Any], enrichment_json: dict[str, Any]) -> dict[str, Any]:
    """Merge LLM schema descriptions into a catalog without changing scope."""

    result = deepcopy(catalog_json)
    tables_by_key = {
        normalize_table_key(table.get("key") or _table_key(table))
        for table in result.get("tables") or []
        if isinstance(table, dict)
    }
    table_enrichments = {
        normalize_table_key(item.get("key") or item.get("table") or item.get("name")): item
        for item in enrichment_json.get("tables") or []
        if isinstance(item, dict)
    }
    table_enrichments = {key: value for key, value in table_enrichments.items() if key in tables_by_key}

    for table in result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        table_key = normalize_table_key(table.get("key") or _table_key(table))
        incoming = table_enrichments.get(table_key)
        if incoming is None:
            continue
        description = _clean_text(incoming.get("description"), max_chars=_MAX_DESCRIPTION_CHARS)
        if description:
            table["description"] = description
        synonyms = _clean_synonyms(incoming.get("synonyms"))
        if synonyms:
            table["synonyms"] = synonyms

        column_enrichments = {
            str(item.get("name") or item.get("column") or "").strip().lower(): item
            for item in incoming.get("columns") or []
            if isinstance(item, dict)
        }
        for column in table.get("columns") or []:
            if not isinstance(column, dict):
                continue
            column_name = str(column.get("name") or "").strip().lower()
            column_incoming = column_enrichments.get(column_name)
            if column_incoming is None:
                continue
            col_description = _clean_text(column_incoming.get("description"), max_chars=_MAX_DESCRIPTION_CHARS)
            if col_description:
                column["description"] = col_description
            col_synonyms = _clean_synonyms(column_incoming.get("synonyms"))
            if col_synonyms:
                column["synonyms"] = col_synonyms

    relationship_enrichments = _relationship_enrichments(enrichment_json)
    for relationship in result.get("relationships") or []:
        if not isinstance(relationship, dict):
            continue
        key = _relationship_key(relationship)
        description = _clean_text(relationship_enrichments.get(key), max_chars=_MAX_DESCRIPTION_CHARS)
        if description:
            relationship["description"] = description

    rules = [
        _clean_text(item, max_chars=_MAX_DESCRIPTION_CHARS)
        for item in enrichment_json.get("business_rules") or []
    ]
    rules = [item for item in rules if item]
    if rules:
        existing_rules = [
            _clean_text(item, max_chars=_MAX_DESCRIPTION_CHARS)
            for item in result.get("business_rules") or []
        ]
        result["business_rules"] = _unique_text([*existing_rules, *rules])[:_MAX_BUSINESS_RULES]

    result["source"] = "connector_introspection_ai_draft"
    result["sample_values_included"] = False
    return result


def _catalog_table(catalog_json: dict[str, Any], table_key: str) -> dict[str, Any] | None:
    for table in catalog_json.get("tables") or []:
        if not isinstance(table, dict):
            continue
        if normalize_table_key(table.get("key") or _table_key(table)) == table_key:
            return table
    return None


def _table_scoped_catalog(catalog_json: dict[str, Any], table_key: str) -> dict[str, Any]:
    table = _catalog_table(catalog_json, table_key)
    relationships = [
        relationship
        for relationship in catalog_json.get("relationships") or []
        if isinstance(relationship, dict)
        and table_key in {
            normalize_table_key(relationship.get("left_table")),
            normalize_table_key(relationship.get("right_table")),
        }
    ]
    return {
        "tables": [deepcopy(table)] if table is not None else [],
        "relationships": deepcopy(relationships[:_MAX_PROMPT_RELATIONSHIPS]),
        "sample_values_included": False,
    }


def _table_enrichment_prompt(
    scoped_catalog: dict[str, Any],
    *,
    connector_type: str,
    profile_name: str,
    table_key: str,
    retry: bool,
) -> str:
    table = (scoped_catalog.get("tables") or [{}])[0]
    column_count = len(table.get("columns") or []) if isinstance(table, dict) else 0
    retry_instruction = (
        "The previous response was unusable. Return a smaller valid JSON object, but still describe the table and every listed column. "
        if retry
        else ""
    )
    return (
        retry_instruction
        + "Draft short human-reviewable metadata for exactly one database table. "
        "Use only the supplied table, columns, data types, keys, indexes, and relationships. "
        "Do not invent schema objects, sensitive values, sample data, people, credentials, or business facts. "
        "Do not change allowed or sensitive flags. Describe every listed column. "
        "Keep the table description under 14 words and each column description under 10 words. "
        "Use an empty synonyms list when no useful synonym exists.\n\n"
        "Return JSON with this shape:\n"
        "{"
        "\"tables\":[{\"key\":\"schema.table\",\"description\":\"...\",\"synonyms\":[\"...\"],"
        "\"columns\":[{\"name\":\"column\",\"description\":\"...\",\"synonyms\":[\"...\"]}]}],"
        "\"relationships\":[{\"left_table\":\"schema.table\",\"right_table\":\"schema.table\",\"description\":\"...\"}],"
        "\"business_rules\":[]"
        "}\n\n"
        f"Requested table: {table_key}\n"
        f"Expected column count: {column_count}\n"
        f"Connector profile: {profile_name}\n"
        f"Connector type: {connector_type}\n"
        f"Table schema JSON:\n{json.dumps(scoped_catalog, ensure_ascii=True)}"
    )


def _table_has_ai_metadata(catalog_json: dict[str, Any], table_key: str) -> bool:
    table = _catalog_table(catalog_json, table_key)
    if table is None:
        return False
    if not _clean_text(table.get("description"), max_chars=_MAX_DESCRIPTION_CHARS):
        return False
    columns = [column for column in table.get("columns") or [] if isinstance(column, dict)]
    return all(_clean_text(column.get("description"), max_chars=_MAX_DESCRIPTION_CHARS) for column in columns)


def _table_has_any_ai_metadata(catalog_json: dict[str, Any], table_key: str) -> bool:
    table = _catalog_table(catalog_json, table_key)
    if table is None:
        return False
    if _clean_text(table.get("description"), max_chars=_MAX_DESCRIPTION_CHARS):
        return True
    return any(
        _clean_text(column.get("description"), max_chars=_MAX_DESCRIPTION_CHARS)
        for column in table.get("columns") or []
        if isinstance(column, dict)
    )


def _set_table_enrichment_status(
    catalog_json: dict[str, Any],
    table_key: str,
    *,
    status: str,
    error_message: str | None = None,
) -> dict[str, Any]:
    result = deepcopy(catalog_json)
    metadata = dict(result.get("ai_enrichment") if isinstance(result.get("ai_enrichment"), dict) else {})
    known_keys = schema_catalog_table_keys(result)
    statuses_by_key: dict[str, dict[str, Any]] = {}
    for item in metadata.get("table_statuses") or []:
        if not isinstance(item, dict):
            continue
        key = normalize_table_key(item.get("table_key"))
        if key in known_keys:
            statuses_by_key[key] = dict(item)
    for key in known_keys:
        statuses_by_key.setdefault(key, {"table_key": key, "status": "pending"})

    item = {"table_key": table_key, "status": status, "updated_at": datetime.now(UTC).isoformat()}
    clean_error = _clean_text(error_message, max_chars=_MAX_DESCRIPTION_CHARS) if error_message else ""
    if clean_error:
        item["error_message"] = clean_error
    statuses_by_key[table_key] = item
    table_statuses = [statuses_by_key[key] for key in known_keys]
    completed = sum(1 for entry in table_statuses if entry.get("status") == "generated")
    failed = sum(1 for entry in table_statuses if entry.get("status") == "failed")
    terminal = completed + failed
    overall_status = "generated" if completed == len(known_keys) else "partial" if terminal == len(known_keys) else "in_progress"
    metadata.update(
        {
            "status": overall_status,
            "source": "llm_schema_enrichment",
            "requires_admin_review": True,
            "total_tables": len(known_keys),
            "completed_tables": completed,
            "failed_tables": failed,
            "table_statuses": table_statuses,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
    if overall_status in {"generated", "partial"}:
        metadata["generated_at"] = datetime.now(UTC).isoformat()
    if failed:
        metadata["error_message"] = f"AI enrichment failed for {failed} table{'s' if failed != 1 else ''}."
    else:
        metadata.pop("error_message", None)
    result["ai_enrichment"] = metadata
    result["source"] = "connector_introspection_ai_draft"
    result["sample_values_included"] = False
    return result


def _schema_enrichment_prompt(
    catalog_json: dict[str, Any],
    *,
    connector_type: str,
    profile_name: str,
    max_tables: int = _MAX_PROMPT_TABLES,
    max_columns_per_table: int = _MAX_PROMPT_COLUMNS_PER_TABLE,
    max_indexes_per_table: int = _MAX_PROMPT_INDEXES_PER_TABLE,
    max_relationships: int = _MAX_PROMPT_RELATIONSHIPS,
    retry: bool = False,
) -> str:
    compact = {
        "tables": [
            _compact_table(table, max_columns=max_columns_per_table, max_indexes=max_indexes_per_table)
            for table in (catalog_json.get("tables") or [])[:max_tables]
            if isinstance(table, dict)
        ],
        "relationships": [
            _compact_relationship(relationship)
            for relationship in (catalog_json.get("relationships") or [])[:max_relationships]
            if isinstance(relationship, dict)
        ],
        "sample_values_included": False,
    }
    retry_instruction = (
        "The previous response was not valid JSON. "
        "Return a smaller JSON object if needed; omitted tables can remain without AI descriptions. "
        if retry
        else ""
    )
    return (
        retry_instruction +
        "Draft short human-reviewable metadata for this approved database scope. "
        "Use table names, column names, data types, keys, indexes, and relationships only. "
        "Do not invent tables or columns. Do not infer sensitive values, credentials, people, or sample data. "
        "Do not change allowed or sensitive flags. Keep table descriptions under 14 words and column descriptions under 10 words. "
        "Describe only the tables and columns you can cover within the response budget.\n\n"
        "Return JSON with this shape:\n"
        "{"
        "\"tables\":[{\"key\":\"schema.table\",\"description\":\"...\",\"synonyms\":[\"...\"],"
        "\"columns\":[{\"name\":\"column\",\"description\":\"...\",\"synonyms\":[\"...\"]}]}],"
        "\"relationships\":[{\"left_table\":\"schema.table\",\"right_table\":\"schema.table\",\"description\":\"...\"}],"
        "\"business_rules\":[\"...\"]"
        "}\n\n"
        f"Connector profile: {profile_name}\n"
        f"Connector type: {connector_type}\n"
        f"Schema catalog JSON:\n{json.dumps(compact, ensure_ascii=True)}"
    )


def _compact_table(table: dict[str, Any], *, max_columns: int, max_indexes: int) -> dict[str, Any]:
    return {
        "key": normalize_table_key(table.get("key") or _table_key(table)),
        "kind": table.get("kind") or "table",
        "columns": [
            {
                "name": column.get("name"),
                "data_type": column.get("data_type") or column.get("type"),
                "nullable": column.get("nullable"),
            }
            for column in (table.get("columns") or [])[:max_columns]
            if isinstance(column, dict)
        ],
        "primary_keys": table.get("primary_keys") if isinstance(table.get("primary_keys"), list) else [],
        "indexes": table.get("indexes")[:max_indexes] if isinstance(table.get("indexes"), list) else [],
        "estimated_row_count": table.get("estimated_row_count"),
    }


def _compact_relationship(relationship: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": relationship.get("name"),
        "left_table": normalize_table_key(relationship.get("left_table")),
        "left_columns": relationship.get("left_columns") or [],
        "right_table": normalize_table_key(relationship.get("right_table")),
        "right_columns": relationship.get("right_columns") or [],
    }


def _load_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    candidates = [text]
    candidates.extend(match.group(1).strip() for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL))
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
        else:
            if isinstance(payload, dict) and _looks_like_schema_enrichment_payload(payload):
                return payload
            if not isinstance(payload, dict):
                raise SchemaEnrichmentError("schema enrichment JSON must be an object")
        extracted = _extract_first_json_object(candidate)
        if extracted is not None:
            return extracted
        salvaged_tables = _extract_schema_table_objects(candidate)
        if salvaged_tables:
            return {"tables": salvaged_tables, "relationships": [], "business_rules": []}
    raise SchemaEnrichmentError("schema enrichment did not return valid JSON") from last_error


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and _looks_like_schema_enrichment_payload(payload):
            return payload
    return None


def _looks_like_schema_enrichment_payload(payload: dict[str, Any]) -> bool:
    return any(key in payload for key in ("tables", "relationships", "business_rules"))


def _extract_schema_table_objects(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    tables: list[dict[str, Any]] = []
    seen: set[str] = set()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        key = normalize_table_key(payload.get("key") or payload.get("table") or payload.get("name"))
        if not key or key in seen:
            continue
        if "columns" not in payload and not _clean_text(payload.get("description"), max_chars=_MAX_DESCRIPTION_CHARS):
            continue
        tables.append(payload)
        seen.add(key)
        if len(tables) >= _MAX_PROMPT_TABLES:
            break
    return tables


def _relationship_enrichments(enrichment_json: dict[str, Any]) -> dict[tuple[str, str, tuple[str, ...], tuple[str, ...]], str]:
    descriptions: dict[tuple[str, str, tuple[str, ...], tuple[str, ...]], str] = {}
    for item in enrichment_json.get("relationships") or []:
        if not isinstance(item, dict):
            continue
        key = _relationship_key(item)
        description = _clean_text(item.get("description"), max_chars=_MAX_DESCRIPTION_CHARS)
        if description:
            descriptions[key] = description
    return descriptions


def _relationship_key(value: dict[str, Any]) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    return (
        normalize_table_key(value.get("left_table")),
        normalize_table_key(value.get("right_table")),
        tuple(str(item).strip().lower() for item in value.get("left_columns") or []),
        tuple(str(item).strip().lower() for item in value.get("right_columns") or []),
    )


def _table_key(table: dict[str, Any]) -> str:
    schema = str(table.get("schema") or "").strip()
    name = str(table.get("name") or "").strip()
    return f"{schema}.{name}" if schema else name


def _clean_text(value: object, *, max_chars: int) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    return text[:max_chars].strip()


def _clean_synonyms(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_text(item, max_chars=80)
        key = text.lower()
        if not text or key in seen:
            continue
        cleaned.append(text)
        seen.add(key)
        if len(cleaned) >= _MAX_SYNONYMS:
            break
    return cleaned


def _unique_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.lower()
        if not value or key in seen:
            continue
        result.append(value)
        seen.add(key)
    return result
