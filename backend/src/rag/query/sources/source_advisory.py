"""Optional LLM advice for automatic query-source preference."""

from __future__ import annotations

import json

from rag.auth.context import UserContext
from rag.query.sources.source_catalog import VisibleDocumentSource, VisibleQuerySource
from rag.query.sources.source_matching import _SourcePreference, _compact_query


def _advisory_llm_source_router(
    *,
    query: str,
    user: UserContext,
    sources: list[VisibleQuerySource],
    documents: list[VisibleDocumentSource],
    session_turns: list[dict[str, object]],
    config: object | None,
    llm: object | None,
    routing_model: str | None,
    deterministic: _SourcePreference,
) -> _SourcePreference | None:
    if not bool(getattr(config, "rag_source_router_llm_enabled", False)):
        return None
    if llm is None or not sources or not documents:
        return None
    if (
        deterministic.preferred_source != "balanced"
        and deterministic.confidence >= 0.70
    ):
        return None
    generator = getattr(llm, "generate_json", None)
    if generator is None:
        return None
    try:
        raw = generator(
            prompt=_source_router_prompt(
                query=query,
                user=user,
                sources=sources,
                documents=documents,
                session_turns=session_turns,
                deterministic=deterministic,
            ),
            model=routing_model,
            system="You choose source priority for a retrieval system without excluding available sources.",
            max_tokens=512,
        )
        payload = json.loads(str(raw))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    confidence = _float(payload.get("confidence"))
    threshold = float(
        getattr(config, "rag_source_router_llm_min_confidence", 0.60) or 0.60
    )
    if confidence < threshold:
        return None
    preferred = str(payload.get("preferred_source") or "").strip().lower()
    if preferred not in {"database", "corpus", "balanced"}:
        return None
    catalog_id = _valid_router_catalog_id(
        payload.get("preferred_catalog_id"), sources
    )
    reason = _compact_query(str(payload.get("reason") or "llm_source_router"))[:240]
    return _SourcePreference(
        preferred,  # type: ignore[arg-type]
        confidence,
        reason,
        preferred_catalog_id=catalog_id,
        router_mode="llm",
    )


def _source_router_prompt(
    *,
    query: str,
    user: UserContext,
    sources: list[VisibleQuerySource],
    documents: list[VisibleDocumentSource],
    session_turns: list[dict[str, object]],
    deterministic: _SourcePreference,
) -> str:
    payload = {
        "query": query,
        "workspace_group_paths": list(user.group_paths),
        "deterministic_preference": {
            "preferred_source": deterministic.preferred_source,
            "confidence": deterministic.confidence,
            "reason": deterministic.reason,
        },
        "visible_database_catalogs": [
            {
                "id": source.target_id,
                "name": source.name,
                "description": source.description,
                "connector_type": source.connector_type,
                "summary": _compact_query(source.match_text)[:900],
            }
            for source in sources[:6]
        ],
        "visible_documents": [
            {
                "id": document.id,
                "title": document.title,
                "summary": _compact_query(document.match_text)[:700],
            }
            for document in documents[:8]
        ],
        "recent_turns": [
            {
                "query": str(turn.get("query") or "")[:240],
                "answer": str(turn.get("answer") or "")[:300],
                "source_mode": turn.get("source_mode"),
                "preferred_source": turn.get("preferred_source"),
            }
            for turn in session_turns[-3:]
        ],
    }
    return (
        "Choose which source should be prioritized for this Auto query. "
        "Do not exclude sources; Auto will still search both database and documents. "
        "Return only JSON with keys preferred_source, preferred_catalog_id, confidence, and reason. "
        'preferred_source must be one of "database", "corpus", or "balanced". '
        "preferred_catalog_id must be one of the visible database catalog ids or null.\n\n"
        f"{json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)}"
    )


def _valid_router_catalog_id(
    value: object, sources: list[VisibleQuerySource]
) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    valid_ids = {source.target_id for source in sources}
    valid_source_ids = {source.id: source.target_id for source in sources}
    if candidate in valid_ids:
        return candidate
    return valid_source_ids.get(candidate)


def _float(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
