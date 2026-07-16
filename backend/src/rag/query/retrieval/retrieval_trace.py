"""Query retrieval lineage with text-free serialization."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Literal

from rag.query.qdrant import SearchHit


RetrievalStageName = Literal[
    "retrieved",
    "rerank_input",
    "reranked",
    "post_policy",
    "final_evidence",
]
RetrievalStageStatus = Literal["completed", "skipped"]


@dataclass(frozen=True, slots=True)
class RetrievalTraceCandidate:
    rank: int
    point_id: str
    doc_id: str | None
    doc_title: str | None
    chunk_id: str
    page: int | None
    page_start: int | None
    page_end: int | None
    group_path: str | None
    chunk_type: str | None
    structured_origin: str | None
    coverage_unit_id: str | None
    coverage_role: str | None
    representative_rank: int | None
    representative_score: float | None
    retrieval_score: float
    rerank_score: float | None
    rerank_adjusted_score: float | None
    rerank_status: str | None
    rerank_error: str | None
    low_value_penalty: float | None
    low_value_reasons: tuple[str, ...]
    origins: tuple[str, ...]
    evidence_text: str = field(default="", repr=False, compare=False)

    def to_row(self) -> dict[str, Any]:
        row = {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name != "evidence_text"
        }
        row["score"] = self.retrieval_score
        if self.low_value_reasons:
            row["low_value_reasons"] = list(self.low_value_reasons)
        else:
            row.pop("low_value_reasons")
        if self.origins:
            row["origins"] = list(self.origins)
        else:
            row.pop("origins")
        return {key: value for key, value in row.items() if value is not None}


@dataclass(frozen=True, slots=True)
class RetrievalTraceStage:
    name: RetrievalStageName
    attempt: int
    candidates: tuple[RetrievalTraceCandidate, ...]
    status: RetrievalStageStatus = "completed"


@dataclass(frozen=True, slots=True)
class RetrievalTrace:
    stages: tuple[RetrievalTraceStage, ...] = ()

    def latest(self, name: RetrievalStageName) -> RetrievalTraceStage | None:
        return next(
            (stage for stage in reversed(self.stages) if stage.name == name), None
        )


def retrieval_trace_stage(
    name: RetrievalStageName,
    hits: list[SearchHit] | tuple[SearchHit, ...],
    *,
    attempt: int,
    status: RetrievalStageStatus = "completed",
) -> RetrievalTraceStage:
    return RetrievalTraceStage(
        name=name,
        attempt=max(0, int(attempt)),
        candidates=tuple(
            _trace_candidate(hit, rank=index) for index, hit in enumerate(hits, start=1)
        ),
        status=status,
    )


def _trace_candidate(hit: SearchHit, *, rank: int) -> RetrievalTraceCandidate:
    payload = hit.payload
    return RetrievalTraceCandidate(
        rank=rank,
        point_id=hit.point_id,
        doc_id=_optional_str(payload.get("doc_id")),
        doc_title=_optional_str(payload.get("doc_title")),
        chunk_id=_optional_str(payload.get("chunk_id")) or hit.point_id,
        page=_optional_int(payload.get("page")),
        page_start=_optional_int(payload.get("page_start")),
        page_end=_optional_int(payload.get("page_end")),
        group_path=_optional_str(payload.get("group_path")),
        chunk_type=_optional_str(payload.get("chunk_type")),
        structured_origin=_optional_str(payload.get("structured_origin")),
        coverage_unit_id=_optional_str(payload.get("exhaustive_coverage_unit_id")),
        coverage_role=_optional_str(payload.get("coverage_role")),
        representative_rank=_optional_int(payload.get("exhaustive_representative_rank")),
        representative_score=_optional_float(payload.get("exhaustive_representative_score")),
        retrieval_score=float(hit.score),
        rerank_score=_optional_float(payload.get("_rerank_score")),
        rerank_adjusted_score=_optional_float(payload.get("_rerank_adjusted_score")),
        rerank_status=_optional_str(payload.get("_rerank_status")),
        rerank_error=_optional_str(payload.get("_rerank_error")),
        low_value_penalty=_optional_float(payload.get("_low_value_penalty")),
        low_value_reasons=_optional_str_tuple(payload.get("_low_value_reasons")),
        origins=_origins(payload),
        evidence_text=_optional_str(payload.get("text")) or "",
    )


def _origins(payload: dict[str, Any]) -> tuple[str, ...]:
    values = (
        payload.get("recall_origin"),
        payload.get("exhaustive_scope_origin"),
        payload.get("structured_origin"),
        payload.get("artifact_scan_origin"),
        payload.get("rerank_candidate_origin"),
        payload.get("coverage_role"),
    )
    return tuple(
        dict.fromkeys(value for item in values if (value := _optional_str(item)))
    )


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str) and value.strip().isdecimal():
        return int(value.strip())
    return None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _optional_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for raw in value if (item := _optional_str(raw)))
