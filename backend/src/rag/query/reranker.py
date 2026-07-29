"""Cross-encoder reranking for retrieved chunks."""

from __future__ import annotations

import logging
from collections.abc import Collection
from functools import lru_cache
from time import monotonic
from typing import Any

from rag.shared.contracts.reranker_models import (
    DEFAULT_RERANKER_MODEL,
    reranker_passage_max_chars,
)
from rag.shared.contracts.rag_defaults import RerankerDevice
from rag.shared.runtime_offline import apply_runtime_offline_defaults

from .cancellation import QueryCancellationToken, QueryCancelled
from rag.query.retrieval.metadata_scoring import annotate_metadata_matches
from .qdrant import SearchHit
from .reranking.coverage import (
    coverage_obligations as _coverage_obligations,
    expanded_exhaustive_candidates as _expanded_exhaustive_candidates,
    merge_exhaustive_coverage_roles as _merge_exhaustive_coverage_roles,
    required_exhaustive_coverage_units as _required_exhaustive_coverage_units,
)
from .reranking.models import (
    EXHAUSTIVE_RERANK_STRATEGY as _EXHAUSTIVE_RERANK_STRATEGY,
    ExhaustiveScope as _ExhaustiveScope,
    ExhaustiveScoring as _ExhaustiveScoring,
    ExhaustiveUnit as _ExhaustiveUnit,
    RerankResult,
    ScoredExhaustiveUnit as _ScoredExhaustiveUnit,
)
from .reranking.scope import (
    heading_matched_exhaustive_unit_keys as _heading_matched_exhaustive_unit_keys,
    is_toc_exhaustive_hit as _is_toc_exhaustive_hit,
    is_toc_only_exhaustive_unit as _is_toc_only_exhaustive_unit,
    referenced_exhaustive_unit_keys as _referenced_exhaustive_unit_keys,
    requires_document_summary_coverage as _requires_document_summary_coverage,
    requires_full_section_coverage as _requires_full_section_coverage,
)
from .reranking.scoring import (
    fallback_rank_hits as _fallback_rank_hits,
    limit_rerank_candidates as _limit_rerank_candidates,
    rank_scored_hits as _rank_scored_hits,
)
from .reranking.text import (
    hit_doc_id as _hit_doc_id,
    hit_page as _hit_page,
    normalized_text as _normalized_phrase,
    payload_str as _payload_str,
    reranker_text as _reranker_text,
    searchable_text as _searchable_text,
    unique_hits as _unique_hits,
)
from rag.query.retrieval.retrieval_budget import EXHAUSTIVE_RETRIEVAL_BUDGET_SECONDS

_LOG = logging.getLogger(__name__)
_POINT_BATCH_SIZE = 8
_EXHAUSTIVE_BATCH_SIZE = 32
_EXHAUSTIVE_WAVE_SIZE = 512
_REPRESENTATIVE_TEXT_MAX_CHARS = 1024
_EXHAUSTIVE_CHILD_TEXT_MAX_CHARS = 1024
_PAGE_WINDOW_SIZE = 4
_ORDINAL_WINDOW_SIZE = 8
_CPU_EXECUTION_PROVIDER = "CPUExecutionProvider"
_CUDA_EXECUTION_PROVIDER = "CUDAExecutionProvider"


def rerank_hits(
    query: str,
    hits: list[SearchHit],
    *,
    top_k: int,
    max_candidates: int | None = None,
    model_name: str = DEFAULT_RERANKER_MODEL,
    cache_dir: str | None = "/models/fastembed",
    device: RerankerDevice = "auto",
    exhaustive: bool = False,
    deadline: float | None = None,
    cancellation_token: QueryCancellationToken | None = None,
) -> list[SearchHit]:
    return list(
        rerank_hits_with_result(
            query,
            hits,
            top_k=top_k,
            max_candidates=max_candidates,
            model_name=model_name,
            cache_dir=cache_dir,
            device=device,
            exhaustive=exhaustive,
            deadline=deadline,
            cancellation_token=cancellation_token,
        ).ranked_hits
    )


