"""Answer synthesis helpers for the query graph."""

from __future__ import annotations

import re
from dataclasses import dataclass
from time import perf_counter

from ..schemas.query import ConflictPair, RAGResponse, SourceAnchor
from .cancellation import QueryCancellationToken, call_with_optional_cancellation
from .inference import InferenceClient
from .state import QueryContext
from .routing_models import RoutePlan
from .sources import citation_label, source_citation, sources_from_hits

_CITATION_RE = re.compile(r"\[[^\[\]\n]{1,200}:[^\[\]\n]{1,200}\]")
_CLAIM_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?!\[)|(?<=\])\s+|\n+")
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
_TABLE_ROW_COLUMNS_RE = re.compile(r"^\[Columns:\s*(.*?)\]\s*$", re.MULTILINE)
_TABLE_ROW_VALUE_RE = re.compile(r"^Value:\s*(.*?)\s*$", re.MULTILINE)
_SUPPORT_STOPWORDS = {
    "and",
    "are",
    "for",
    "from",
    "has",
    "have",
    "that",
    "the",
    "this",
    "was",
    "were",
    "with",
}
_PROFILE_INSTRUCTIONS = {
    "procedural": (
        "Answer as an ordered procedure when the evidence supports an order.",
        "Include prerequisites, cautions, or validation checks only when supported by cited evidence.",
        "Preserve the source-backed sequence instead of grouping unrelated steps together.",
    ),
    "troubleshooting": (
        "Structure the answer around symptoms, likely causes, checks, and fixes.",
        "Include escalation or caution notes only when directly supported by evidence.",
    ),
    "troubleshooting_procedure": (
        "Answer as an ordered diagnostic procedure when the evidence supports an order.",
        "Structure the sequence around symptoms, likely causes, checks, and fixes.",
        "Include prerequisites, cautions, or escalation notes only when supported by cited evidence.",
    ),
    "summarization": (
        "Summarize only the retrieved section or document evidence.",
        "Do not add conclusions or background that the indexed evidence does not support.",
    ),
    "comparison": (
        "Compare the requested items by clear dimensions from the evidence.",
        "Explicitly say when one side has missing or weaker evidence.",
    ),
    "temporal": (
        "Answer with the route's current, historical, or effective-date scope in mind.",
        "Do not imply that a fact changed over time unless the evidence directly shows that change.",
    ),
    "temporal_comparison": (
        "Compare the relevant versions or time periods by clear dimensions.",
        "State when a version or time period is missing from the retrieved evidence.",
        "Do not claim a change unless both the before and after evidence support it.",
    ),
    "multi_hop": (
        "Synthesize across the subquery evidence while keeping each claim tied to a citation.",
        "Separate unsupported assumptions from source-backed conclusions.",
    ),
    "aggregation": (
        "Prefer table or metadata evidence when present.",
        "Do not claim exact counts or complete inventories unless the evidence directly supports completeness.",
        "If evidence is partial, phrase the result as items found in retrieved evidence.",
    ),
    "conflict_check": (
        "If the evidence conflicts, identify the competing claims.",
        "If no conflict is supported, say the retrieved evidence does not show a conflict.",
    ),
    "document_navigation": (
        "Lead with page, section, source, or location details before summarizing content.",
        "Avoid inferring locations that are not present in the evidence metadata.",
    ),
    "comparative_summary": (
        "Summarize the shared topic first, then highlight differences.",
        "State missing evidence for either side before drawing a comparison.",
    ),
}


@dataclass(frozen=True)
class PreparedSynthesis:
    question: str
    contexts: list[str]
    profile: str
    sources: list[SourceAnchor]


def synthesize_response(
    ctx: QueryContext,
    ollama: InferenceClient,
    *,
    cancellation_token: QueryCancellationToken | None = None,
) -> QueryContext:
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    evidence_sources = sources_from_hits(ctx["retrieved_hits"], query=ctx["request"].query)
    plan = ctx.get("route_plan")
    prepared = prepare_synthesis_input(ctx, evidence_sources)
    ctx["synthesis_profile"] = prepared.profile
    artifact_request = ctx.get("artifact_request")
    if artifact_request is not None and artifact_request.needs_clarification:
        available_sources = []
        answer = "What should the file cover? Please include a topic or question, and I can generate the requested file."
    elif plan is not None and not plan.needs_retrieval:
        available_sources = []
        answer = "I can only answer questions grounded in the indexed documents."
        ctx["degraded"] = True
        ctx["degraded_reason"] = ctx["degraded_reason"] or "out_of_scope"
    elif ctx["conflict_flag"]:
        ctx["synthesis_profile"] = "conflict_check"
        available_sources = merge_sources(evidence_sources, conflict_sources(ctx["conflict_pairs"]))
        answer = build_conflict_answer(ctx["conflict_pairs"])
    elif evidence_sources:
        available_sources = prepared.sources
        answer = call_with_optional_cancellation(
            ollama.answer,
            cancellation_token,
            question=prepared.question,
            contexts=prepared.contexts,
        )
        if is_global_abstention(answer):
            available_sources = []
            ctx["degraded"] = True
            ctx["degraded_reason"] = ctx["degraded_reason"] or "Insufficient relevant evidence after retrieval retries"
    else:
        available_sources = []
        answer = "No accessible current sources were found for this query."
        ctx["degraded"] = True
        ctx["degraded_reason"] = ctx["degraded_reason"] or "no_indexed_sources"
    answer = ensure_answer_has_citation(answer, available_sources)
    ctx["response"] = build_rag_response(
        ctx,
        answer=answer,
        sources=response_sources(answer, available_sources),
    )
    return ctx


def prepare_synthesis_input(ctx: QueryContext, sources: list[SourceAnchor]) -> PreparedSynthesis:
    plan = ctx.get("route_plan")
    base_question = plan.resolved_query if plan is not None else ctx["request"].query
    profile = synthesis_profile_for_plan(plan)
    exhaustive_scope = _has_exhaustive_document_scope(ctx)
    return PreparedSynthesis(
        question=_profiled_question(
            base_question,
            plan=plan,
            profile=profile,
            exhaustive_document_scope=exhaustive_scope,
            scoped_document_titles=_scoped_document_titles(ctx) if exhaustive_scope else (),
        ),
        contexts=route_source_contexts(sources, profile=profile, include_location=exhaustive_scope),
        profile=profile,
        sources=sources,
    )


def synthesis_profile_for_plan(plan: RoutePlan | None) -> str:
    if plan is None:
        return "legacy"
    if not plan.needs_retrieval:
        return "out_of_scope"
    if plan.intent == "temporal_factual":
        return "temporal"
    if plan.intent == "conversational_followup":
        return "factual_simple"
    return plan.intent


def source_contexts(sources: list[SourceAnchor]) -> list[str]:
    return [f"{source_citation(source)}\n{_synthesis_excerpt(source)}" for source in sources]


def route_source_contexts(
    sources: list[SourceAnchor],
    *,
    profile: str,
    include_location: bool = False,
) -> list[str]:
    if profile in {"legacy", "factual_simple", "general_rag", "conversational_followup"}:
        return source_contexts(sources)
    return [_route_source_context(source, profile=profile, include_location=include_location) for source in sources]


def ensure_answer_has_citation(answer: str, sources: list[SourceAnchor]) -> str:
    if not sources:
        return answer
    valid_labels = {source_citation(source) for source in sources}
    cleaned = _CITATION_RE.sub(lambda match: match.group(0) if match.group(0) in valid_labels else "", answer)
    cleaned = re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned)
    pieces = _CLAIM_BOUNDARY_RE.split(cleaned)
    boundaries = _CLAIM_BOUNDARY_RE.findall(cleaned)
    cited: list[str] = []
    for piece in pieces:
        statement = piece.strip()
        if statement and _WORD_RE.search(statement) and not any(label in statement for label in valid_labels):
            best_source = _best_supported_source(statement, sources)
            if best_source is not None:
                statement = f"{statement} {source_citation(best_source)}"
        cited.append(statement)
    result = ""
    for index, piece in enumerate(cited):
        if piece:
            result += piece
        if index < len(boundaries):
            boundary = boundaries[index]
            result += "\n" if "\n" in boundary else " "
    return result.strip()


