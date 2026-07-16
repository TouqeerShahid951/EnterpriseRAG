"""Coverage obligations and evidence preservation for exhaustive reranking."""

from __future__ import annotations

from ..qdrant import SearchHit
from rag.query.sources.source_parent_promotion import (
    PARENT_PROMOTION_MAX_CHARS,
    _promote_parent_text,
)
from .models import (
    EXHAUSTIVE_CANDIDATE_ORIGIN,
    EXHAUSTIVE_COVERAGE_ROLE,
    ExhaustiveUnit,
    ScoredExhaustiveUnit,
)
from .scope import (
    contains_normalized_phrase,
    is_toc_exhaustive_hit,
    requires_document_summary_coverage,
    requires_full_section_coverage,
)
from .text import (
    hit_identity,
    hit_page,
    normalized_text,
    payload_int,
    payload_str,
    searchable_text,
    unique_hits,
)

_EXHAUSTIVE_SEED_UNIT_LIMIT = 3


def required_exhaustive_coverage_units(
    query: str,
    selected_units: list[ScoredExhaustiveUnit],
    *,
    referenced_unit_keys: set[str],
    heading_matched_unit_keys: set[str],
    exclusive_scope_unit_keys: set[str],
) -> set[str]:
    if exclusive_scope_unit_keys:
        return set(exclusive_scope_unit_keys)
    if requires_full_section_coverage(query) or requires_document_summary_coverage(
        query
    ):
        return {scored.unit.key for scored in selected_units}
    ranked_units = sorted(selected_units, key=lambda scored: scored.rank)
    required = {
        scored.unit.key for scored in ranked_units[:_EXHAUSTIVE_SEED_UNIT_LIMIT]
    }
    required.update(
        scored.unit.key
        for scored in ranked_units
        if scored.unit.key in referenced_unit_keys
    )
    required.update(heading_matched_unit_keys)
    best_by_doc: dict[str, ScoredExhaustiveUnit] = {}
    for scored in ranked_units:
        best_by_doc.setdefault(scored.unit.doc_id, scored)
    required.update(scored.unit.key for scored in best_by_doc.values())
    return required


def expanded_exhaustive_candidates(
    query: str,
    selected_units: list[ScoredExhaustiveUnit],
    *,
    coverage_unit_keys: set[str],
    complete_unit_keys: set[str],
) -> list[SearchHit]:
    coverage_candidates: list[SearchHit] = []
    ordinary_candidates: list[SearchHit] = []
    for scored in selected_units:
        coverage_assignments = (
            _coverage_assignments(
                query,
                scored.unit,
                require_complete_unit=scored.unit.key in complete_unit_keys,
            )
            if scored.unit.key in coverage_unit_keys
            else {}
        )
        for child in scored.unit.children:
            payload = {
                **child.payload,
                "rerank_candidate_origin": EXHAUSTIVE_CANDIDATE_ORIGIN,
                "exhaustive_coverage_unit_id": scored.unit.key,
                "exhaustive_representative_rank": scored.rank,
                "exhaustive_representative_score": scored.score,
            }
            obligations = coverage_assignments.get(hit_identity(child), set())
            if obligations:
                payload["coverage_role"] = EXHAUSTIVE_COVERAGE_ROLE
                payload["exhaustive_coverage_obligation_ids"] = sorted(obligations)
            candidate = SearchHit(
                point_id=child.point_id,
                score=child.score,
                payload=payload,
            )
            if obligations:
                coverage_candidates.extend(_promote_parent_text([candidate]))
            else:
                ordinary_candidates.append(candidate)
    return unique_hits([*coverage_candidates, *ordinary_candidates])


