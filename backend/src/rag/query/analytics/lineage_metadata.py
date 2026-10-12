"""Safe candidate metadata shared by capture and historical detail responses."""

from collections.abc import Mapping


# Titles, text, origins and freeform errors require document access, not analytics access.
CANDIDATE_FIELDS = frozenset({
    "candidate_key", "rank", "point_id", "index_generation_id", "content_hash",
    "evidence_hash", "provenance_kind", "doc_id", "chunk_id", "page", "page_start",
    "page_end", "group_path", "chunk_type", "coverage_unit_id", "representative_rank",
    "representative_score", "retrieval_score", "score", "rerank_score",
    "rerank_adjusted_score", "rerank_status", "low_value_penalty",
})


def candidate_metadata(row: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in row.items() if key in CANDIDATE_FIELDS}


def lineage_metadata(lineage: dict[str, object] | None) -> dict[str, object] | None:
    """Redact legacy candidate rows as well as newly captured rows, without mutating storage."""
    if lineage is None:
        return None
    result = dict(lineage)
    if "stages" in lineage:
        result["stages"] = [
            {**stage, "candidates": [candidate_metadata(row) for row in stage.get("candidates", [])]}
            for stage in lineage["stages"]
        ]
    return result


def expired_lineage(lineage: dict[str, object]) -> dict[str, object]:
    """Retain summary timings while removing shorter-lived evidence diagnostics."""
    return {"schema_version": 1, "status": "expired", "performance": lineage.get("performance", {})}