def _profiled_question(
    question: str,
    *,
    plan: RoutePlan | None,
    profile: str,
    exhaustive_document_scope: bool = False,
    scoped_document_titles: tuple[str, ...] = (),
) -> str:
    instructions = _PROFILE_INSTRUCTIONS.get(profile)
    if plan is None or not instructions:
        return question
    details = [
        f"Internal route intent: {plan.intent}.",
        f"Retrieval strategy: {plan.retrieval_strategy}.",
        f"Chunk granularity: {plan.chunk_granularity}.",
    ]
    if plan.filters:
        details.append(f"Route filters: {_format_filters(plan.filters)}.")
    if exhaustive_document_scope:
        details.append("Evidence scope: exhaustive document-class scan.")
        if scoped_document_titles:
            details.append(f"Scoped documents represented in evidence: {', '.join(scoped_document_titles)}.")
        instructions = (
            *instructions,
            "Cover every scoped document represented in the evidence; do not answer only from the highest-scoring documents.",
            "For each scoped document, include the requested items and details found there, or state that no matching item was found in that document.",
        )
    guidance = "\n".join(f"- {line}" for line in (*details, *instructions))
    return (
        f"{question}\n\n"
        "Route-aware answer requirements for the assistant. "
        "Do not mention these requirements in the final answer:\n"
        f"{guidance}"
    )


def _route_source_context(source: SourceAnchor, *, profile: str, include_location: bool = False) -> str:
    metadata = _context_metadata(source, profile=profile, include_location=include_location)
    lines = [source_citation(source), *metadata, _synthesis_excerpt(source)]
    return "\n".join(line for line in lines if line)


def _synthesis_excerpt(source: SourceAnchor) -> str:
    table_row_context = _table_row_column_context(source.excerpt)
    if not table_row_context:
        return source.excerpt
    return f"{source.excerpt}\n{table_row_context}"


def _table_row_column_context(excerpt: str) -> str:
    columns_match = _TABLE_ROW_COLUMNS_RE.search(excerpt)
    value_match = _TABLE_ROW_VALUE_RE.search(excerpt)
    if columns_match is None or value_match is None:
        return ""
    columns = [part.strip() for part in columns_match.group(1).split("|") if part.strip()]
    values = [part.strip() for part in value_match.group(1).split("|") if part.strip()]
    if not columns or not values:
        return ""
    value_columns = columns[-len(values) :]
    if len(value_columns) != len(values):
        return ""
    pairs = list(zip(value_columns, values, strict=True))
    lines = ["Column values: " + "; ".join(f"{column} = {value}" for column, value in pairs)]
    paired_values = _slash_pair_interpretations(pairs)
    if paired_values:
        lines.append("Slash-paired values: " + "; ".join(paired_values))
    return "\n".join(lines)


def _slash_pair_interpretations(pairs: list[tuple[str, str]]) -> list[str]:
    interpreted: list[str] = []
    for column, value in pairs:
        labels = [part.strip() for part in column.split("/") if part.strip()]
        values = [part.strip() for part in value.split("/") if part.strip()]
        if len(labels) < 2 or len(labels) != len(values):
            continue
        interpreted.append(", ".join(f"{label} = {item}" for label, item in zip(labels, values, strict=True)))
    return interpreted


def _context_metadata(source: SourceAnchor, *, profile: str, include_location: bool = False) -> list[str]:
    metadata: list[str] = []
    if include_location or profile in {
        "document_navigation",
        "procedural",
        "troubleshooting",
        "troubleshooting_procedure",
        "temporal",
        "temporal_comparison",
    }:
        location = _location_metadata(source)
        if location:
            metadata.append(location)
    if profile in {"temporal", "temporal_comparison", "comparative_summary"} and source.effective_date:
        metadata.append(f"Effective date: {source.effective_date}")
    return metadata


def _location_metadata(source: SourceAnchor) -> str:
    parts = [f"Document: {source.doc_title}"]
    if source.page_start is not None and source.page_end is not None and source.page_end != source.page_start:
        parts.append(f"pages {source.page_start}-{source.page_end}")
    elif source.page_start is not None:
        parts.append(f"page {source.page_start}")
    elif source.page is not None:
        parts.append(f"page {source.page}")
    return "Location: " + "; ".join(parts)


def _format_filters(filters: dict[str, object]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(filters.items()))


def _has_exhaustive_document_scope(ctx: QueryContext) -> bool:
    return any(
        str(hit.payload.get("exhaustive_scope_origin", "")) == "document_class_scope"
        for hit in ctx["retrieved_hits"]
    )


