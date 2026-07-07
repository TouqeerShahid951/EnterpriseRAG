"""Strict read-only SQL validation for connector selections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .schema_catalog import column_allowed, normalize_identifier, normalize_table_key, table_allowed, table_key

_BLOCKED_SQL_TOKENS = {
    "alter",
    "call",
    "copy",
    "create",
    "delete",
    "drop",
    "exec",
    "execute",
    "insert",
    "merge",
    "truncate",
    "update",
}
_GENERIC_BLOCKED_PATTERNS = (
    r"\binto\s+(?:#|@|[a-z_\"\[])",
    r"\bfor\s+(?:update|share|no\s+key\s+update|key\s+share)\b",
)
_SQL_SERVER_BLOCKED_PATTERNS = (
    r"\bopenrowset\b",
    r"\bopendatasource\b",
    r"\bopenquery\b",
    r"\bxp_cmdshell\b",
    r"\bxp_[a-z0-9_]+\b",
    r"\bsp_[a-z0-9_]+\b",
)
_POSTGRES_BLOCKED_PATTERNS = (
    r"\bdblink\s*\(",
    r"\bdblink_exec\s*\(",
    r"\blo_export\s*\(",
    r"\blo_import\s*\(",
    r"\bpg_cancel_backend\s*\(",
    r"\bpg_ls_dir\s*\(",
    r"\bpg_read_binary_file\s*\(",
    r"\bpg_read_file\s*\(",
    r"\bpg_reload_conf\s*\(",
    r"\bpg_stat_file\s*\(",
    r"\bpg_terminate_backend\s*\(",
)
_SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "sys"}


class SqlValidationError(ValueError):
    """Raised when a connector SQL selection is not safely read-only."""


def validate_read_only_sql(query: str, *, connector_type: str = "sql_server") -> str:
    cleaned = query.strip()
    if not cleaned:
        raise SqlValidationError("SQL selection cannot be empty.")
    if "--" in cleaned or "/*" in cleaned or "*/" in cleaned:
        raise SqlValidationError("SQL comments are not allowed in connector selections.")
    if _contains_chained_statements(cleaned):
        raise SqlValidationError("Only one SQL statement is allowed.")
    statement = cleaned[:-1].strip() if cleaned.endswith(";") else cleaned
    lowered = statement.lower()
    if not re.match(r"^\s*(select|with)\b", lowered):
        raise SqlValidationError("Connector SQL must start with SELECT or WITH.")
    tokens = set(re.findall(r"\b[a-z_][a-z0-9_]*\b", lowered))
    blocked = sorted(tokens & _BLOCKED_SQL_TOKENS)
    if blocked:
        raise SqlValidationError(f"Connector SQL contains blocked keyword: {blocked[0].upper()}.")
    for pattern in _GENERIC_BLOCKED_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            raise SqlValidationError(f"Connector SQL contains blocked pattern: {match.group(0).upper()}.")
    if connector_type == "sql_server":
        for pattern in _SQL_SERVER_BLOCKED_PATTERNS:
            match = re.search(pattern, lowered)
            if match:
                raise SqlValidationError(f"SQL Server selection contains blocked pattern: {match.group(0).upper()}.")
    if connector_type == "postgres":
        for pattern in _POSTGRES_BLOCKED_PATTERNS:
            match = re.search(pattern, lowered)
            if match:
                raise SqlValidationError(f"PostgreSQL selection contains blocked pattern: {match.group(0).upper()}.")
    return statement


def validate_live_sql_for_approved_selection(query: str, *, connector_type: str = "sql_server") -> str:
    """Validate generated live SQL against the approved schedule selection CTE.

    Live SQL is intentionally stricter than connector sync SQL. The generated
    statement may only read from the caller-provided approved_selection CTE, so a
    schedule selection stays the access boundary even when the agent writes SQL.
    """

    statement = validate_read_only_sql(query, connector_type=connector_type)
    lowered = statement.lower()
    if re.match(r"^\s*with\b", lowered):
        raise SqlValidationError("Live connector SQL cannot define additional CTEs.")
    if re.search(r"\bjoin\b", lowered):
        raise SqlValidationError("Live connector SQL cannot join additional relations.")
    relations = _referenced_relations(statement)
    if not relations:
        raise SqlValidationError("Live connector SQL must read from approved_selection.")
    invalid = sorted(relation for relation in relations if relation != "approved_selection")
    if invalid:
        raise SqlValidationError("Live connector SQL can only read from approved_selection.")
    return statement


def wrap_approved_selection_query(approved_query: str, live_query: str, *, connector_type: str = "sql_server") -> str:
    approved = validate_read_only_sql(approved_query, connector_type=connector_type)
    generated = validate_live_sql_for_approved_selection(live_query, connector_type=connector_type)
    return f"WITH approved_selection AS (\n{approved}\n)\n{generated}"


def validate_live_sql_for_approved_catalog(
    query: str,
    *,
    catalog_json: dict[str, Any],
    connector_type: str = "sql_server",
    row_limit: int = 100,
) -> str:
    """Validate generated SQL against an admin-approved database catalog."""

    statement = validate_read_only_sql(query, connector_type=connector_type)
    if re.match(r"^\s*with\b", statement, flags=re.IGNORECASE):
        raise SqlValidationError("Live connector SQL cannot define CTEs for approved database scopes.")
    expression = _parse_sql(statement, connector_type)
    _require_select_expression(expression)
    if list(expression.find_all(_sqlglot_exp().Subquery)):
        raise SqlValidationError("Live connector SQL cannot use derived-table subqueries.")
    catalog = _Catalog.from_json(catalog_json)
    references = _catalog_table_references(expression, catalog)
    if not references:
        raise SqlValidationError("Live connector SQL must read from at least one approved table.")
    _validate_catalog_columns(expression, catalog, references)
    _validate_catalog_joins(expression, catalog, references)
    return _ensure_row_limit(expression, statement, connector_type=connector_type, row_limit=row_limit)


def _contains_chained_statements(value: str) -> bool:
    if ";" not in value:
        return False
    stripped = value.rstrip()
    if stripped.endswith(";") and stripped.count(";") == 1:
        return False
    return True


def _referenced_relations(statement: str) -> set[str]:
    relations: set[str] = set()
    for match in re.finditer(r"\bfrom\s+([^\s,;)]+)", statement, flags=re.IGNORECASE):
        relation = _normalize_relation(match.group(1))
        if relation:
            relations.add(relation)
    return relations


def _normalize_relation(value: str) -> str:
    text = value.strip().rstrip(";")
    if text.startswith("("):
        return ""
    if "." in text:
        return text.lower()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("[") and text.endswith("]")):
        text = text[1:-1]
    return text.strip().lower()


@dataclass(frozen=True)
class _CatalogColumn:
    name: str
    allowed: bool
    sensitive: bool


@dataclass(frozen=True)
class _CatalogTable:
    key: str
    schema: str
    name: str
    allowed: bool
    sensitive: bool
    columns: dict[str, _CatalogColumn]


@dataclass(frozen=True)
class _TableReference:
    key: str
    alias: str
    schema: str
    name: str


class _Catalog:
    def __init__(self, tables: dict[str, _CatalogTable], relationships: set[tuple[str, tuple[str, ...], str, tuple[str, ...]]]) -> None:
        self.tables = tables
        self.relationships = relationships

    @classmethod
    def from_json(cls, catalog_json: dict[str, Any]) -> "_Catalog":
        tables: dict[str, _CatalogTable] = {}
        for raw_table in catalog_json.get("tables") or []:
            if not isinstance(raw_table, dict):
                continue
            key = normalize_table_key(raw_table.get("key") or table_key(raw_table.get("schema"), raw_table.get("name")))
            if not key:
                continue
            schema_value = raw_table.get("schema")
            schema = normalize_identifier(schema_value if schema_value else (key.rsplit(".", 1)[0] if "." in key else ""))
            name = normalize_identifier(raw_table.get("name") or key.rsplit(".", 1)[-1])
            columns: dict[str, _CatalogColumn] = {}
            for raw_column in raw_table.get("columns") or []:
                if not isinstance(raw_column, dict) or not raw_column.get("name"):
                    continue
                column_name = normalize_identifier(raw_column["name"])
                columns[column_name] = _CatalogColumn(
                    name=column_name,
                    allowed=column_allowed(raw_column),
                    sensitive=raw_column.get("sensitive") is True,
                )
            tables[key] = _CatalogTable(
                key=key,
                schema=schema,
                name=name,
                allowed=table_allowed(raw_table),
                sensitive=raw_table.get("sensitive") is True,
                columns=columns,
            )
        relationships: set[tuple[str, tuple[str, ...], str, tuple[str, ...]]] = set()
        for raw_relationship in catalog_json.get("relationships") or []:
            if not isinstance(raw_relationship, dict) or raw_relationship.get("allowed") is False:
                continue
            left = normalize_table_key(raw_relationship.get("left_table"))
            right = normalize_table_key(raw_relationship.get("right_table"))
            left_cols = tuple(normalize_identifier(item) for item in raw_relationship.get("left_columns") or [])
            right_cols = tuple(normalize_identifier(item) for item in raw_relationship.get("right_columns") or [])
            if left and right and left_cols and right_cols:
                relationships.add((left, left_cols, right, right_cols))
                relationships.add((right, right_cols, left, left_cols))
        return cls(tables, relationships)

    def resolve_table(self, *, schema: object, name: object) -> _CatalogTable | None:
        schema_text = normalize_identifier(schema)
        name_text = normalize_identifier(name)
        if schema_text in _SYSTEM_SCHEMAS:
            return None
        if schema_text:
            return self.tables.get(f"{schema_text}.{name_text}")
        exact = self.tables.get(name_text)
        if exact is not None:
            return exact
        matches = [table for table in self.tables.values() if table.name == name_text]
        return matches[0] if len(matches) == 1 else None

    def relationship_allows(self, left_table: str, left_column: str, right_table: str, right_column: str) -> bool:
        left = normalize_table_key(left_table)
        right = normalize_table_key(right_table)
        left_col = normalize_identifier(left_column)
        right_col = normalize_identifier(right_column)
        for rel_left, rel_left_cols, rel_right, rel_right_cols in self.relationships:
            if rel_left != left or rel_right != right:
                continue
            pairs = zip(rel_left_cols, rel_right_cols, strict=False)
            if any(left_item == left_col and right_item == right_col for left_item, right_item in pairs):
                return True
        return False


def _parse_sql(statement: str, connector_type: str):
    try:
        import sqlglot
    except ImportError as exc:
        raise SqlValidationError("sqlglot is required for approved database scope validation.") from exc
    try:
        return sqlglot.parse_one(statement, read=_sqlglot_dialect(connector_type))
    except Exception as exc:
        raise SqlValidationError("Live connector SQL could not be parsed safely.") from exc


def _require_select_expression(expression: object) -> None:
    exp = _sqlglot_exp()
    if not isinstance(expression, exp.Select):
        raise SqlValidationError("Live connector SQL must be a SELECT statement.")


def _catalog_table_references(expression: object, catalog: _Catalog) -> dict[str, _TableReference]:
    exp = _sqlglot_exp()
    references: dict[str, _TableReference] = {}
    for table_expr in expression.find_all(exp.Table):
        table = catalog.resolve_table(schema=table_expr.db, name=table_expr.name)
        if table is None or not table.allowed or table.sensitive:
            raise SqlValidationError("Live connector SQL references an unapproved table.")
        alias = normalize_identifier(table_expr.alias or table.name)
        references[alias] = _TableReference(key=table.key, alias=alias, schema=table.schema, name=table.name)
        references.setdefault(table.name, _TableReference(key=table.key, alias=table.name, schema=table.schema, name=table.name))
    return references


def _validate_catalog_columns(expression: object, catalog: _Catalog, references: dict[str, _TableReference]) -> None:
    exp = _sqlglot_exp()
    referenced_keys = sorted({reference.key for reference in references.values()})
    for star in expression.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise SqlValidationError("Live connector SQL cannot use wildcard column selection.")
    for column_expr in expression.find_all(exp.Column):
        column_name = normalize_identifier(column_expr.name)
        table_key = _resolve_column_table_key(column_expr, catalog, references, referenced_keys)
        if table_key is None:
            column_label = _column_label(column_expr)
            raise SqlValidationError(f"Live connector SQL references an unapproved or ambiguous column: {column_label}.")
        table = catalog.tables[table_key]
        column = table.columns.get(column_name)
        if column is None or not column.allowed or column.sensitive:
            column_label = _column_label(column_expr)
            allowed_excerpt = _approved_column_excerpt(table)
            hint = f" Approved columns for {table.key}: {allowed_excerpt}." if allowed_excerpt else ""
            raise SqlValidationError(
                f"Live connector SQL references an unapproved or sensitive column: {column_label} on {table.key}.{hint}"
            )


def _validate_catalog_joins(expression: object, catalog: _Catalog, references: dict[str, _TableReference]) -> None:
    exp = _sqlglot_exp()
    joins = list(expression.find_all(exp.Join))
    referenced_keys = {reference.key for reference in references.values()}
    if len(referenced_keys) <= 1:
        return
    if not joins:
        raise SqlValidationError("Live connector SQL cannot use implicit joins.")
    for join in joins:
        on_expr = join.args.get("on")
        if on_expr is None:
            raise SqlValidationError("Live connector SQL joins must use approved ON relationships.")
        allowed = False
        for equality in on_expr.find_all(exp.EQ):
            left, right = equality.left, equality.right
            if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
                continue
            left_table = _resolve_column_table_key(left, catalog, references, sorted(referenced_keys))
            right_table = _resolve_column_table_key(right, catalog, references, sorted(referenced_keys))
            if left_table and right_table and catalog.relationship_allows(left_table, left.name, right_table, right.name):
                allowed = True
                break
        if not allowed:
            raise SqlValidationError("Live connector SQL join is not in the approved relationship catalog.")


def _resolve_column_table_key(column_expr: object, catalog: _Catalog, references: dict[str, _TableReference], referenced_keys: list[str]) -> str | None:
    qualifier = normalize_identifier(getattr(column_expr, "table", ""))
    schema = normalize_identifier(getattr(column_expr, "db", ""))
    if schema and qualifier:
        table = catalog.resolve_table(schema=schema, name=qualifier)
        return table.key if table else None
    if qualifier:
        reference = references.get(qualifier)
        return reference.key if reference else None
    column_name = normalize_identifier(getattr(column_expr, "name", ""))
    matches = [key for key in referenced_keys if column_name in catalog.tables[key].columns]
    return matches[0] if len(matches) == 1 else None


def _column_label(column_expr: object) -> str:
    name = normalize_identifier(getattr(column_expr, "name", ""))
    qualifier = normalize_identifier(getattr(column_expr, "table", ""))
    schema = normalize_identifier(getattr(column_expr, "db", ""))
    parts = [part for part in (schema, qualifier, name) if part]
    return ".".join(parts) if parts else "<unknown>"


def _approved_column_excerpt(table: _CatalogTable, *, limit: int = 12) -> str:
    names = [column.name for column in table.columns.values() if column.allowed and not column.sensitive]
    if not names:
        return ""
    shown = names[:limit]
    suffix = ", ..." if len(names) > limit else ""
    return ", ".join(shown) + suffix


def _ensure_row_limit(expression: object, statement: str, *, connector_type: str, row_limit: int) -> str:
    if getattr(expression, "args", {}).get("limit") is not None:
        return statement
    bounded = expression.copy()
    exp = _sqlglot_exp()
    bounded.set("limit", exp.Limit(expression=exp.Literal.number(max(1, row_limit))))
    return bounded.sql(dialect=_sqlglot_dialect(connector_type))


def _sqlglot_dialect(connector_type: str) -> str:
    if connector_type == "sql_server":
        return "tsql"
    if connector_type == "postgres":
        return "postgres"
    return "postgres"


def _sqlglot_exp():
    from sqlglot import exp

    return exp
