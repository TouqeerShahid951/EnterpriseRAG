"""Live SQL retrieval over approved connector database scopes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import logging
import re
from typing import Any

from ..connectors.crypto import decrypt_secret, keyring_from_settings
from ..connectors.models import ConnectorProfileRecord, ConnectorQueryResult, ConnectorSchemaCatalogRecord
from ..connectors.repositories import ConnectorProfileRepository, get_connector_profile_repository
from ..connectors.registry import ConnectorRegistry, default_connector_registry
from ..connectors.schema_catalog import approved_schema_prompt, schema_catalog_access_group_paths, schema_catalog_visible_group_path
from ..connectors.sql_safety import SqlValidationError, validate_live_sql_for_approved_catalog
from ..core.config import Settings
from ..ingestion.folder_schedule_models import FolderScheduleRepository
from ..shared.contracts.clearance import clearance_rank
from .cancellation import QueryCancelled, cancellation_token_from_context
from .qdrant import SearchHit
from .routing_models import RoutePlan
from .source_resolution import selected_source_target
from .state import QueryContext, scoped_user_context

_ACTIVE_CATALOG_STATUSES = {"approved"}
_SQL_CONNECTOR_TYPES = {"postgres", "sql_server", "fake"}
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveSqlRetrievalResult:
    hits: list[SearchHit]
    mode: str
    detail: str


@dataclass(frozen=True)
class _RepairFeedback:
    stage: str
    message: str
    previous_sql: str | None = None


@dataclass(frozen=True)
class _LiveSqlExecution:
    result: ConnectorQueryResult
    attempts: int
    repairs: int


@dataclass(frozen=True)
class _ResultVerification:
    accepted: bool
    reason: str
    repair_instruction: str = ""


class _LiveSqlResultVerificationError(RuntimeError):
    """Raised when a safe SQL result shape does not answer the question."""


def retrieve_live_sql_hits(
    ctx: QueryContext,
    *,
    config: Settings,
    llm: object,
    reasoning_model: str | None = None,
    schedule_repo: FolderScheduleRepository | None = None,
    connector_profile_repo: ConnectorProfileRepository | None = None,
    connector_registry: ConnectorRegistry | None = None,
) -> LiveSqlRetrievalResult:
    if not getattr(config, "connector_live_sql_enabled", False):
        return LiveSqlRetrievalResult([], "skipped", "disabled")
    if ctx["request"].document_ids:
        return LiveSqlRetrievalResult([], "skipped", "document_scope")
    plan = ctx.get("route_plan")
    if not _should_run_live_sql(plan, ctx.get("source_decision")):
        return LiveSqlRetrievalResult([], "skipped", "non_structured_route")

    _ = schedule_repo
    connector_profile_repo = connector_profile_repo or get_connector_profile_repository()
    connector_registry = connector_registry or default_connector_registry()
    token = cancellation_token_from_context(ctx)
    question = plan.resolved_query if plan is not None else ctx["request"].query
    all_hits: list[SearchHit] = []
    failures: list[str] = []
    attempted_scopes = 0
    repair_count = 0
    max_scopes = max(1, int(getattr(config, "connector_live_sql_max_scopes", getattr(config, "connector_live_sql_max_schedules", 5))))
    max_repair_attempts = _max_repair_attempts(config)
    result_verifier_enabled = bool(getattr(config, "connector_live_sql_result_verifier_enabled", True))
    selected_source = selected_source_target(ctx.get("source_decision"))  # type: ignore[arg-type]
    catalogs = _eligible_catalogs(
        ctx,
        connector_profile_repo.list_schema_catalogs(),
        limit=max_scopes,
    )
    catalogs = [
        catalog
        for catalog in catalogs
        if _selected_source_allows(selected_source, "catalog", catalog.id)
    ]
    preferred_catalog_id = str(getattr(ctx.get("source_decision"), "preferred_catalog_id", "") or "")
    if preferred_catalog_id:
        catalogs = sorted(catalogs, key=lambda catalog: 0 if catalog.id == preferred_catalog_id else 1)
    for catalog in catalogs:
        if token is not None:
            token.raise_if_cancelled()
        try:
            profile = connector_profile_repo.get_profile(catalog.profile_id)
            if profile is None:
                failures.append(f"{catalog.id}:profile_missing")
                continue
            connector_type = str(profile.connector_type)
            if connector_type not in _SQL_CONNECTOR_TYPES:
                failures.append(f"{catalog.id}:unsupported_connector")
                continue
            row_limit = _catalog_row_limit(config, catalog)
            attempted_scopes += 1
            connector = connector_registry.get(connector_type)
            secrets = decrypt_secret(
                profile.encrypted_secrets,
                keyring_from_settings(config.connector_secrets_key, config.connector_secrets_key_ring),
            )
            execution = _run_with_sql_repair(
                ctx=ctx,
                scope="database_scope",
                target_id=catalog.id,
                connector_type=connector_type,
                max_repair_attempts=max_repair_attempts,
                cancellation_token=token,
                generate_sql=lambda feedback: _generate_catalog_live_sql(
                    llm,
                    question=question,
                    catalog=catalog,
                    profile=profile,
                    connector_type=connector_type,
                    reasoning_model=reasoning_model,
                    row_limit=row_limit,
                    cancellation_token=token,
                    repair_feedback=feedback,
                ),
                validate_sql=lambda generated_sql: validate_live_sql_for_approved_catalog(
                    generated_sql,
                    catalog_json=catalog.catalog_json,
                    connector_type=connector_type,
                    row_limit=row_limit,
                ),
                execute_sql=lambda live_query: connector.execute_query(
                    config=profile.public_config,
                    secrets=secrets,
                    query=live_query,
                    row_limit=row_limit,
                    timeout_seconds=max(1, int(getattr(config, "connector_live_sql_timeout_seconds", 15))),
                ),
                verify_result=(
                    lambda live_query, result: _verify_live_sql_result(
                        llm,
                        question=question,
                        connector_type=connector_type,
                        scope="database_scope",
                        scope_name=_catalog_title(catalog, profile),
                        sql=live_query,
                        result=result,
                        row_limit=row_limit,
                        sample_rows=_verifier_sample_rows(config),
                        reasoning_model=reasoning_model,
                        cancellation_token=token,
                    )
                    if result_verifier_enabled
                    else None
                ),
            )
            result = execution.result
            repair_count += execution.repairs
            _log_live_sql_audit(
                ctx,
                scope="database_scope",
                target_id=catalog.id,
                connector_type=connector_type,
                sql=result.query,
                row_count=len(result.rows),
            )
            all_hits.extend(
                live_catalog_query_hits(
                    catalog=catalog,
                    profile=profile,
                    connector_type=connector_type,
                    sql=result.query,
                    rows=result.rows[:row_limit],
                    columns=result.columns,
                    group_path=_catalog_visible_group_path(catalog, scoped_user_context(ctx)),
                )
            )
        except QueryCancelled:
            raise
        except Exception as exc:
            failures.append(f"{catalog.id}:{type(exc).__name__}")
            continue

    if all_hits:
        return LiveSqlRetrievalResult(
            all_hits,
            "ai_assisted",
            f"scope=database_scope,live_sql_hits={len(all_hits)},catalogs={len(catalogs)},repairs={repair_count}",
        )
    if failures:
        return LiveSqlRetrievalResult([], "fallback", ",".join(failures[:5]))
    if attempted_scopes:
        return LiveSqlRetrievalResult([], "fallback", "no_live_rows")
    return LiveSqlRetrievalResult([], "skipped", "no_approved_connector_scope")


def live_catalog_query_hits(
    *,
    catalog: ConnectorSchemaCatalogRecord,
    profile: ConnectorProfileRecord,
    connector_type: str,
    sql: str,
    rows: list[dict[str, Any]],
    columns: list[str],
    group_path: str | None = None,
) -> list[SearchHit]:
    query_hash = hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]
    title = _catalog_title(catalog, profile)
    doc_id = f"connector-live-scope:{catalog.id}"
    row_count = len(rows)
    hit_group_path = group_path or catalog.group_path
    access_group_paths = schema_catalog_access_group_paths(catalog.group_path, catalog.catalog_json)
    hits: list[SearchHit] = []
    for index, row in enumerate(rows):
        fields = _structured_fields(row, columns)
        text = _catalog_row_text(title, connector_type, sql, row, row_count=row_count)
        chunk_id = f"{doc_id}:{query_hash}:{index}"
        payload = {
            "doc_id": doc_id,
            "doc_title": f"Live connector query: {title}",
            "chunk_id": chunk_id,
            "text": text,
            "group_path": hit_group_path,
            "acl_group_paths": access_group_paths,
            "clearance_level": catalog.clearance_level,
            "clearance_rank": clearance_rank(catalog.clearance_level),
            "is_current": True,
            "source_type": "connector_live_sql_database_scope",
            "connector_type": connector_type,
            "connector_profile_id": profile.id,
            "connector_profile_name": profile.name,
            "connector_schema_catalog_id": catalog.id,
            "live_sql_scope": "database_scope",
            "live_sql": sql,
            "live_sql_row_count": row_count,
            "structured_kind": "kv_record",
            "structured_field_names": [field["label"] for field in fields],
            "structured_fields": fields,
            "table_title": f"Live connector query: {title}",
            "table_row_index": index,
        }
        hits.append(SearchHit(point_id=chunk_id, score=1.0, payload=payload))
    return hits


def _should_run_live_sql(plan: RoutePlan | None, source_decision: object | None = None) -> bool:
    if plan and (plan.use_structured_query or plan.search_mode == "structured_first"):
        return True
    mode = str(getattr(source_decision, "resolved_mode", "") or "")
    return mode in {"db_only", "db_first", "hybrid"}


def _eligible_catalogs(
    ctx: QueryContext,
    catalogs: list[ConnectorSchemaCatalogRecord],
    *,
    limit: int,
) -> list[ConnectorSchemaCatalogRecord]:
    user = scoped_user_context(ctx)
    eligible: list[ConnectorSchemaCatalogRecord] = []
    for catalog in _current_schema_catalogs(catalogs):
        if catalog.status not in _ACTIVE_CATALOG_STATUSES:
            continue
        if str(catalog.connector_type) not in _SQL_CONNECTOR_TYPES:
            continue
        if _catalog_visible_group_path(catalog, user) is None:
            continue
        if clearance_rank(catalog.clearance_level) > clearance_rank(user.clearance_level):
            continue
        eligible.append(catalog)
        if len(eligible) >= limit:
            break
    return eligible


def _selected_source_allows(
    selected_source: tuple[str, str] | None,
    kind: str,
    record_id: str,
) -> bool:
    return selected_source is None or selected_source == (kind, record_id)


def _current_schema_catalogs(catalogs: list[ConnectorSchemaCatalogRecord]) -> list[ConnectorSchemaCatalogRecord]:
    by_profile: dict[str, ConnectorSchemaCatalogRecord] = {}
    for catalog in catalogs:
        if catalog.profile_id not in by_profile:
            by_profile[catalog.profile_id] = catalog
    return list(by_profile.values())


def _catalog_visible_group_path(catalog: ConnectorSchemaCatalogRecord, user) -> str | None:
    return schema_catalog_visible_group_path(catalog.group_path, catalog.catalog_json, user.group_paths)


def _run_with_sql_repair(
    *,
    ctx: QueryContext,
    scope: str,
    target_id: str,
    connector_type: str,
    max_repair_attempts: int,
    cancellation_token: object | None,
    generate_sql: Callable[[_RepairFeedback | None], str],
    validate_sql: Callable[[str], str],
    execute_sql: Callable[[str], ConnectorQueryResult],
    verify_result: Callable[[str, ConnectorQueryResult], _ResultVerification | None] | None = None,
) -> _LiveSqlExecution:
    feedback: _RepairFeedback | None = None
    last_error: Exception | None = None
    max_attempts = max(1, max_repair_attempts + 1)
    for attempt in range(1, max_attempts + 1):
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        generated_sql: str | None = None
        live_query: str | None = None
        try:
            generated_sql = generate_sql(feedback)
            live_query = validate_sql(generated_sql)
            result = execute_sql(live_query)
            if verify_result is not None:
                verification = verify_result(live_query, result)
                if verification is not None and not verification.accepted:
                    raise _LiveSqlResultVerificationError(_verification_error_message(verification))
            _log_live_sql_attempt(
                ctx,
                scope=scope,
                target_id=target_id,
                connector_type=connector_type,
                attempt=attempt,
                stage="execute",
                success=True,
                sql=live_query,
                error=None,
            )
            return _LiveSqlExecution(result=result, attempts=attempt, repairs=attempt - 1)
        except QueryCancelled:
            raise
        except Exception as exc:
            last_error = exc
            stage = _failed_stage(generated_sql=generated_sql, live_query=live_query, exc=exc)
            _log_live_sql_attempt(
                ctx,
                scope=scope,
                target_id=target_id,
                connector_type=connector_type,
                attempt=attempt,
                stage=stage,
                success=False,
                sql=live_query or generated_sql,
                error=exc,
            )
            if attempt >= max_attempts:
                raise
            feedback = _RepairFeedback(
                stage=stage,
                message=_sanitized_error(exc),
                previous_sql=_safe_sql_excerpt(live_query or generated_sql),
            )
    if last_error is not None:
        raise last_error
    raise RuntimeError("live SQL repair loop exited without a result")


def _failed_stage(*, generated_sql: str | None, live_query: str | None, exc: Exception) -> str:
    if generated_sql is None:
        return "generation"
    if isinstance(exc, _LiveSqlResultVerificationError):
        return "verification"
    if live_query is None or isinstance(exc, (SqlValidationError, ValueError)):
        return "validation"
    return "execution"


def _generate_catalog_live_sql(
    llm: object,
    *,
    question: str,
    catalog: ConnectorSchemaCatalogRecord,
    profile: ConnectorProfileRecord,
    connector_type: str,
    reasoning_model: str | None,
    row_limit: int,
    cancellation_token: object | None,
    repair_feedback: _RepairFeedback | None = None,
) -> str:
    generator = getattr(llm, "generate_json", None)
    if generator is None:
        raise RuntimeError("language client does not support JSON generation")
    raw = generator(
        prompt=_catalog_live_sql_prompt(
            question=question,
            catalog=catalog,
            profile=profile,
            connector_type=connector_type,
            row_limit=row_limit,
            repair_feedback=repair_feedback,
        ),
        model=reasoning_model,
        system="You generate safe read-only SQL for approved enterprise connector database scopes.",
        cancellation_token=cancellation_token,
    )
    payload = _load_json_object(str(raw))
    sql = payload.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("live SQL generation did not return sql")
    return sql.strip()


def _catalog_live_sql_prompt(
    *,
    question: str,
    catalog: ConnectorSchemaCatalogRecord,
    profile: ConnectorProfileRecord,
    connector_type: str,
    row_limit: int,
    repair_feedback: _RepairFeedback | None = None,
) -> str:
    schema_context = approved_schema_prompt(catalog.catalog_json, question=question)
    prompt = (
        "Generate one read-only SQL SELECT statement to answer the user question from an approved database schema catalog. "
        "Return only JSON with keys sql and reasoning. "
        "Use only approved tables, approved columns, and approved joins listed below. "
        "Never read system schemas or unlisted tables. Do not use comments, multiple statements, stored procedures, mutations, or wildcard SELECT *. "
        "Qualify column names when more than one table is referenced. Include a LIMIT/TOP when the answer returns rows; aggregates may return a single row.\n\n"
        f"Connector profile: {profile.name}\n"
        f"Connector type: {connector_type}\n"
        f"Approved scope status: {catalog.status}\n"
        f"Maximum rows: {row_limit}\n\n"
        f"{schema_context}\n\n"
        f"User question: {question}"
    )
    repair_block = _repair_prompt_block(repair_feedback)
    return f"{prompt}\n\n{repair_block}" if repair_block else prompt


def _verify_live_sql_result(
    llm: object,
    *,
    question: str,
    connector_type: str,
    scope: str,
    scope_name: str,
    sql: str,
    result: ConnectorQueryResult,
    row_limit: int,
    sample_rows: int,
    reasoning_model: str | None,
    cancellation_token: object | None,
) -> _ResultVerification:
    generator = getattr(llm, "generate_json", None)
    if generator is None:
        return _ResultVerification(True, "verifier_unavailable")
    try:
        raw = generator(
            prompt=_live_sql_result_verifier_prompt(
                question=question,
                connector_type=connector_type,
                scope=scope,
                scope_name=scope_name,
                sql=sql,
                result=result,
                row_limit=row_limit,
                sample_rows=sample_rows,
            ),
            model=reasoning_model,
            system="You verify whether safe live SQL result shapes answer user questions.",
            cancellation_token=cancellation_token,
        )
        payload = _load_json_object(str(raw))
    except QueryCancelled:
        raise
    except Exception as exc:
        _LOGGER.warning(
            "connector_live_sql.result_verifier_unavailable",
            extra={"connector_live_sql_verifier_error": {"error_type": type(exc).__name__}},
        )
        return _ResultVerification(True, "verifier_unavailable")
    verdict = str(payload.get("verdict") or "").strip().lower()
    reason = _compact_text(payload.get("reason") or "", max_chars=500)
    instruction = _compact_text(payload.get("repair_instruction") or "", max_chars=500)
    if verdict in {"repair", "revise", "reject", "retry"}:
        return _ResultVerification(False, reason or "Result shape does not answer the question.", instruction)
    return _ResultVerification(True, reason or "accepted")


def _live_sql_result_verifier_prompt(
    *,
    question: str,
    connector_type: str,
    scope: str,
    scope_name: str,
    sql: str,
    result: ConnectorQueryResult,
    row_limit: int,
    sample_rows: int,
) -> str:
    sample = _compact_rows(result.rows[:sample_rows])
    payload = {
        "question": question,
        "connector_type": connector_type,
        "scope": scope,
        "scope_name": scope_name,
        "row_limit": row_limit,
        "sql": sql,
        "columns": result.columns,
        "row_count": len(result.rows),
        "sample_rows": sample,
    }
    return (
        "Verify whether this already-safe live SQL result shape is likely to answer the user question. "
        "Do not evaluate security or ask for broader access; the SQL validator handles access. "
        "Return only JSON with keys verdict, reason, and repair_instruction. "
        'Use verdict "accept" when the selected columns, aggregation grain, filters, sort, and row count are adequate. '
        'Use verdict "repair" only when the result shape is clearly wrong, such as missing requested metrics, returning detail rows for an aggregate question, '
        "aggregating when the user asked for a list, missing latest/top ordering, or omitting requested grouping/filter columns. "
        "Empty rows can be acceptable when the SQL shape matches the question. "
        "When repairing, give a concise SQL-generation instruction that still uses only the approved scope.\n\n"
        f"{json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)}"
    )


def _catalog_row_limit(config: Settings, catalog: ConnectorSchemaCatalogRecord) -> int:
    configured = max(1, int(getattr(config, "connector_live_sql_max_rows", 100)))
    try:
        catalog_limit = int(catalog.catalog_json.get("row_limit") or configured)
    except (TypeError, ValueError):
        catalog_limit = configured
    return max(1, min(configured, catalog_limit))


def _max_repair_attempts(config: Settings) -> int:
    try:
        configured = int(getattr(config, "connector_live_sql_max_repair_attempts", 2))
    except (TypeError, ValueError):
        configured = 2
    return max(0, min(configured, 5))


def _verifier_sample_rows(config: Settings) -> int:
    try:
        configured = int(getattr(config, "connector_live_sql_verifier_sample_rows", 5))
    except (TypeError, ValueError):
        configured = 5
    return max(0, min(configured, 20))


def _structured_fields(row: dict[str, Any], columns: list[str]) -> list[dict[str, str]]:
    ordered = columns or list(row)
    fields: list[dict[str, str]] = []
    seen: set[str] = set()
    for key in [*ordered, *[key for key in row if key not in ordered]]:
        if key in seen:
            continue
        seen.add(key)
        value = row.get(key)
        fields.append({"label": str(key), "value": _scalar(value)})
    return fields


def _catalog_title(catalog: ConnectorSchemaCatalogRecord, profile: ConnectorProfileRecord) -> str:
    name = catalog.catalog_json.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return f"{profile.name} approved database scope"


def _catalog_row_text(
    title: str,
    connector_type: str,
    sql: str,
    row: dict[str, Any],
    *,
    row_count: int,
) -> str:
    lines = [
        f"Live connector query: {title}",
        f"Connector type: {connector_type}",
        f"Rows returned: {row_count}",
    ]
    lines.extend(f"{key}: {_scalar(value)}" for key, value in row.items())
    lines.append(f"SQL: {sql}")
    return "\n".join(lines)


def _scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return " ".join(str(value).split())


def _repair_prompt_block(feedback: _RepairFeedback | None) -> str:
    if feedback is None:
        return ""
    lines = [
        "Repair the previous SQL attempt.",
        f"Previous failure stage: {feedback.stage}.",
        f"Sanitized error: {feedback.message}",
        "Return a corrected JSON object with a single sql string. Do not explain outside JSON.",
        "If the error names a table or column, replace it with an exact approved table or column from the schema context.",
        "Do not relax any safety rule: use only the approved scope, approved columns, approved joins, one SELECT statement, and the configured row limit.",
    ]
    if feedback.previous_sql:
        lines.append(f"Previous SQL attempt:\n{feedback.previous_sql}")
    return "\n".join(lines)


def _verification_error_message(verification: _ResultVerification) -> str:
    if verification.repair_instruction:
        return f"{verification.reason} Repair instruction: {verification.repair_instruction}"
    return verification.reason


def _safe_sql_excerpt(sql: str | None, *, max_chars: int = 800) -> str | None:
    if not sql:
        return None
    text = " ".join(str(sql).split())
    return text[:max_chars]


def _compact_rows(rows: list[dict[str, Any]], *, max_value_chars: int = 160) -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    for row in rows:
        item: dict[str, str] = {}
        for key, value in row.items():
            item[str(key)] = _compact_text(_scalar(value), max_chars=max_value_chars)
        compact.append(item)
    return compact


def _compact_text(value: object, *, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "..."
    return text


def _sanitized_error(exc: Exception, *, max_chars: int = 500) -> str:
    text = " ".join(str(exc).split())
    text = re.sub(r"(?i)(password|pwd)\s*=\s*[^;\s]+", r"\1=[redacted]", text)
    text = re.sub(r"(?i)(password|pwd)['\"]?\s*:\s*['\"][^'\"]+['\"]", r"\1: [redacted]", text)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "..."
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _log_live_sql_attempt(
    ctx: QueryContext,
    *,
    scope: str,
    target_id: str,
    connector_type: str,
    attempt: int,
    stage: str,
    success: bool,
    sql: str | None,
    error: Exception | None,
) -> None:
    payload: dict[str, object] = {
        "trace_id": ctx["trace_id"],
        "user_id": ctx["user"].user_id,
        "scope": scope,
        "target_id": target_id,
        "connector_type": connector_type,
        "attempt": attempt,
        "stage": stage,
        "success": success,
    }
    if sql:
        payload["sql_hash"] = hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]
    if error is not None:
        payload["error_type"] = type(error).__name__
    log = _LOGGER.info if success else _LOGGER.warning
    log("connector_live_sql.attempt", extra={"connector_live_sql_attempt": payload})


def _log_live_sql_audit(
    ctx: QueryContext,
    *,
    scope: str,
    target_id: str,
    connector_type: str,
    sql: str,
    row_count: int,
) -> None:
    _LOGGER.info(
        "connector_live_sql.executed",
        extra={
            "connector_live_sql": {
                "trace_id": ctx["trace_id"],
                "user_id": ctx["user"].user_id,
                "scope": scope,
                "target_id": target_id,
                "connector_type": connector_type,
                "sql_hash": hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16],
                "row_count": row_count,
            }
        },
    )


def _load_json_object(raw: str) -> dict[str, object]:
    text = raw.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("live SQL response did not contain JSON") from None
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("live SQL response was not a JSON object")
    return value