def rerank_hits_with_result(
    query: str,
    hits: list[SearchHit],
    *,
    top_k: int,
    max_candidates: int | None = None,
    model_name: str = DEFAULT_RERANKER_MODEL,
    cache_dir: str | None = "/models/fastembed",
    device: RerankerDevice = "auto",
    exhaustive: bool = False,
    deadline: float | None = None,
    cancellation_token: QueryCancellationToken | None = None,
) -> RerankResult:
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if max_candidates is not None and max_candidates <= 0:
        raise ValueError("max_candidates must be positive")
    return _cross_encoder_rerank(
        query,
        hits,
        top_k=top_k,
        max_candidates=max_candidates,
        model_name=model_name,
        cache_dir=cache_dir,
        device=device,
        exhaustive=exhaustive,
        deadline=deadline,
        cancellation_token=cancellation_token,
    )


def rank_passages(
    query: str,
    passages: list[str],
    *,
    model_name: str = DEFAULT_RERANKER_MODEL,
    cache_dir: str | None = "/models/fastembed",
    device: RerankerDevice = "auto",
) -> list[tuple[int, float]]:
    if not model_name:
        raise ValueError("cross-encoder reranker model name is required")
    if not passages:
        return []
    model = _load_cross_encoder(model_name, cache_dir, device)
    scores = [float(score) for score in model.rerank(query, passages)]
    if len(scores) != len(passages):
        raise RuntimeError("cross-encoder reranker returned an unexpected score count")
    return sorted(enumerate(scores), key=lambda item: (-item[1], item[0]))


def _cross_encoder_rerank(
    query: str,
    hits: list[SearchHit],
    *,
    top_k: int,
    max_candidates: int | None,
    model_name: str,
    cache_dir: str | None,
    device: RerankerDevice,
    exhaustive: bool,
    deadline: float | None,
    cancellation_token: QueryCancellationToken | None,
) -> RerankResult:
    if not model_name:
        raise ValueError("cross-encoder reranker model name is required")
    if not hits:
        return RerankResult(candidates=(), ranked_hits=())
    hits = annotate_metadata_matches(query, hits)
    if exhaustive and _has_exhaustive_scope(hits):
        return _exhaustive_cross_encoder_rerank(
            query,
            hits,
            top_k=top_k,
            max_candidates=max_candidates,
            model_name=model_name,
            cache_dir=cache_dir,
            device=device,
            deadline=deadline,
            cancellation_token=cancellation_token,
        )
    hits = _limit_rerank_candidates(query, hits, max_candidates=max_candidates)
    passage_max_chars = reranker_passage_max_chars(model_name)
    passages = [
        _reranker_text(hit, max_chars=passage_max_chars) for hit in hits
    ]
    try:
        model = _load_cross_encoder(model_name, cache_dir, device)
        score_values, batch_count, stop_reason = _score_point_passages(
            model,
            query,
            passages,
            deadline=deadline,
            cancellation_token=cancellation_token,
        )
        scored_hits = hits[: len(score_values)]
        ranked_scored = _rank_scored_hits(
            query, scored_hits, score_values, top_k=len(scored_hits)
        )
        if stop_reason is None:
            ranked_candidates = tuple(ranked_scored)
        else:
            fallback = _fallback_rank_hits(
                query,
                hits[len(score_values) :],
                top_k=len(hits) - len(score_values),
                error=TimeoutError(stop_reason),
            )
            ranked_candidates = tuple((*ranked_scored, *fallback))
        return RerankResult(
            candidates=tuple(hits),
            ranked_hits=ranked_candidates[:top_k],
            ranked_candidates=ranked_candidates,
            stop_reason=stop_reason,
            candidate_wave_count=batch_count,
            input_character_count=sum(
                len(passage) for passage in passages[: len(score_values)]
            ),
            passage_max_chars=passage_max_chars,
        )
    except QueryCancelled:
        raise
    except Exception as exc:
        _LOG.warning(
            "cross-encoder reranker failed; falling back to retrieval policy",
            extra={
                "candidate_count": len(hits),
                "error_type": type(exc).__name__,
                "model_name": model_name,
            },
            exc_info=True,
        )
        ranked_candidates = tuple(
            _fallback_rank_hits(query, hits, top_k=len(hits), error=exc)
        )
        return RerankResult(
            candidates=tuple(hits),
            ranked_hits=ranked_candidates[:top_k],
            ranked_candidates=ranked_candidates,
            input_character_count=sum(len(passage) for passage in passages),
            passage_max_chars=passage_max_chars,
        )


