"""Community summary generation for GraphRAG."""

from __future__ import annotations

import json

from .models import CommunitySummary, GraphCommunity, SourceRef, stable_id


class CommunitySummarizer:
    def __init__(self, llm: object | None = None, *, model: str | None = None) -> None:
        self.llm = llm
        self.model = model

    def summarize(self, community: GraphCommunity) -> CommunitySummary:
        llm_summary = self._summarize_with_llm(community)
        if llm_summary is not None:
            return llm_summary
        return _fallback_summary(community)

    def _summarize_with_llm(self, community: GraphCommunity) -> CommunitySummary | None:
        generate_json = getattr(self.llm, "generate_json", None)
        if not callable(generate_json):
            return None
        try:
            raw = generate_json(
                prompt=_summary_prompt(community),
                model=self.model,
                system=(
                    "You summarize graph communities for a Microsoft-style GraphRAG system. "
                    "Return only grounded JSON."
                ),
            )
            payload = json.loads(_json_object(raw))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        title = _text(payload.get("title")) or _fallback_title(community)
        summary = _text(payload.get("summary"))
        if not summary:
            return None
        return CommunitySummary(
            id=stable_id("community-summary", community.id, community.level),
            community_id=community.id,
            partition_key=community.partition_key,
            group_path=community.group_path,
            clearance_level=community.clearance_level,
            clearance_rank=community.clearance_rank,
            level=community.level,
            title=title,
            summary=summary,
            important_entities=_strings(payload.get("important_entities"))[:20] or community.entity_names[:20],
            important_relationships=_strings(payload.get("important_relationships"))[:20]
            or community.relationship_descriptions[:20],
            source_refs=_dedupe_refs(community.source_refs),
            entity_ids=community.entity_ids,
        )


def _summary_prompt(community: GraphCommunity) -> str:
    return (
        "Return only a JSON object with keys title, summary, important_entities, important_relationships. "
        "The summary must describe what this graph community is about using only the supplied entities, "
        "relationships, and source ids. Do not add unsupported background.\n\n"
        f"Community id: {community.id}\n"
        f"Entities: {json.dumps(community.entity_names[:80], ensure_ascii=True)}\n"
        f"Relationships: {json.dumps(community.relationship_descriptions[:80], ensure_ascii=True)}\n"
        "Source refs: "
        f"{json.dumps([{'doc_id': ref.doc_id, 'chunk_id': ref.chunk_id} for ref in community.source_refs[:80]], ensure_ascii=True)}"
    )


def _fallback_summary(community: GraphCommunity) -> CommunitySummary:
    entities = community.entity_names[:12]
    relationships = community.relationship_descriptions[:8]
    if relationships:
        summary = (
            f"This community centers on {', '.join(entities[:8])}. "
            f"Key observed relationships include {'; '.join(relationships[:5])}."
        )
    elif entities:
        summary = f"This community centers on recurring mentions of {', '.join(entities[:10])}."
    else:
        summary = "This community contains graph evidence but no high-confidence entity labels."
    return CommunitySummary(
        id=stable_id("community-summary", community.id, community.level),
        community_id=community.id,
        partition_key=community.partition_key,
        group_path=community.group_path,
        clearance_level=community.clearance_level,
        clearance_rank=community.clearance_rank,
        level=community.level,
        title=_fallback_title(community),
        summary=summary,
        important_entities=entities,
        important_relationships=relationships,
        source_refs=_dedupe_refs(community.source_refs),
        entity_ids=community.entity_ids,
    )


def _fallback_title(community: GraphCommunity) -> str:
    if community.entity_names:
        return ", ".join(community.entity_names[:3])
    return "Graph community"


def _json_object(value: str) -> str:
    text = str(value).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    return text[start : end + 1]


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _strings(value: object) -> list[str]:
    return [_text(item) for item in value if _text(item)] if isinstance(value, list) else []


def _dedupe_refs(refs: list[SourceRef]) -> list[SourceRef]:
    seen: set[tuple[str, str]] = set()
    unique: list[SourceRef] = []
    for ref in refs:
        key = (ref.doc_id, ref.chunk_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique
