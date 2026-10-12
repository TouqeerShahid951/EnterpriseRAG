"""Compile evidence-source plans into the existing retrieval executors."""

from __future__ import annotations

from rag.query.routing.routing_models import (
    EvidenceCapability,
    EvidenceNeed,
    EvidencePlan,
    RetrievalCapability,
    SourceAssignment,
)
from rag.query.sources.source_catalog import query_source_id_for_catalog

INDEXED_CORPUS_SOURCE_ID = "indexed_corpus"
KNOWLEDGE_GRAPH_SOURCE_ID = "knowledge_graph"


def default_evidence_plan(
    query: str,
    *,
    source_decision: object | None,
) -> EvidencePlan:
    """Create the one-need fast path used when decomposition is unnecessary."""

    mode = str(getattr(source_decision, "resolved_mode", "") or "")
    source_ids = tuple(
        str(item)
        for item in getattr(source_decision, "query_source_ids", ())
        if str(item)
    )
    source_id = str(getattr(source_decision, "query_source_id", "") or "")
    if not source_ids and source_id:
        source_ids = (source_id,)
    if not source_ids and getattr(source_decision, "preferred_source", None) == "database":
        preferred_catalog_id = str(
            getattr(source_decision, "preferred_catalog_id", "") or ""
        )
        if preferred_catalog_id:
            source_ids = (query_source_id_for_catalog(preferred_catalog_id),)
    assignments: list[SourceAssignment] = []
    if mode != "db_only":
        assignments.append(
            SourceAssignment(
                source_id=INDEXED_CORPUS_SOURCE_ID,
                capability="indexed_search",
            )
        )
    if mode in {"db_only", "db_first", "hybrid"}:
        assignments.extend(
            SourceAssignment(source_id=item, capability="connector_query")
            for item in source_ids
        )
    if not assignments:
        assignments.append(
            SourceAssignment(
                source_id=INDEXED_CORPUS_SOURCE_ID,
                capability="indexed_search",
            )
        )
    return EvidencePlan(
        needs=(EvidenceNeed(id="need_1", query=query, assignments=tuple(assignments)),)
    )


def compile_retrieval_capabilities(
    capabilities: tuple[RetrievalCapability, ...],
    evidence_plan: EvidencePlan,
) -> tuple[RetrievalCapability, ...]:
    """Map neutral evidence capabilities onto stable executor identifiers."""

    required: list[RetrievalCapability] = ["general_search"]
    evidence_capabilities = {
        assignment.capability
        for need in evidence_plan.needs
        for assignment in need.assignments
        if assignment.required
    }
    if "connector_query" in evidence_capabilities:
        required.append("live_sql")
    if "graph_query" in evidence_capabilities:
        required.append("global_graph")
    if len(evidence_plan.needs) > 1:
        required.append("decomposed_search")
    optional = [
        item
        for item in capabilities
        if item not in {"live_sql", "global_graph"} and item not in required
    ]
    ordered = [*required, *optional]
    return tuple(dict.fromkeys(ordered))[:4]  # type: ignore[return-value]


def evidence_queries(
    evidence_plan: EvidencePlan | None,
    capability: EvidenceCapability,
    *,
    source_id: str | None = None,
) -> tuple[str, ...]:
    if evidence_plan is None:
        return ()
    queries = [
        need.query
        for need in evidence_plan.needs
        if any(
            assignment.capability == capability
            and (source_id is None or assignment.source_id == source_id)
            for assignment in need.assignments
        )
    ]
    return tuple(dict.fromkeys(query for query in queries if query.strip()))


def evidence_need_ids_for_query(
    evidence_plan: EvidencePlan | None,
    query: str,
    capability: EvidenceCapability,
    *,
    source_id: str | None = None,
) -> tuple[str, ...]:
    if evidence_plan is None:
        return ()
    matches = tuple(
        need.id
        for need in evidence_plan.needs
        if need.query == query
        and any(
            assignment.capability == capability
            and (source_id is None or assignment.source_id == source_id)
            for assignment in need.assignments
        )
    )
    if matches or len(evidence_plan.needs) != 1:
        return matches
    only_need = evidence_plan.needs[0]
    return (
        (only_need.id,)
        if any(
            assignment.capability == capability
            and (source_id is None or assignment.source_id == source_id)
            for assignment in only_need.assignments
        )
        else ()
    )


def required_evidence_assignments_for_query(
    evidence_plan: EvidencePlan | None,
    query: str,
    capability: EvidenceCapability,
    *,
    source_ids: set[str] | None = None,
) -> tuple[tuple[str, str, EvidenceCapability], ...]:
    if evidence_plan is None:
        return ()
    matches = tuple(
        (need.id, assignment.source_id, assignment.capability)
        for need in evidence_plan.needs
        if need.query == query
        for assignment in need.assignments
        if assignment.required
        and assignment.capability == capability
        and (source_ids is None or assignment.source_id in source_ids)
    )
    if matches or len(evidence_plan.needs) != 1:
        return matches
    only_need = evidence_plan.needs[0]
    return tuple(
        (only_need.id, assignment.source_id, assignment.capability)
        for assignment in only_need.assignments
        if assignment.required
        and assignment.capability == capability
        and (source_ids is None or assignment.source_id in source_ids)
    )


def required_evidence_assignments(
    evidence_plan: EvidencePlan | None,
) -> set[tuple[str, str, EvidenceCapability]]:
    if evidence_plan is None:
        return set()
    return {
        (need.id, assignment.source_id, assignment.capability)
        for need in evidence_plan.needs
        for assignment in need.assignments
        if assignment.required
    }


def assigned_source_ids(
    evidence_plan: EvidencePlan | None,
    capability: EvidenceCapability,
) -> tuple[str, ...]:
    if evidence_plan is None:
        return ()
    return tuple(
        dict.fromkeys(
            assignment.source_id
            for need in evidence_plan.needs
            for assignment in need.assignments
            if assignment.capability == capability
        )
    )


def assigned_need_ids(
    evidence_plan: EvidencePlan | None,
    capability: EvidenceCapability,
    *,
    source_id: str,
) -> tuple[str, ...]:
    if evidence_plan is None:
        return ()
    return tuple(
        need.id
        for need in evidence_plan.needs
        if any(
            assignment.capability == capability
            and assignment.source_id == source_id
            for assignment in need.assignments
        )
    )