def _score_point_passages(
    model: Any,
    query: str,
    passages: list[str],
    *,
    deadline: float | None,
    cancellation_token: QueryCancellationToken | None,
) -> tuple[list[float], int, str | None]:
    scores: list[float] = []
    batch_count = 0
    for start in range(0, len(passages), _POINT_BATCH_SIZE):
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if deadline is not None and monotonic() >= deadline:
            return scores, batch_count, "deadline_exceeded"
        batch = passages[start : start + _POINT_BATCH_SIZE]
        batch_scores = [float(score) for score in model.rerank(query, batch)]
        if len(batch_scores) != len(batch):
            raise RuntimeError(
                "cross-encoder reranker returned an unexpected score count"
            )
        scores.extend(batch_scores)
        batch_count += 1
    return scores, batch_count, None


def _exhaustive_cross_encoder_rerank(
    query: str,
    hits: list[SearchHit],
    *,
    top_k: int,
    max_candidates: int | None,
    model_name: str,
    cache_dir: str | None,
    device: RerankerDevice,
    deadline: float | None,
    cancellation_token: QueryCancellationToken | None,
) -> RerankResult:
    unique_hits = _unique_hits(hits)
    authorized_scan_complete = _authorized_scan_complete(unique_hits)
    units = _build_exhaustive_units(unique_hits)
    if not units:
        return _exhaustive_fallback_result(
            query,
            unique_hits,
            top_k=top_k,
            max_candidates=max_candidates,
            error=RuntimeError("exhaustive hierarchy unavailable"),
            stop_reason="hierarchy_unavailable",
        )
    scope = _resolve_exhaustive_scope(
        query,
        unique_hits,
        units,
        max_candidates=max_candidates,
    )
    deadline = (
        monotonic() + EXHAUSTIVE_RETRIEVAL_BUDGET_SECONDS
        if deadline is None
        else deadline
    )
    if monotonic() >= deadline:
        return _exhaustive_fallback_result(
            query,
            unique_hits,
            top_k=top_k,
            max_candidates=max_candidates,
            error=RuntimeError("exhaustive retrieval deadline exceeded"),
            stop_reason="deadline_exceeded",
            representative_count=len(units),
            candidate_coverage_status="partial",
        )
    try:
        model = _load_cross_encoder(model_name, cache_dir, device)
        scoring = _score_exhaustive_hierarchy(
            model,
            query,
            units,
            scope,
            cancellation_token=cancellation_token,
            deadline=deadline,
        )
    except QueryCancelled:
        raise
    except Exception as exc:
        _LOG.warning(
            "exhaustive cross-encoder reranker failed; returning explicitly partial fallback evidence",
            extra={
                "candidate_count": len(unique_hits),
                "error_type": type(exc).__name__,
                "model_name": model_name,
                "representative_count": len(units),
            },
            exc_info=True,
        )
        return _exhaustive_fallback_result(
            query,
            unique_hits,
            top_k=top_k,
            max_candidates=max_candidates,
            error=exc,
            stop_reason="reranker_error",
            representative_count=len(units),
        )
    return _build_exhaustive_result(
        query,
        unique_hits,
        units,
        scope,
        scoring,
        top_k=top_k,
        max_candidates=max_candidates,
        authorized_scan_complete=authorized_scan_complete,
    )


def _resolve_exhaustive_scope(
    query: str,
    hits: list[SearchHit],
    units: list[_ExhaustiveUnit],
    *,
    max_candidates: int | None,
) -> _ExhaustiveScope:
    eligible_units = [
        unit for unit in units if not _is_toc_only_exhaustive_unit(query, unit)
    ]
    referenced_keys, _, exclusive_keys = _referenced_exhaustive_unit_keys(
        query,
        hits,
        eligible_units,
        head_limit=max_candidates or 40,
    )
    heading_keys = _heading_matched_exhaustive_unit_keys(query, eligible_units)
    if exclusive_keys:
        heading_keys &= exclusive_keys
    return _ExhaustiveScope(
        coverage_eligible_unit_keys=frozenset(unit.key for unit in eligible_units),
        referenced_unit_keys=frozenset(referenced_keys),
        heading_matched_unit_keys=frozenset(heading_keys),
        exclusive_scope_unit_keys=frozenset(exclusive_keys),
        semantic_scope_resolved=bool(
            exclusive_keys
            or _requires_full_section_coverage(query)
            or _requires_document_summary_coverage(query)
        ),
    )