def _coverage_assignments(
    query: str,
    unit: ExhaustiveUnit,
    *,
    require_complete_unit: bool = False,
) -> dict[tuple[str, str, str], set[str]]:
    coverage_children = tuple(
        child for child in unit.children if not is_toc_exhaustive_hit(query, child)
    )
    if not coverage_children:
        return {}
    coverage_child = _coverage_child(coverage_children)
    coverage_identity = hit_identity(coverage_child)
    assignments = {
        coverage_identity: {f"unit:{unit.key}"},
    }
    requires_complete_unit = (
        require_complete_unit
        or requires_full_section_coverage(query)
        or requires_document_summary_coverage(query)
    )
    if requires_complete_unit and not _parent_covers_unit(
        coverage_child,
        coverage_children,
    ):
        for child in coverage_children:
            child_identity = hit_identity(child)
            assignments.setdefault(child_identity, set()).add(
                f"child:{unit.key}:{child_identity}"
            )
    children_by_page: dict[int, list[SearchHit]] = {}
    for child in coverage_children:
        page = hit_page(child)
        if page is not None:
            children_by_page.setdefault(page, []).append(child)
    if not children_by_page:
        return assignments

    page_obligations = {page: f"page:{unit.doc_id}:{page}" for page in children_by_page}
    if _parent_covers_pages(coverage_child, set(children_by_page)):
        assignments[coverage_identity].update(page_obligations.values())
        return assignments

    for page, children in children_by_page.items():
        page_child = _coverage_child(tuple(children))
        assignments.setdefault(hit_identity(page_child), set()).add(
            page_obligations[page]
        )
    return assignments


def _parent_covers_unit(
    hit: SearchHit,
    children: tuple[SearchHit, ...],
) -> bool:
    parent_text = str(hit.payload.get("parent_text") or "").strip()
    if not parent_text or len(parent_text) > PARENT_PROMOTION_MAX_CHARS:
        return False
    parent_id = payload_str(hit, "parent_chunk_id")
    if not parent_id or any(
        payload_str(child, "parent_chunk_id") != parent_id for child in children
    ):
        return False
    normalized_parent = normalized_text(parent_text)
    if any(
        (child_text := normalized_text(searchable_text(child)))
        and not contains_normalized_phrase(normalized_parent, child_text)
        for child in children
    ):
        return False
    pages = {page for child in children if (page := hit_page(child)) is not None}
    return not pages or _parent_covers_pages(hit, pages)


def _parent_covers_pages(hit: SearchHit, pages: set[int]) -> bool:
    parent_text = str(hit.payload.get("parent_text") or "").strip()
    if not parent_text or len(parent_text) > PARENT_PROMOTION_MAX_CHARS:
        return False
    page_start = payload_int(hit, "parent_page_start")
    page_end = payload_int(hit, "parent_page_end") or page_start
    if page_start is None or page_end is None:
        return False
    return all(page_start <= page <= page_end for page in pages)


def _coverage_child(children: tuple[SearchHit, ...]) -> SearchHit:
    return max(
        enumerate(children),
        key=lambda item: (
            len(str(item[1].payload.get("parent_text") or "")),
            _coverage_chunk_type_priority(item[1]),
            len(searchable_text(item[1])),
            -item[0],
        ),
    )[1]


def _coverage_chunk_type_priority(hit: SearchHit) -> int:
    chunk_type = str(hit.payload.get("chunk_type", "")).lower()
    if chunk_type in {"table", "text", "section", "heading"}:
        return 2
    if chunk_type in {"table_row", "cell"}:
        return 0
    return 1


def merge_exhaustive_coverage_roles(
    ranked_hits: list[SearchHit],
    candidates: list[SearchHit],
    *,
    top_k: int,
) -> list[SearchHit]:
    if not ranked_hits:
        return []
    scored_by_identity = {hit_identity(hit): hit for hit in ranked_hits}
    coverage_hits = [
        scored_by_identity[hit_identity(candidate)]
        for candidate in candidates
        if candidate.payload.get("coverage_role") == EXHAUSTIVE_COVERAGE_ROLE
        and hit_identity(candidate) in scored_by_identity
    ]
    coverage_hits.sort(
        key=lambda hit: int(hit.payload.get("exhaustive_representative_rank", 10**9))
    )
    return unique_hits([ranked_hits[0], *coverage_hits, *ranked_hits])[:top_k]


def coverage_obligations(hits: list[SearchHit]) -> set[str]:
    obligations: set[str] = set()
    for hit in hits:
        if hit.payload.get("coverage_role") != EXHAUSTIVE_COVERAGE_ROLE:
            continue
        raw = hit.payload.get("exhaustive_coverage_obligation_ids")
        if isinstance(raw, list | tuple):
            obligations.update(str(value) for value in raw if str(value).strip())
            continue
        unit_id = hit.payload.get("exhaustive_coverage_unit_id")
        if unit_id not in (None, ""):
            obligations.add(f"unit:{unit_id}")
    return obligations
