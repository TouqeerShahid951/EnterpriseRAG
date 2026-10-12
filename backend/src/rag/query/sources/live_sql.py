"""Live SQL retrieval over approved connector database scopes."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import hashlib
import json
import logging
import re
from typing import Any, Literal

from rag.connectors.crypto import decrypt_secret, keyring_from_settings
from rag.connectors.models import ConnectorProfileRecord, ConnectorQueryResult, ConnectorSchemaCatalogRecord
from rag.connectors.repositories import ConnectorProfileRepository, get_connector_profile_repository
from rag.connectors.registry import ConnectorRegistry, default_connector_registry
from rag.connectors.catalog.schema_catalog import approved_schema_prompt, schema_catalog_access_group_paths, schema_catalog_visible_group_path
from rag.connectors.sql_safety import SqlValidationError, validate_live_sql_for_approved_catalog
from rag.core.config import Settings
from rag.ingestion.folders.models import FolderScheduleRepository
from rag.shared.contracts.clearance import clearance_rank
from rag.query.cancellation import QueryCancelled, cancellation_token_from_context
from rag.query.qdrant import SearchHit
from rag.query.routing.routing_models import RoutePlan
from rag.query.routing.evidence_planning import (
    evidence_queries,
    required_evidence_assignments_for_query,
)
from rag.query.sources.source_catalog import query_source_id_for_catalog
from rag.query.sources.source_resolution import selected_source_targets
from rag.query.state import QueryContext, scoped_user_context, timed_retrieval_phase

_ACTIVE_CATALOG_STATUSES = {"approved"}
_SQL_CONNECTOR_TYPES = {"postgres", "sql_server", "fake"}
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveSqlRetrievalResult:
    hits: list[SearchHit]
    mode: str
    detail: str
    failures: tuple["LiveSqlFailure", ...] = ()


LiveSqlFailureStage = Literal["selection", "generation", "validation", "execution"]


@dataclass(frozen=True)
class LiveSqlFailure:
    stage: LiveSqlFailureStage
    code: str
    retryable: bool
    source_id: str | None
    message: str


@dataclass(frozen=True)
class _GeneratedLiveSql:
    sql: str
    parameters: dict[str, object]


@dataclass(frozen=True)
class _CatalogAttempt:
    hits: list[SearchHit]
    failure: LiveSqlFailure | None = None
    attempted: bool = False
    phase_timings_ms: dict[str, int] = field(default_factory=dict)


class _LiveSqlStageError(RuntimeError):
    def __init__(self, stage: LiveSqlFailureStage) -> None:
        super().__init__(stage)
        self.stage = stage


def retrieve_live_sql_hits(
    ctx: QueryContext,
    *,
    config: Settings,
    llm: object,
    reasoning_model: str | None = None,
    sql_generation_model: str | None = None,
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
        return LiveSqlRetrievalResult([], "skipped", "live_sql_not_selected")

    _ = schedule_repo
    connector_profile_repo = connector_profile_repo or get_connector_profile_repository()
    connector_registry = connector_registry or default_connector_registry()
    token = cancellation_token_from_context(ctx)
    question = plan.resolved_query if plan is not None else ctx["request"].query
    all_hits: list[SearchHit] = []
    failures: list[LiveSqlFailure] = []
    attempted_scopes = 0
    available_catalogs = connector_profile_repo.list_schema_catalogs()
    eligible_catalogs = _eligible_catalogs(
        ctx,
        available_catalogs,
        limit=max(1, len(available_catalogs)),
    )
    if not eligible_catalogs:
        return LiveSqlRetrievalResult([], "skipped", "no_approved_connector_scope")
    selected_sources = selected_source_targets(ctx.get("source_decision"))  # type: ignore[arg-type]
    if not selected_sources:
        if len(eligible_catalogs) != 1:
            return LiveSqlRetrievalResult([], "fallback", "database_source_unresolved")
        catalogs = eligible_catalogs
    elif all(kind == "catalog" for kind, _target_id in selected_sources):
        selected_catalog_ids = {target_id for _kind, target_id in selected_sources}
        catalogs = [
            catalog
            for catalog in eligible_catalogs
            if catalog.id in selected_catalog_ids
        ]
    else:
        catalogs = []
    if not catalogs or len(catalogs) > 3:
        source_id = str(getattr(ctx.get("source_decision"), "query_source_id", "") or "")
        failure = LiveSqlFailure(
            stage="selection",
            code="selected_database_unavailable",
            retryable=False,
            source_id=source_id or None,
            message="The selected database source is unavailable.",
        )
        return LiveSqlRetrievalResult(
            [], "fallback", failure.code, failures=(failure,)
        )
    def retrieve_catalog(catalog: ConnectorSchemaCatalogRecord) -> _CatalogAttempt:
        return _retrieve_catalog(
            ctx=ctx,
            catalog=catalog,
            question=question,
            plan=plan,
            config=config,
            llm=llm,
            reasoning_model=reasoning_model,
            sql_generation_model=sql_generation_model,
            connector_profile_repo=connector_profile_repo,
            connector_registry=connector_registry,
            cancellation_token=token,
        )

    if len(catalogs) == 1:
        attempts = [retrieve_catalog(catalogs[0])]
    else:
        # ponytail: request-local bounded fan-out; centralize only if measured load
        # shows that a shared executor materially reduces thread pressure.
        with ThreadPoolExecutor(
            max_workers=len(catalogs), thread_name_prefix="rag-connector"
        ) as executor:
            attempts = list(executor.map(retrieve_catalog, catalogs))
    for attempt in attempts:
        all_hits.extend(attempt.hits)
        attempted_scopes += int(attempt.attempted)
        phase_timings = ctx.setdefault("retrieval_phase_timings_ms", {})
        for phase, duration_ms in attempt.phase_timings_ms.items():
            phase_timings[phase] = phase_timings.get(phase, 0) + duration_ms
        if attempt.failure:
            failures.append(attempt.failure)

    if all_hits:
        return LiveSqlRetrievalResult(
            all_hits,
            "ai_assisted",
            f"scope=database_scope,live_sql_hits={len(all_hits)},catalogs={','.join(catalog.id for catalog in catalogs)}",
            failures=tuple(failures),
        )
    if failures:
        return LiveSqlRetrievalResult(
            [],
            "fallback",
            ",".join(
                f"{failure.source_id or 'database'}:{failure.code}"
                for failure in failures[:5]
            ),
            failures=tuple(failures),
        )
    if attempted_scopes:
        return LiveSqlRetrievalResult([], "fallback", "no_live_rows")
    return LiveSqlRetrievalResult([], "skipped", "no_approved_connector_scope")


def _retrieve_catalog(
    *,
    ctx: QueryContext,
    catalog: ConnectorSchemaCatalogRecord,
    question: str,
    plan: RoutePlan | None,
    config: Settings,
    llm: object,
    reasoning_model: str | None,
    sql_generation_model: str | None,
    connector_profile_repo: ConnectorProfileRepository,
    connector_registry: ConnectorRegistry,
    cancellation_token: object | None,
) -> _CatalogAttempt:
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    profile = connector_profile_repo.get_profile(catalog.profile_id)
    if profile is None:
        return _CatalogAttempt(
            [],
            _catalog_failure(
                catalog,
                None,
                stage="execution",
                code="connector_profile_unavailable",
                retryable=False,
            ),
        )
    connector_type = str(profile.connector_type)
    if connector_type not in _SQL_CONNECTOR_TYPES:
        return _CatalogAttempt(
            [],
            _catalog_failure(
                catalog,
                profile,
                stage="execution",
                code="connector_type_unsupported",
                retryable=False,
            ),
        )
    row_limit = _catalog_row_limit(config, catalog)
    source_id = query_source_id_for_catalog(catalog.id)
    assigned_queries = evidence_queries(
        plan.evidence_plan if plan is not None else None,
        "connector_query",
        source_id=source_id,
    )
    catalog_question = "\n".join(assigned_queries) or question
    assignments = tuple(
        dict.fromkeys(
            assignment
            for assigned_query in assigned_queries or (question,)
            for assignment in required_evidence_assignments_for_query(
                plan.evidence_plan if plan is not None else None,
                assigned_query,
                "connector_query",
                source_ids={source_id},
            )
        )
    )
    need_ids = tuple(dict.fromkeys(item[0] for item in assignments))
    branch_ctx = ctx.copy()
    branch_ctx["retrieval_phase_timings_ms"] = {}
    try:
        connector = connector_registry.get(connector_type)
        secrets = decrypt_secret(
            profile.encrypted_secrets,
            keyring_from_settings(
                config.connector_secrets_key, config.connector_secrets_key_ring
            ),
        )
        primary_sql_model = sql_generation_model or reasoning_model
        def generate_reasoned_sql() -> _GeneratedLiveSql:
            return _generate_catalog_live_sql(
                llm,
                question=catalog_question,
                catalog=catalog,
                profile=profile,
                connector_type=connector_type,
                sql_generation_model=reasoning_model,
                row_limit=row_limit,
                cancellation_token=cancellation_token,
                allow_verified_query=False,
            )
        repair_sql = (
            generate_reasoned_sql
            if reasoning_model and primary_sql_model != reasoning_model
            else None
        )
        result = _execute_live_sql(
            ctx=branch_ctx,
            scope="database_scope",
            target_id=catalog.id,
            connector_type=connector_type,
            cancellation_token=cancellation_token,
            generate_sql=lambda: _generate_catalog_live_sql(
                llm,
                question=catalog_question,
                catalog=catalog,
                profile=profile,
                connector_type=connector_type,
                sql_generation_model=primary_sql_model,
                row_limit=row_limit,
                cancellation_token=cancellation_token,
            ),
            repair_sql=repair_sql,
            validate_sql=lambda generated_sql: validate_live_sql_for_approved_catalog(
                generated_sql,
                catalog_json=catalog.catalog_json,
                connector_type=connector_type,
                row_limit=row_limit,
            ),
            execute_sql=lambda live_query, parameters: _execute_connector_query(
                connector,
                config=profile.public_config,
                secrets=secrets,
                query=live_query,
                parameters=parameters,
                row_limit=row_limit,
                timeout_seconds=max(
                    1,
                    int(getattr(config, "connector_live_sql_timeout_seconds", 15)),
                ),
            ),
        )
        _log_live_sql_audit(
            branch_ctx,
            scope="database_scope",
            target_id=catalog.id,
            connector_type=connector_type,
            sql=result.query,
            row_count=len(result.rows),
        )
        return _CatalogAttempt(
            live_catalog_query_hits(
                catalog=catalog,
                profile=profile,
                connector_type=connector_type,
                sql=result.query,
                rows=result.rows[:row_limit],
                columns=result.columns,
                group_path=_catalog_visible_group_path(
                    catalog, scoped_user_context(ctx)
                ),
                evidence_need_ids=need_ids,
                required_evidence_assignments=assignments,
            ),
            attempted=True,
            phase_timings_ms=dict(
                branch_ctx.get("retrieval_phase_timings_ms", {})
            ),
        )
    except QueryCancelled:
        raise
    except _LiveSqlStageError as exc:
        return _CatalogAttempt(
            [],
            _catalog_failure(catalog, profile, stage=exc.stage),
            attempted=True,
            phase_timings_ms=dict(
                branch_ctx.get("retrieval_phase_timings_ms", {})
            ),
        )
    except Exception:
        return _CatalogAttempt(
            [],
            _catalog_failure(
                catalog,
                profile,
                stage="execution",
                code="connector_setup_failed",
                retryable=False,
            ),
            attempted=True,
            phase_timings_ms=dict(
                branch_ctx.get("retrieval_phase_timings_ms", {})
            ),
        )


def live_catalog_query_hits(
    *,
    catalog: ConnectorSchemaCatalogRecord,
    profile: ConnectorProfileRecord,
    connector_type: str,
    sql: str,
    rows: list[dict[str, Any]],
    columns: list[str],
    group_path: str | None = None,
    evidence_need_ids: tuple[str, ...] = (),
    required_evidence_assignments: tuple[tuple[str, str, str], ...] = (),
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
        lineage_id = _evidence_lineage_id(row, catalog.catalog_json)
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
            "quote_texts": ["\n".join([f"Rows returned: {row_count}", *(f"{key}: {_scalar(value)}" for key, value in row.items())])],
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
            "retrieved_via": "sql",
            **(
                {"_evidence_need_ids": list(evidence_need_ids)}
                if evidence_need_ids
                else {}
            ),
            **(
                {
                    "_required_evidence_assignments": [
                        list(item) for item in required_evidence_assignments
                    ]
                }
                if required_evidence_assignments
                else {}
            ),
            **(
                {"evidence_lineage_id": lineage_id}
                if lineage_id is not None
                else {}
            ),
        }
        hits.append(SearchHit(point_id=chunk_id, score=1.0, payload=payload))
    return hits


def _evidence_lineage_id(
    row: dict[str, Any], catalog_json: dict[str, Any]
) -> str | None:
    provenance = catalog_json.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    raw_fields = provenance.get("lineage_fields")
    fields = (
        [str(value) for value in raw_fields if str(value).strip()]
        if isinstance(raw_fields, list)
        else []
    )
    if not fields:
        field = str(
            provenance.get("lineage_field")
            or catalog_json.get("evidence_lineage_field")
            or ""
        ).strip()
        fields = [field] if field else []
    values = [str(row[field]).strip() for field in fields if row.get(field) not in (None, "")]
    if len(values) != len(fields) or not values:
        return None
    return ":".join(values)[:500]


def _should_run_live_sql(plan: RoutePlan | None, source_decision: object | None = None) -> bool:
    mode = str(getattr(source_decision, "resolved_mode", "") or "")
    if mode == "corpus_only":
        return False
    if bool(getattr(source_decision, "explicit", False)) and mode in {
        "db_only",
        "hybrid",
    }:
        return True
    return plan is not None and "live_sql" in plan.capabilities


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


def _current_schema_catalogs(catalogs: list[ConnectorSchemaCatalogRecord]) -> list[ConnectorSchemaCatalogRecord]:
    by_profile: dict[str, ConnectorSchemaCatalogRecord] = {}
    for catalog in catalogs:
        if catalog.profile_id not in by_profile:
            by_profile[catalog.profile_id] = catalog
    return list(by_profile.values())


def _catalog_visible_group_path(catalog: ConnectorSchemaCatalogRecord, user) -> str | None:
    return schema_catalog_visible_group_path(catalog.group_path, catalog.catalog_json, user.group_paths)


def _execute_live_sql(
    *,
    ctx: QueryContext,
    scope: str,
    target_id: str,
    connector_type: str,
    cancellation_token: object | None,
    generate_sql: Callable[[], _GeneratedLiveSql],
    repair_sql: Callable[[], _GeneratedLiveSql] | None,
    validate_sql: Callable[[str], str],
    execute_sql: Callable[[str, dict[str, object]], ConnectorQueryResult],
) -> ConnectorQueryResult:
    generators = (generate_sql,) if repair_sql is None else (generate_sql, repair_sql)
    for attempt, generator in enumerate(generators, start=1):
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        generated: _GeneratedLiveSql | None = None
        live_query: str | None = None
        try:
            with timed_retrieval_phase(ctx, "sql_generation"):
                generated = generator()
            with timed_retrieval_phase(ctx, "sql_validation"):
                live_query = validate_sql(generated.sql)
        except QueryCancelled:
            raise
        except Exception as exc:
            stage = _failed_stage(
                generated_sql=generated.sql if generated is not None else None,
                live_query=live_query,
                exc=exc,
            )
            _log_live_sql_attempt(
                ctx,
                scope=scope,
                target_id=target_id,
                connector_type=connector_type,
                attempt=attempt,
                stage=stage,
                success=False,
                sql=generated.sql if generated is not None else None,
                error=exc,
            )
            if attempt < len(generators):
                continue
            raise _LiveSqlStageError(stage) from exc
        try:
            with timed_retrieval_phase(ctx, "sql_execution"):
                result = execute_sql(live_query, generated.parameters)
        except QueryCancelled:
            raise
        except Exception as exc:
            _log_live_sql_attempt(
                ctx,
                scope=scope,
                target_id=target_id,
                connector_type=connector_type,
                attempt=attempt,
                stage="execution",
                success=False,
                sql=live_query,
                error=exc,
            )
            raise _LiveSqlStageError("execution") from exc
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
        return result
    raise RuntimeError("live SQL generation exhausted without a result")


def _failed_stage(
    *, generated_sql: str | None, live_query: str | None, exc: Exception
) -> LiveSqlFailureStage:
    if generated_sql is None:
        return "generation"
    if live_query is None or isinstance(exc, (SqlValidationError, ValueError)):
        return "validation"
    return "execution"


def _catalog_failure(
    catalog: ConnectorSchemaCatalogRecord,
    profile: ConnectorProfileRecord | None,
    *,
    stage: LiveSqlFailureStage,
    code: str | None = None,
    retryable: bool | None = None,
) -> LiveSqlFailure:
    title = _catalog_title(catalog, profile) if profile is not None else str(
        catalog.catalog_json.get("name") or catalog.id
    )
    defaults = {
        "generation": (
            "sql_generation_unavailable",
            True,
            f"SQL generation is unavailable for {title}.",
        ),
        "validation": (
            "sql_validation_failed",
            False,
            f"Generated SQL could not be safely validated for {title}.",
        ),
        "execution": (
            "sql_execution_failed",
            True,
            f"Database query execution is unavailable for {title}.",
        ),
        "selection": (
            "selected_database_unavailable",
            False,
            "The selected database source is unavailable.",
        ),
    }
    default_code, default_retryable, message = defaults[stage]
    return LiveSqlFailure(
        stage=stage,
        code=code or default_code,
        retryable=default_retryable if retryable is None else retryable,
        source_id=query_source_id_for_catalog(catalog.id),
        message=message,
    )


def _generate_catalog_live_sql(
    llm: object,
    *,
    question: str,
    catalog: ConnectorSchemaCatalogRecord,
    profile: ConnectorProfileRecord,
    connector_type: str,
    sql_generation_model: str | None,
    row_limit: int,
    cancellation_token: object | None,
    allow_verified_query: bool = True,
) -> _GeneratedLiveSql:
    if allow_verified_query:
        verified = _exact_verified_query(catalog.catalog_json, question)
        if verified is not None:
            return verified
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
        ),
        model=sql_generation_model,
        system="You generate safe read-only SQL for approved enterprise connector database scopes.",
        cancellation_token=cancellation_token,
    )
    payload = _load_json_object(str(raw))
    sql = payload.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("live SQL generation did not return sql")
    parameters = _live_sql_parameters(payload.get("parameters"))
    _validate_parameter_placeholders(sql, parameters)
    return _GeneratedLiveSql(sql=sql.strip(), parameters=parameters)


def _exact_verified_query(
    catalog_json: dict[str, Any], question: str
) -> _GeneratedLiveSql | None:
    normalized_question = " ".join(question.lower().split())
    for item in catalog_json.get("verified_queries") or []:
        if not isinstance(item, dict):
            continue
        candidate = " ".join(str(item.get("question") or "").lower().split())
        sql = str(item.get("sql") or "").strip()
        if not candidate or candidate != normalized_question or not sql:
            continue
        parameters = _live_sql_parameters(item.get("parameters"))
        _validate_parameter_placeholders(sql, parameters)
        return _GeneratedLiveSql(sql=sql, parameters=parameters)
    return None


def _catalog_live_sql_prompt(
    *,
    question: str,
    catalog: ConnectorSchemaCatalogRecord,
    profile: ConnectorProfileRecord,
    connector_type: str,
    row_limit: int,
) -> str:
    schema_context = approved_schema_prompt(catalog.catalog_json, question=question)
    prompt = (
        "Generate one read-only SQL SELECT statement to answer the user question from an approved database schema catalog. "
        "Return only JSON with keys sql, parameters, and reasoning. "
        "Use only approved tables, approved columns, and approved joins listed below. "
        "Never read system schemas or unlisted tables. Do not use comments, multiple statements, stored procedures, mutations, or wildcard SELECT *. "
        "Qualify column names when more than one table is referenced. Use named :parameter placeholders for user-provided filter values and put their scalar values in the parameters object. "
        "Include a LIMIT/TOP when the answer returns rows; aggregates may return a single row.\n\n"
        f"Connector profile: {profile.name}\n"
        f"Connector type: {connector_type}\n"
        f"Approved scope status: {catalog.status}\n"
        f"Maximum rows: {row_limit}\n\n"
        f"{schema_context}\n\n"
        f"User question: {question}"
    )
    return prompt


def _live_sql_parameters(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 20:
        raise ValueError("live SQL parameters must be an object with at most 20 values")
    parameters: dict[str, object] = {}
    for raw_name, item in value.items():
        name = str(raw_name)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
            raise ValueError("live SQL parameter name is invalid")
        if item is not None and not isinstance(item, (str, int, float, bool)):
            raise ValueError("live SQL parameter value must be scalar")
        if isinstance(item, str) and len(item) > 1000:
            raise ValueError("live SQL parameter value is too long")
        parameters[name] = item
    return parameters


def _validate_parameter_placeholders(
    sql: str, parameters: dict[str, object]
) -> None:
    names = set(re.findall(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", sql))
    if names != set(parameters):
        raise ValueError("live SQL placeholders and parameters do not match")


def _execute_connector_query(
    connector: object,
    *,
    config: dict[str, Any],
    secrets: dict[str, Any],
    query: str,
    parameters: dict[str, object],
    row_limit: int,
    timeout_seconds: int,
) -> ConnectorQueryResult:
    execute_query = getattr(connector, "execute_query")
    kwargs = {
        "config": config,
        "secrets": secrets,
        "query": query,
        "row_limit": row_limit,
        "timeout_seconds": timeout_seconds,
    }
    if parameters:
        kwargs["parameters"] = parameters
    return execute_query(**kwargs)


def _catalog_row_limit(config: Settings, catalog: ConnectorSchemaCatalogRecord) -> int:
    configured = max(1, int(getattr(config, "connector_live_sql_max_rows", 100)))
    try:
        catalog_limit = int(catalog.catalog_json.get("row_limit") or configured)
    except (TypeError, ValueError):
        catalog_limit = configured
    return max(1, min(configured, catalog_limit))


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