def _score_exhaustive_hierarchy(
    model: Any,
    query: str,
    units: list[_ExhaustiveUnit],
    scope: _ExhaustiveScope,
    *,
    cancellation_token: QueryCancellationToken | None,
    deadline: float,
) -> _ExhaustiveScoring:
    representative_scores, representative_stop = _rerank_passages_batched(
        model,
        query,
        [unit.representative_text for unit in units],
        cancellation_token=cancellation_token,
        deadline=deadline,
    )
    scored_units = _rank_exhaustive_units(
        units[: len(representative_scores)], representative_scores
    )
    selected_units, selection_complete = _select_exhaustive_units(
        scored_units,
        prioritized_keys=(scope.referenced_unit_keys | scope.heading_matched_unit_keys),
    )
    coverage_unit_keys = _required_exhaustive_coverage_units(
        query,
        [
            scored
            for scored in selected_units
            if scored.unit.key in scope.coverage_eligible_unit_keys
        ],
        referenced_unit_keys=set(scope.referenced_unit_keys),
        heading_matched_unit_keys=set(scope.heading_matched_unit_keys),
        exclusive_scope_unit_keys=set(scope.exclusive_scope_unit_keys),
    )
    qualifying_units = [
        scored for scored in selected_units if scored.unit.key in coverage_unit_keys
    ]
    candidates = _expanded_exhaustive_candidates(
        query,
        qualifying_units,
        coverage_unit_keys=coverage_unit_keys,
        complete_unit_keys=set(scope.exclusive_scope_unit_keys),
    )
    child_scores, child_stop = _rerank_exhaustive_children(
        model,
        query,
        [
            _bounded_stratified_text(
                _searchable_text(hit),
                max_chars=_EXHAUSTIVE_CHILD_TEXT_MAX_CHARS,
            )
            for hit in candidates
        ],
        cancellation_token=cancellation_token,
        deadline=deadline,
    )
    return _ExhaustiveScoring(
        representative_scores=tuple(representative_scores),
        candidates=tuple(candidates),
        child_scores=tuple(child_scores),
        representative_stop=representative_stop,
        child_stop=child_stop,
        selection_complete=selection_complete,
    )


def _build_exhaustive_result(
    query: str,
    hits: list[SearchHit],
    units: list[_ExhaustiveUnit],
    scope: _ExhaustiveScope,
    scoring: _ExhaustiveScoring,
    *,
    top_k: int,
    max_candidates: int | None,
    authorized_scan_complete: bool | None,
) -> RerankResult:
    scored_candidates = list(scoring.candidates[: len(scoring.child_scores)])
    stop_reason = scoring.representative_stop or scoring.child_stop
    if not scored_candidates:
        return _exhaustive_fallback_result(
            query,
            hits,
            top_k=top_k,
            max_candidates=max_candidates,
            error=RuntimeError(
                stop_reason or "exhaustive candidate scoring incomplete"
            ),
            stop_reason=stop_reason or "candidate_scoring_incomplete",
            representative_count=len(units),
            representative_scored_count=len(scoring.representative_scores),
            candidate_coverage_status="partial",
        )
    candidate_complete, stop_reason = _candidate_coverage_result(
        authorized_scan_complete,
        units,
        scoring,
        stop_reason=stop_reason,
    )
    ranked_hits = _rank_exhaustive_evidence(
        query,
        scored_candidates,
        list(scoring.child_scores),
        scope=scope,
        top_k=top_k,
    )
    required_obligations = _coverage_obligations(list(scoring.candidates))
    covered_obligations = _coverage_obligations(ranked_hits)
    evidence_complete, evidence_stop_reason = _evidence_coverage_result(
        candidate_complete,
        scope.semantic_scope_resolved,
        required_obligations,
        covered_obligations,
    )
    return RerankResult(
        candidates=tuple(scored_candidates),
        ranked_hits=tuple(ranked_hits),
        strategy=_EXHAUSTIVE_RERANK_STRATEGY,
        candidate_coverage_status="complete" if candidate_complete else "partial",
        evidence_coverage_status="complete" if evidence_complete else "partial",
        stop_reason=stop_reason,
        evidence_stop_reason=evidence_stop_reason,
        required_coverage_obligations=tuple(sorted(required_obligations)),
        covered_coverage_obligations=tuple(sorted(covered_obligations)),
        representative_count=len(units),
        representative_scored_count=len(scoring.representative_scores),
        candidate_wave_count=(
            (len(scored_candidates) + _EXHAUSTIVE_WAVE_SIZE - 1)
            // _EXHAUSTIVE_WAVE_SIZE
        ),
    )