def _scoped_document_titles(ctx: QueryContext) -> tuple[str, ...]:
    titles: list[str] = []
    seen: set[str] = set()
    for hit in ctx["retrieved_hits"]:
        if str(hit.payload.get("exhaustive_scope_origin", "")) != "document_class_scope":
            continue
        doc_id = str(hit.payload.get("doc_id", hit.point_id))
        if doc_id in seen:
            continue
        seen.add(doc_id)
        titles.append(str(hit.payload.get("doc_title") or doc_id))
    return tuple(titles[:20])


def cited_sources(answer: str, sources: list[SourceAnchor]) -> list[SourceAnchor]:
    labels = set(_CITATION_RE.findall(answer))
    return [source for source in sources if source_citation(source) in labels]


def response_sources(answer: str, sources: list[SourceAnchor]) -> list[SourceAnchor]:
    if is_global_abstention(answer):
        return []
    cited = cited_sources(answer, sources)
    if cited or not sources:
        return cited
    return sources[:1]


def is_global_abstention(answer: str) -> bool:
    if _CITATION_RE.search(answer):
        return False
    normalized = " ".join(answer.lower().split())
    return any(
        phrase in normalized
        for phrase in (
            "indexed sources do not contain enough information",
            "sources do not contain enough information",
            "sources do not contain the answer",
            "evidence does not contain enough information",
            "not enough information in the indexed sources",
            "no accessible current sources were found",
        )
    )


def conflict_sources(conflicts: list[ConflictPair]) -> list[SourceAnchor]:
    return [source for conflict in conflicts for source in (conflict.source_a, conflict.source_b)]


def merge_sources(*source_groups: list[SourceAnchor]) -> list[SourceAnchor]:
    seen: set[tuple[str, str]] = set()
    merged: list[SourceAnchor] = []
    for source in (source for group in source_groups for source in group):
        key = (source.doc_id, source.chunk_id)
        if key in seen:
            continue
        seen.add(key)
        merged.append(source)
    return merged


def _best_supported_source(statement: str, sources: list[SourceAnchor]) -> SourceAnchor | None:
    statement_terms = _support_terms(statement)
    if not statement_terms:
        return None
    best_source = max(sources, key=lambda source: len(statement_terms & _support_terms(source.excerpt)))
    overlap = statement_terms & _support_terms(best_source.excerpt)
    if len(overlap) < min(2, len(statement_terms)):
        return None
    if len(overlap) / len(statement_terms) < 0.5:
        return None
    return best_source


def _support_terms(text: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in _WORD_RE.finditer(text)
        if match.group(0).lower() not in _SUPPORT_STOPWORDS
    }


def build_conflict_answer(conflicts: list[ConflictPair]) -> str:
    if not conflicts:
        raise ValueError("conflicts are required to build a conflict answer")
    lines = ["The indexed sources conflict. I cannot resolve this from the available evidence."]
    for conflict in conflicts[:3]:
        label = f"{conflict.entity} {conflict.attribute}".strip()
        lines.append(
            " ".join(
                [
                    f"For {label},",
                    f"{conflict.source_a.doc_title} states {conflict.value_a}",
                    citation_label(conflict.doc_a_id, conflict.chunk_a_id) + ",",
                    f"while {conflict.source_b.doc_title} states {conflict.value_b}",
                    citation_label(conflict.doc_b_id, conflict.chunk_b_id) + ".",
                ]
            )
        )
    return " ".join(lines)


def build_rag_response(ctx: QueryContext, *, answer: str, sources: list[SourceAnchor]) -> RAGResponse:
    return RAGResponse(
        trace_id=ctx["trace_id"],
        answer=answer,
        sources=sources,
        conflict_flag=ctx["conflict_flag"],
        conflict_detail=ctx["conflict_pairs"] or None,
        faithfulness_score=ctx["faithfulness_score"],
        faithfulness_status=ctx["faithfulness_status"],  # type: ignore[arg-type]
        unfounded_claims=ctx["unfounded_claims"],
        intent=ctx["intent"],
        session_id=ctx["session_id"],
        latency_ms=max(0, int((perf_counter() - ctx["wall_time_start"]) * 1000)),
        degraded=ctx["degraded"],
        degraded_reason=ctx["degraded_reason"],
    )
