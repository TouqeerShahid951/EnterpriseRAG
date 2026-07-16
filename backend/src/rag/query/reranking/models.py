"""Immutable results and hierarchy records for query reranking."""

from __future__ import annotations

from dataclasses import dataclass

from ..qdrant import SearchHit

POINT_RERANK_STRATEGY = "point"
EXHAUSTIVE_RERANK_STRATEGY = "exhaustive_hierarchical"
EXHAUSTIVE_CANDIDATE_ORIGIN = "exhaustive_section_expansion"
EXHAUSTIVE_COVERAGE_ROLE = "exhaustive_section_representative"


@dataclass(frozen=True, slots=True)
class RerankResult:
    candidates: tuple[SearchHit, ...]
    ranked_hits: tuple[SearchHit, ...]
    strategy: str = POINT_RERANK_STRATEGY
    candidate_coverage_status: str = "not_applicable"
    evidence_coverage_status: str = "not_applicable"
    stop_reason: str | None = None
    evidence_stop_reason: str | None = None
    required_coverage_obligations: tuple[str, ...] = ()
    covered_coverage_obligations: tuple[str, ...] = ()
    representative_count: int = 0
    representative_scored_count: int = 0
    candidate_wave_count: int = 0


@dataclass(frozen=True, slots=True)
class ExhaustiveUnit:
    key: str
    doc_id: str
    order: int
    children: tuple[SearchHit, ...]
    representative_text: str


@dataclass(frozen=True, slots=True)
class ScoredExhaustiveUnit:
    unit: ExhaustiveUnit
    score: float
    rank: int


@dataclass(frozen=True, slots=True)
class ExhaustiveScope:
    coverage_eligible_unit_keys: frozenset[str]
    referenced_unit_keys: frozenset[str]
    heading_matched_unit_keys: frozenset[str]
    exclusive_scope_unit_keys: frozenset[str]
    semantic_scope_resolved: bool


@dataclass(frozen=True, slots=True)
class ExhaustiveScoring:
    representative_scores: tuple[float, ...]
    candidates: tuple[SearchHit, ...]
    child_scores: tuple[float, ...]
    representative_stop: str | None
    child_stop: str | None
    selection_complete: bool