def _candidate_coverage_result(
    authorized_scan_complete: bool | None,
    units: list[_ExhaustiveUnit],
    scoring: _ExhaustiveScoring,
    *,
    stop_reason: str | None,
) -> tuple[bool, str | None]:
    required_obligations = _coverage_obligations(list(scoring.candidates))
    scored_candidates = list(scoring.candidates[: len(scoring.child_scores)])
    covered_obligations = _coverage_obligations(scored_candidates)
    candidate_set_complete = (
        required_obligations <= covered_obligations
        if required_obligations
        else len(scoring.child_scores) == len(scoring.candidates)
    )
    complete = (
        authorized_scan_complete is True
        and scoring.representative_stop is None
        and len(scoring.representative_scores) == len(units)
        and scoring.selection_complete
        and candidate_set_complete
    )
    if complete:
        return True, None
    if stop_reason is not None:
        return False, stop_reason
    if authorized_scan_complete is False:
        return False, "authorized_scan_truncated"
    if authorized_scan_complete is None:
        return False, "scan_completeness_unknown"
    return False, "candidate_budget_exceeded"


def _rank_exhaustive_evidence(
    query: str,
    candidates: list[SearchHit],
    scores: list[float],
    *,
    scope: _ExhaustiveScope,
    top_k: int,
) -> list[SearchHit]:
    ranked_hits = _rank_scored_hits(
        query,
        candidates,
        scores,
        top_k=len(candidates),
    )
    if scope.exclusive_scope_unit_keys:
        ranked_hits = [
            hit
            for hit in ranked_hits
            if hit.payload.get("exhaustive_coverage_unit_id")
            in scope.exclusive_scope_unit_keys
        ]
    ranked_hits = [hit for hit in ranked_hits if not _is_toc_exhaustive_hit(query, hit)]
    return _merge_exhaustive_coverage_roles(
        ranked_hits,
        candidates,
        top_k=top_k,
    )


def _evidence_coverage_result(
    candidate_complete: bool,
    semantic_scope_resolved: bool,
    required_obligations: set[str],
    covered_obligations: set[str],
) -> tuple[bool, str | None]:
    complete = (
        candidate_complete
        and semantic_scope_resolved
        and required_obligations <= covered_obligations
    )
    if complete:
        return True, None
    if not candidate_complete:
        return False, "candidate_coverage_incomplete"
    if not semantic_scope_resolved:
        return False, "semantic_scope_unresolved"
    return False, "final_evidence_coverage_incomplete"


def _exhaustive_fallback_result(
    query: str,
    hits: list[SearchHit],
    *,
    top_k: int,
    max_candidates: int | None,
    error: Exception,
    stop_reason: str,
    representative_count: int = 0,
    representative_scored_count: int = 0,
    candidate_coverage_status: str = "unknown",
) -> RerankResult:
    fallback_candidates = _limit_rerank_candidates(
        query,
        hits,
        max_candidates=max_candidates,
    )
    return RerankResult(
        candidates=tuple(fallback_candidates),
        ranked_hits=tuple(
            _fallback_rank_hits(
                query,
                fallback_candidates,
                top_k=top_k,
                error=error,
            )
        ),
        strategy=_EXHAUSTIVE_RERANK_STRATEGY,
        candidate_coverage_status=candidate_coverage_status,
        evidence_coverage_status="unknown",
        stop_reason=stop_reason,
        evidence_stop_reason="candidate_coverage_unknown",
        representative_count=representative_count,
        representative_scored_count=representative_scored_count,
    )


def _has_exhaustive_scope(hits: list[SearchHit]) -> bool:
    return any(
        str(hit.payload.get("exhaustive_scope_origin", "")) == "document_class_scope"
        for hit in hits
    )


def _authorized_scan_complete(hits: list[SearchHit]) -> bool | None:
    statuses = [
        hit.payload.get("authorized_scan_complete")
        for hit in hits
        if hit.payload.get("exhaustive_scope_origin") == "document_class_scope"
    ]
    if any(status is False for status in statuses):
        return False
    if statuses and all(status is True for status in statuses):
        return True
    return None


