"""Agent 4 claim extraction and conflict lookup helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ..auth.abac import build_abac_filter
from ..auth.document_access import can_read_group_path
from ..shared.contracts.clearance import can_access_clearance
from ..schemas.internal import ClaimRecord
from ..schemas.query import ConflictPair, SourceAnchor
from .cancellation import call_with_optional_cancellation, cancellation_token_from_context
from .qdrant import QdrantClient, SearchHit
from .state import QueryContext, scoped_user_context, visible_group_paths
from .sources import source_from_hit


class ConflictChecker(Protocol):
    def check_conflicts(
        self,
        claims: list[ClaimRecord],
        *,
        visible_group_paths: Sequence[str] | None = None,
    ) -> list[ConflictPair]: ...


class NoopConflictChecker:
    def check_conflicts(
        self,
        claims: list[ClaimRecord],
        *,
        visible_group_paths: Sequence[str] | None = None,
    ) -> list[ConflictPair]:
        _ = claims, visible_group_paths
        return []


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
