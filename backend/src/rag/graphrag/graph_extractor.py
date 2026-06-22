"""Chunk-level GraphRAG extraction."""

from __future__ import annotations

import json
import re
from typing import Any

from .models import (
    ChunkRecord,
    GraphClaim,
    GraphEntity,
    GraphExtractionResult,
    GraphMention,
    GraphRelationship,
    normalized_name,
    stable_id,
)

_ENTITY_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9&./'-]*(?:\s+[A-Z][A-Za-z0-9&./'-]*){0,5}|[A-Z]{2,}[-_/A-Z0-9]{1,})\b"
)
_LOW_VALUE_ENTITIES = {
    "A",
    "An",
    "And",
    "As",
    "At",
    "By",
    "For",
    "From",
    "In",
    "It",
    "Of",
    "On",
    "Or",
    "The",
    "This",
    "To",
    "With",
}
_MAX_ENTITIES = 12
_MAX_RELATIONSHIPS = 16
_MAX_CLAIMS = 8


class GraphExtractor:
    """Extract domain-agnostic entities, mentions, relationships, and claims."""

    def __init__(self, llm: object | None = None, *, model: str | None = None) -> None:
        self.llm = llm
        self.model = model

    def extract(self, chunk: ChunkRecord) -> GraphExtractionResult:
        llm_result = self._extract_with_llm(chunk)
        if llm_result is not None and (llm_result.entities or llm_result.relationships or llm_result.claims):
            return llm_result
        return self._extract_deterministic(chunk)

    def _extract_with_llm(self, chunk: ChunkRecord) -> GraphExtractionResult | None:
        generate_json = getattr(self.llm, "generate_json", None)
        if not callable(generate_json):
            return None
        try:
            raw = generate_json(
                prompt=_extraction_prompt(chunk.text),
                model=self.model,
                system=(
                    "You are a strict JSON knowledge graph extraction API. "
                    "Extract only facts supported by the supplied chunk."
                ),
            )
        except Exception:
            return None
        try:
            payload = json.loads(_json_object(raw))
        except (TypeError, json.JSONDecodeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        return _result_from_payload(chunk, payload)

    def _extract_deterministic(self, chunk: ChunkRecord) -> GraphExtractionResult:
        partition = chunk.partition_key
        candidates: list[GraphEntity] = []
        seen: set[str] = set()
        for match in _ENTITY_RE.finditer(chunk.text):
            name = _clean_entity(match.group(0))
            if not _is_useful_entity(name):
                continue
            entity = GraphEntity.from_name(
                name=name,
                entity_type=_deterministic_entity_type(name),
                partition=partition,
                confidence=0.45,
            )
            if entity.id in seen:
                continue
            seen.add(entity.id)
            candidates.append(entity)
            if len(candidates) >= _MAX_ENTITIES:
                break
        mentions = [
            _mention_for_entity(entity, chunk=chunk, evidence_text=_evidence_window(chunk.text, entity.name), confidence=entity.confidence)
            for entity in candidates
        ]
        relationships: list[GraphRelationship] = []
        for left, right in zip(candidates, candidates[1:]):
            relationships.append(
                GraphRelationship(
                    id=stable_id("graph-rel", chunk.chunk_id, left.id, right.id, "co_occurs_with"),
                    source_entity_id=left.id,
                    target_entity_id=right.id,
                    source_name=left.name,
                    target_name=right.name,
                    type="co_occurs_with",
                    description=f"{left.name} appears near {right.name}.",
                    doc_id=chunk.doc_id,
                    chunk_id=chunk.chunk_id,
                    evidence_text=_relationship_evidence(chunk.text, left.name, right.name),
                    confidence=0.35,
                    weight=1.0,
                )
            )
            if len(relationships) >= _MAX_RELATIONSHIPS:
                break
        return GraphExtractionResult(
            doc_id=chunk.doc_id,
            chunk_id=chunk.chunk_id,
            entities=candidates,
            mentions=mentions,
            relationships=relationships,
            claims=[],
        )


def _extraction_prompt(text: str) -> str:
    return (
        "Return only a JSON object with keys entities, relationships, claims.\n"
        "entities: array of {name, type, evidence_text, confidence}.\n"
        "relationships: array of {source, target, type, description, evidence_text, confidence}.\n"
        "claims: array of {entity, claim, evidence_text, confidence}.\n"
        "Use generic entity and relationship types. Do not invent domain-specific schema keys. "
        "Keep evidence_text as a short exact or near-exact supporting span from the chunk. "
        "If uncertain, omit the item.\n\n"
        f"Chunk:\n{text[:6000]}"
    )


def _result_from_payload(chunk: ChunkRecord, payload: dict[str, Any]) -> GraphExtractionResult:
    partition = chunk.partition_key
    entities_by_name: dict[str, GraphEntity] = {}
    for raw in _dict_items(payload.get("entities"))[:_MAX_ENTITIES]:
        name = _clean_entity(str(raw.get("name", "")))
        if not _is_useful_entity(name):
            continue
        entity = GraphEntity.from_name(
            name=name,
            entity_type=str(raw.get("type") or "unknown"),
            partition=partition,
            confidence=_float(raw.get("confidence"), 0.65),
        )
        entities_by_name[entity.normalized_name] = entity
    relationships: list[GraphRelationship] = []
    for raw in _dict_items(payload.get("relationships"))[:_MAX_RELATIONSHIPS]:
        source_name = _clean_entity(str(raw.get("source", "")))
        target_name = _clean_entity(str(raw.get("target", "")))
        if not _is_useful_entity(source_name) or not _is_useful_entity(target_name):
            continue
        source = entities_by_name.get(normalized_name(source_name)) or GraphEntity.from_name(
            name=source_name,
            entity_type="unknown",
            partition=partition,
            confidence=0.5,
        )
        target = entities_by_name.get(normalized_name(target_name)) or GraphEntity.from_name(
            name=target_name,
            entity_type="unknown",
            partition=partition,
            confidence=0.5,
        )
        entities_by_name.setdefault(source.normalized_name, source)
        entities_by_name.setdefault(target.normalized_name, target)
        rel_type = _relationship_type(str(raw.get("type") or "related_to"))
        relationships.append(
            GraphRelationship(
                id=stable_id("graph-rel", chunk.chunk_id, source.id, target.id, rel_type, str(raw.get("description", ""))),
                source_entity_id=source.id,
                target_entity_id=target.id,
                source_name=source.name,
                target_name=target.name,
                type=rel_type,
                description=str(raw.get("description") or f"{source.name} is related to {target.name}.").strip(),
                doc_id=chunk.doc_id,
                chunk_id=chunk.chunk_id,
                evidence_text=str(raw.get("evidence_text") or _relationship_evidence(chunk.text, source.name, target.name)).strip(),
                confidence=_float(raw.get("confidence"), 0.6),
                weight=max(0.1, _float(raw.get("confidence"), 0.6)),
            )
        )
    entities = list(entities_by_name.values())
    mentions = [
        _mention_for_entity(
            entity,
            chunk=chunk,
            evidence_text=_evidence_for_entity(payload, entity.name) or _evidence_window(chunk.text, entity.name),
            confidence=entity.confidence,
        )
        for entity in entities
    ]
    claims: list[GraphClaim] = []
    for raw in _dict_items(payload.get("claims"))[:_MAX_CLAIMS]:
        entity_name = _clean_entity(str(raw.get("entity", "")))
        claim_text = str(raw.get("claim", "")).strip()
        if not entity_name or not claim_text:
            continue
        entity = entities_by_name.get(normalized_name(entity_name)) or GraphEntity.from_name(
            name=entity_name,
            entity_type="unknown",
            partition=partition,
            confidence=0.5,
        )
        claims.append(
            GraphClaim(
                id=stable_id("graph-claim", chunk.chunk_id, entity.id, claim_text),
                entity_id=entity.id,
                entity_name=entity.name,
                claim=claim_text,
                doc_id=chunk.doc_id,
                chunk_id=chunk.chunk_id,
                evidence_text=str(raw.get("evidence_text") or _evidence_window(chunk.text, entity.name)).strip(),
                confidence=_float(raw.get("confidence"), 0.55),
            )
        )
        entities_by_name.setdefault(entity.normalized_name, entity)
    return GraphExtractionResult(
        doc_id=chunk.doc_id,
        chunk_id=chunk.chunk_id,
        entities=list(entities_by_name.values()),
        mentions=mentions,
        relationships=relationships,
        claims=claims,
    )


def _mention_for_entity(entity: GraphEntity, *, chunk: ChunkRecord, evidence_text: str, confidence: float) -> GraphMention:
    return GraphMention(
        id=stable_id("graph-mention", chunk.chunk_id, entity.id),
        entity_id=entity.id,
        entity_name=entity.name,
        doc_id=chunk.doc_id,
        chunk_id=chunk.chunk_id,
        evidence_text=evidence_text,
        confidence=confidence,
    )


def _json_object(value: str) -> str:
    text = str(value).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    return text[start : end + 1]


def _dict_items(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _evidence_for_entity(payload: dict[str, Any], name: str) -> str:
    for raw in _dict_items(payload.get("entities")):
        if _clean_entity(str(raw.get("name", ""))).lower() == name.lower():
            evidence = str(raw.get("evidence_text", "")).strip()
            if evidence:
                return evidence
    return ""


def _clean_entity(value: str) -> str:
    return " ".join(value.replace("\n", " ").strip(" ,.;:()[]{}").split())[:160]


def _is_useful_entity(name: str) -> bool:
    if len(name) < 2 or name in _LOW_VALUE_ENTITIES:
        return False
    return any(ch.isalnum() for ch in name)


def _deterministic_entity_type(name: str) -> str:
    if re.search(r"\b(?:Ltd|Limited|Company|Department|Ministry|Authority|Office|Unit|Agency)\b", name, re.I):
        return "organization"
    if re.search(r"\b(?:District|City|Province|Road|Street|Karachi|Lahore|Islamabad)\b", name, re.I):
        return "location"
    if re.fullmatch(r"[A-Z0-9][A-Z0-9_/-]{2,}", name):
        return "identifier"
    return "entity"


def _relationship_type(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    return normalized or "related_to"


def _evidence_window(text: str, needle: str, *, radius: int = 140) -> str:
    index = text.lower().find(needle.lower())
    if index < 0:
        return text.strip()[: radius * 2]
    start = max(0, index - radius)
    end = min(len(text), index + len(needle) + radius)
    return text[start:end].strip()


def _relationship_evidence(text: str, left: str, right: str) -> str:
    left_index = text.lower().find(left.lower())
    right_index = text.lower().find(right.lower())
    if left_index < 0 or right_index < 0:
        return text.strip()[:300]
    start = max(0, min(left_index, right_index) - 120)
    end = min(len(text), max(left_index + len(left), right_index + len(right)) + 120)
    return text[start:end].strip()


def _float(value: object, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default