def _build_exhaustive_units(hits: list[SearchHit]) -> list[_ExhaustiveUnit]:
    parent_sections: dict[tuple[str, str], set[str]] = {}
    for hit in hits:
        doc_id = _hit_doc_id(hit)
        parent_id = _payload_str(hit, "parent_chunk_id")
        section_id = _payload_str(hit, "parent_section_id")
        if parent_id:
            parent_sections.setdefault((doc_id, parent_id), set()).add(section_id)

    grouped: dict[str, list[SearchHit]] = {}
    group_order: dict[str, int] = {}
    ordinal_by_doc: dict[str, int] = {}
    for order, hit in enumerate(hits):
        doc_id = _hit_doc_id(hit)
        section_id = _payload_str(hit, "parent_section_id")
        parent_id = _payload_str(hit, "parent_chunk_id")
        page = _hit_page(hit)
        if section_id or parent_id:
            key = f"{doc_id}|section:{section_id}|parent:{parent_id}"
        elif page is not None:
            page_window = max(0, page - 1) // _PAGE_WINDOW_SIZE
            key = f"{doc_id}|page-window:{page_window}"
        else:
            ordinal = ordinal_by_doc.get(doc_id, 0)
            key = f"{doc_id}|ordinal-window:{ordinal // _ORDINAL_WINDOW_SIZE}"
            ordinal_by_doc[doc_id] = ordinal + 1
        grouped.setdefault(key, []).append(hit)
        group_order.setdefault(key, order)

    units: list[_ExhaustiveUnit] = []
    for key, children in grouped.items():
        first = children[0]
        doc_id = _hit_doc_id(first)
        parent_id = _payload_str(first, "parent_chunk_id")
        section_ids = parent_sections.get((doc_id, parent_id), set())
        parent_is_section_pure = bool(parent_id) and len(section_ids) == 1
        units.append(
            _ExhaustiveUnit(
                key=key,
                doc_id=doc_id,
                order=group_order[key],
                children=tuple(_unique_hits(children)),
                representative_text=_representative_text(
                    children,
                    use_parent_text=parent_is_section_pure,
                ),
            )
        )
    return sorted(units, key=lambda unit: unit.order)


def _representative_text(
    children: list[SearchHit],
    *,
    use_parent_text: bool,
) -> str:
    first = children[0]
    descriptor_parts: list[str] = []
    for field in (
        "doc_title",
        "section_title",
        "table_title",
        "table_caption",
    ):
        value = first.payload.get(field)
        if isinstance(value, str) and value.strip():
            descriptor_parts.append(value.strip())
    section_path = first.payload.get("section_path")
    if isinstance(section_path, list):
        descriptor_parts.extend(
            value.strip()
            for item in section_path
            if isinstance(item, str) and (value := item.strip())
        )

    body = ""
    if use_parent_text:
        parent_text = first.payload.get("parent_text")
        if isinstance(parent_text, str):
            body = parent_text.strip()
    if not body:
        child_parts: list[str] = []
        seen: set[str] = set()
        for child in children:
            value = _searchable_text(child).strip()
            normalized = _normalized_phrase(value)
            if not value or normalized in seen:
                continue
            seen.add(normalized)
            child_parts.append(value)
        body = "\n".join(child_parts)

    descriptor = "\n".join(dict.fromkeys(descriptor_parts))
    return _bounded_stratified_text(
        "\n".join(part for part in (descriptor, body) if part),
        max_chars=_REPRESENTATIVE_TEXT_MAX_CHARS,
    )


