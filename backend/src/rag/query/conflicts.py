"""Agent 4 claim extraction and conflict lookup helpers."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from ..auth.abac import build_abac_filter
from ..auth.document_access import can_read_group_path
from ..shared.contracts.clearance import can_access_clearance
from ..shared.contracts.evidence import ConflictPair, SourceAnchor
from ..schemas.internal import ClaimRecord
from .cancellation import call_with_optional_cancellation, cancellation_token_from_context
from .qdrant import QdrantClient, SearchHit
from .state import QueryContext, scoped_user_context, visible_group_paths
from .sources import source_from_hit

_DISAGREEMENT_FIELDS = {
    "status",
    "state",
    "priority",
    "severity",
    "stage",
    "owner",
    "assignee",
    "amount",
    "total",
    "count",
}


class ConflictChecker(Protocol):
    def check_conflicts(
        self,
        claims: list[ClaimRecord],
        *,
        visible_group_paths: Sequence[str] | None = None,
    ) -> list[ConflictPair]: ...


def apply_conflict_detection(ctx: QueryContext, checker: ConflictChecker, qdrant: QdrantClient) -> QueryContext:
    cancellation_token = cancellation_token_from_context(ctx)
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    claims = claims_from_hits(ctx["retrieved_hits"])
    group_paths = visible_group_paths(ctx)
    conflicts = (
        checker.check_conflicts(claims, visible_group_paths=group_paths)
        if claims
        else []
    )
    conflicts = _visible_conflicts(conflicts, group_paths, scoped_user_context(ctx).clearance_level)
    conflicts = _resolve_original_sources(ctx, conflicts, qdrant)
    ctx["conflict_pairs"] = conflicts
    ctx["conflict_flag"] = bool(conflicts)
    return ctx


def apply_hybrid_disagreement_detection(ctx: QueryContext) -> QueryContext:
    decision = ctx.get("source_decision")
    if str(getattr(decision, "resolved_mode", "") or "") != "hybrid":
        return ctx
    if ctx["conflict_flag"]:
        return ctx
    db_hits = [hit for hit in ctx["retrieved_hits"] if _is_live_db_hit(hit)]
    doc_hits = [hit for hit in ctx["retrieved_hits"] if not _is_live_db_hit(hit)]
    if not db_hits or not doc_hits:
        return ctx
    conflicts: list[ConflictPair] = []
    for db_hit in db_hits:
        for label, db_value in _db_fields(db_hit):
            if _normalized_value(db_value) == "":
                continue
            for doc_hit in doc_hits:
                doc_value = _document_field_value(doc_hit, label)
                if not doc_value or _values_agree(db_value, doc_value):
                    continue
                source_a = source_from_hit(db_hit, query=ctx["request"].query)
                source_b = source_from_hit(doc_hit, query=ctx["request"].query)
                conflicts.append(
                    ConflictPair(
                        claim_a_id=f"{db_hit.point_id}:{label}",
                        claim_b_id=f"{doc_hit.point_id}:{label}",
                        doc_a_id=str(db_hit.payload.get("doc_id", db_hit.point_id)),
                        doc_b_id=str(doc_hit.payload.get("doc_id", doc_hit.point_id)),
                        chunk_a_id=str(db_hit.payload.get("chunk_id", db_hit.point_id)),
                        chunk_b_id=str(doc_hit.payload.get("chunk_id", doc_hit.point_id)),
                        entity=str(db_hit.payload.get("doc_title") or db_hit.payload.get("table_title") or "Live DB"),
                        attribute=label,
                        value_a=db_value,
                        value_b=doc_value,
                        source_a=source_a,
                        source_b=source_b,
                    )
                )
                break
            if conflicts:
                break
        if conflicts:
            break
    if conflicts:
        ctx["conflict_pairs"] = conflicts
        ctx["conflict_flag"] = True
    return ctx


def claims_from_hits(hits: list[SearchHit]) -> list[ClaimRecord]:
    claims: list[ClaimRecord] = []
    for hit in hits:
        raw_claims = hit.payload.get("claims")
        if isinstance(raw_claims, list):
            for raw_claim in raw_claims:
                if isinstance(raw_claim, dict):
                    claim = _claim_from_payload(hit, raw_claim)
                    if claim is not None:
                        claims.append(claim)
        raw_claim_ids = hit.payload.get("claim_ids")
        if isinstance(raw_claim_ids, list):
            for claim_id in raw_claim_ids:
                claim_text = _text(claim_id)
                if claim_text:
                    claims.append(
                        ClaimRecord(
                            id=claim_text,
                            doc_id=str(hit.payload.get("doc_id", "")),
                            chunk_id=str(hit.payload.get("chunk_id", hit.point_id)),
                            entity="",
                            attribute="",
                            value="",
                        )
                    )
    return claims


def _visible_conflicts(conflicts: list[ConflictPair], group_paths: Sequence[str], clearance_level: str) -> list[ConflictPair]:
    return [
        conflict
        for conflict in conflicts
        if can_read_group_path(group_paths, conflict.source_a.group_path)
        and can_read_group_path(group_paths, conflict.source_b.group_path)
        and can_access_clearance(clearance_level, conflict.source_a.clearance_level)
        and can_access_clearance(clearance_level, conflict.source_b.clearance_level)
    ]


def _resolve_original_sources(
    ctx: QueryContext,
    conflicts: list[ConflictPair],
    qdrant: QdrantClient,
) -> list[ConflictPair]:
    if not conflicts:
        return []
    hits = {_hit_key(hit): hit for hit in ctx["retrieved_hits"]}
    required = {
        (conflict.doc_a_id, conflict.chunk_a_id)
        for conflict in conflicts
    } | {
        (conflict.doc_b_id, conflict.chunk_b_id)
        for conflict in conflicts
    }
    missing = sorted(required - hits.keys())
    if missing:
        retrieved = call_with_optional_cancellation(
            qdrant.retrieve_chunks,
            cancellation_token_from_context(ctx),
            missing,
            qdrant_filter=build_abac_filter(scoped_user_context(ctx), is_current_only=ctx["is_current_only"]),
        )
        hits.update({_hit_key(hit): hit for hit in retrieved})

    resolved: list[ConflictPair] = []
    for conflict in conflicts:
        source_a = _source_for_key(hits, (conflict.doc_a_id, conflict.chunk_a_id), ctx["request"].query)
        source_b = _source_for_key(hits, (conflict.doc_b_id, conflict.chunk_b_id), ctx["request"].query)
        if source_a is None or source_b is None:
            continue
        resolved.append(conflict.model_copy(update={"source_a": source_a, "source_b": source_b}))
    return resolved


def _hit_key(hit: SearchHit) -> tuple[str, str]:
    return (
        str(hit.payload.get("doc_id", hit.point_id)),
        str(hit.payload.get("chunk_id", hit.point_id)),
    )


def _source_for_key(
    hits: dict[tuple[str, str], SearchHit],
    key: tuple[str, str],
    query: str,
) -> SourceAnchor | None:
    hit = hits.get(key)
    return source_from_hit(hit, query=query) if hit is not None else None


def _claim_from_payload(hit: SearchHit, raw_claim: dict[str, object]) -> ClaimRecord | None:
    entity = _text(raw_claim.get("entity"))
    attribute = _text(raw_claim.get("attribute"))
    value = _text(raw_claim.get("value"))
    if not entity or not attribute or not value:
        return None
    return ClaimRecord(
        id=_text(raw_claim.get("id") or raw_claim.get("claim_id")),
        doc_id=_text(raw_claim.get("doc_id")) or str(hit.payload.get("doc_id", "")),
        chunk_id=_text(raw_claim.get("chunk_id")) or str(hit.payload.get("chunk_id", hit.point_id)),
        entity=entity,
        attribute=attribute,
        value=value,
    )


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _is_live_db_hit(hit: SearchHit) -> bool:
    if str(hit.payload.get("source_type") or "").startswith("connector_live_sql"):
        return True
    return str(hit.payload.get("doc_id") or "").startswith("connector-live-scope:")


def _db_fields(hit: SearchHit) -> list[tuple[str, str]]:
    raw_fields = hit.payload.get("structured_fields")
    fields: list[tuple[str, str]] = []
    if isinstance(raw_fields, list):
        for item in raw_fields:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            value = str(item.get("value") or "").strip()
            if label and value and _normalized_label(label) in _DISAGREEMENT_FIELDS:
                fields.append((label, value))
    for name in _DISAGREEMENT_FIELDS:
        value = hit.payload.get(name)
        if value not in (None, ""):
            fields.append((name, str(value)))
    return fields


def _document_field_value(hit: SearchHit, label: str) -> str | None:
    text = str(hit.payload.get("text") or "")
    normalized_label = re.escape(_normalized_label(label).replace("_", " "))
    patterns = [
        rf"\b{normalized_label}\b\s*(?:is|=|:|-)\s*([A-Za-z0-9_][A-Za-z0-9_\- ]{{0,60}})",
        rf"\b{normalized_label.replace(' ', '_')}\b\s*(?:is|=|:|-)\s*([A-Za-z0-9_][A-Za-z0-9_\- ]{{0,60}})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_extracted_value(match.group(1))
    return None


def _clean_extracted_value(value: str) -> str:
    text = re.split(r"[\n.;,|]", value, maxsplit=1)[0]
    return " ".join(text.split()).strip()


def _normalized_label(value: str) -> str:
    return " ".join(re.findall(r"[A-Za-z0-9_]+", value.lower())).replace(" ", "_")


def _normalized_value(value: str) -> str:
    return " ".join(re.findall(r"[A-Za-z0-9_]+", value.lower()))


def _values_agree(left: str, right: str) -> bool:
    left_norm = _normalized_value(left)
    right_norm = _normalized_value(right)
    if not left_norm or not right_norm:
        return True
    return left_norm == right_norm or left_norm in right_norm or right_norm in left_norm