def _bounded_stratified_text(text: str, *, max_chars: int) -> str:
    normalized = text.strip()
    if len(normalized) <= max_chars:
        return normalized
    window = (max_chars - 2) // 3
    middle_start = max(0, (len(normalized) - window) // 2)
    return "\n".join(
        (
            normalized[:window].rstrip(),
            normalized[middle_start : middle_start + window].strip(),
            normalized[-window:].lstrip(),
        )
    )


def _rerank_passages_batched(
    model: Any,
    query: str,
    passages: list[str],
    *,
    cancellation_token: QueryCancellationToken | None,
    deadline: float,
) -> tuple[list[float], str | None]:
    scores: list[float] = []
    for start in range(0, len(passages), _EXHAUSTIVE_BATCH_SIZE):
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if monotonic() >= deadline:
            return scores, "deadline_exceeded"
        batch = passages[start : start + _EXHAUSTIVE_BATCH_SIZE]
        batch_scores = [float(score) for score in model.rerank(query, batch)]
        if len(batch_scores) != len(batch):
            raise RuntimeError(
                "cross-encoder reranker returned an unexpected score count"
            )
        scores.extend(batch_scores)
    return scores, None


def _rerank_exhaustive_children(
    model: Any,
    query: str,
    passages: list[str],
    *,
    cancellation_token: QueryCancellationToken | None,
    deadline: float,
) -> tuple[list[float], str | None]:
    scores: list[float] = []
    for start in range(0, len(passages), _EXHAUSTIVE_WAVE_SIZE):
        wave = passages[start : start + _EXHAUSTIVE_WAVE_SIZE]
        wave_scores, stop_reason = _rerank_passages_batched(
            model,
            query,
            wave,
            cancellation_token=cancellation_token,
            deadline=deadline,
        )
        scores.extend(wave_scores)
        if stop_reason is not None:
            return scores, stop_reason
    return scores, None


def _rank_exhaustive_units(
    units: list[_ExhaustiveUnit],
    scores: list[float],
) -> list[_ScoredExhaustiveUnit]:
    ranked = sorted(
        zip(units, scores, strict=True),
        key=lambda item: (-item[1], item[0].order),
    )
    return [
        _ScoredExhaustiveUnit(unit=unit, score=score, rank=rank)
        for rank, (unit, score) in enumerate(ranked, start=1)
    ]


def _select_exhaustive_units(
    ranked_units: list[_ScoredExhaustiveUnit],
    *,
    prioritized_keys: set[str],
) -> tuple[list[_ScoredExhaustiveUnit], bool]:
    selected: list[_ScoredExhaustiveUnit] = []
    seen: set[str] = set()

    def add(scored: _ScoredExhaustiveUnit) -> None:
        if scored.unit.key in seen:
            return
        selected.append(scored)
        seen.add(scored.unit.key)

    best_by_doc: dict[str, _ScoredExhaustiveUnit] = {}
    for scored in ranked_units:
        best_by_doc.setdefault(scored.unit.doc_id, scored)
    for scored in ranked_units:
        if scored.unit.key in prioritized_keys:
            add(scored)
    for scored in sorted(best_by_doc.values(), key=lambda item: item.rank):
        add(scored)
    for scored in ranked_units:
        add(scored)
    return selected, len(selected) == len(ranked_units)


@lru_cache(maxsize=8)
def _load_cross_encoder(
    model_name: str,
    cache_dir: str | None,
    device: RerankerDevice,
) -> Any:
    apply_runtime_offline_defaults()
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
    except ImportError as exc:
        raise RuntimeError(
            "FastEmbed cross-encoder reranker requires optional dependency "
            "`fastembed`; install backend dependencies before running RAG queries"
        ) from exc
    return TextCrossEncoder(
        model_name=model_name,
        cache_dir=cache_dir,
        providers=list(_reranker_execution_providers(device)),
    )


def _reranker_execution_providers(
    device: RerankerDevice,
    available: Collection[str] | None = None,
) -> tuple[str, ...]:
    if available is None:
        try:
            import onnxruntime
        except ImportError as exc:
            raise RuntimeError("ONNX Runtime is required for reranking") from exc
        available = onnxruntime.get_available_providers()
    available_set = set(available)
    if device == "cuda":
        if _CUDA_EXECUTION_PROVIDER not in available_set:
            raise RuntimeError(
                "CUDA reranking was requested, but CUDAExecutionProvider is unavailable; "
                "build with RERANKER_RUNTIME=cuda and start with the NVIDIA GPU Compose override"
            )
        return (_CUDA_EXECUTION_PROVIDER,)
    if device == "auto" and _CUDA_EXECUTION_PROVIDER in available_set:
        fallback = (
            (_CPU_EXECUTION_PROVIDER,)
            if _CPU_EXECUTION_PROVIDER in available_set
            else ()
        )
        return (_CUDA_EXECUTION_PROVIDER, *fallback)
    if _CPU_EXECUTION_PROVIDER not in available_set:
        raise RuntimeError("CPUExecutionProvider is unavailable for reranking")
    return (_CPU_EXECUTION_PROVIDER,)
