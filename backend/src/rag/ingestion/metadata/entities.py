"""Named-entity extraction for ingestion metadata."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any

from rag.shared.runtime_offline import apply_runtime_offline_defaults

from .models import NamedEntity

ENTITY_TYPES = [
    "person",
    "organization",
    "location",
    "date",
    "equipment",
    "policy_reference",
    "monetary_value",
    "percentage",
    "designation",
    "project_code",
]

_POLICY_REF_RE = re.compile(r"\b(?:[A-Z]{2,}-[\d/]+|(?:SOP|Circular|Notification|Order)\s*(?:No\.?\s*)?\d{1,4}[/\-]\d{2,4})\b", re.IGNORECASE)
_MONEY_RE = re.compile(r"\b(?:PKR|USD|EUR|GBP|\$|Rs\.?)\s?[\d,]+(?:\.\d+)?(?:\s?(?:million|billion|crore|lac|lakh))?\b", re.IGNORECASE)
_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%\b")
_DESIGNATION_RE = re.compile(r"\b(?:BPS-\d{1,2}|Grade\s+\d{1,2}\s+(?:Officer|Staff|Employee)?)\b", re.IGNORECASE)
_PROJECT_RE = re.compile(r"\b(?:PRJ|PROJ|PROJECT)-[A-Z0-9-]+\b", re.IGNORECASE)
_ORG_RE = re.compile(r"\b(?:Ministry|Department|Directorate|Authority|Commission|Vendor|Company|Co\.|Ltd\.|Limited|Office)\s+of\s+[A-Z][A-Za-z &.-]+|\b[A-Z][A-Za-z &.-]+(?:Ministry|Department|Authority|Commission|Company|Ltd\.|Limited)\b")
_LOCATION_RE = re.compile(r"\b(?:Islamabad|Karachi|Lahore|Peshawar|Quetta|Rawalpindi|District\s+\d+\s+Office)\b", re.IGNORECASE)


def extract_named_entities(text: str, *, use_gliner: bool = False) -> list[NamedEntity]:
    if use_gliner:
        entities = _extract_gliner(text)
        if entities:
            return _dedupe_entities(entities)
    return _dedupe_entities(_regex_entities(text))


def _extract_gliner(text: str) -> list[NamedEntity]:
    try:
        model = _gliner_model()
    except Exception:
        return []
    try:
        raw_entities = model.predict_entities(text[:20000], ENTITY_TYPES, threshold=0.45)
    except Exception:
        return []
    entities: list[NamedEntity] = []
    for raw in raw_entities:
        if not isinstance(raw, dict):
            continue
        entity_text = str(raw.get("text", "")).strip()
        entity_type = str(raw.get("label") or raw.get("type") or "").strip().lower()
        if entity_text and entity_type:
            entities.append(
                NamedEntity(
                    text=entity_text,
                    type=entity_type,
                    start=_int_or_none(raw.get("start")),
                    end=_int_or_none(raw.get("end")),
                )
            )
    return entities


@lru_cache(maxsize=1)
def _gliner_model() -> Any:
    apply_runtime_offline_defaults()
    from gliner import GLiNER

    return GLiNER.from_pretrained(os.getenv("GLINER_MODEL", "urchade/gliner_medium-v2.1"))


def _regex_entities(text: str) -> list[NamedEntity]:
    specs = [
        ("policy_reference", _POLICY_REF_RE),
        ("monetary_value", _MONEY_RE),
        ("percentage", _PERCENT_RE),
        ("designation", _DESIGNATION_RE),
        ("project_code", _PROJECT_RE),
        ("organization", _ORG_RE),
        ("location", _LOCATION_RE),
    ]
    entities: list[NamedEntity] = []
    for entity_type, pattern in specs:
        for match in pattern.finditer(text):
            entities.append(NamedEntity(match.group(0).strip(), entity_type, match.start(), match.end()))
    return entities


def _dedupe_entities(entities: list[NamedEntity], *, limit: int = 100) -> list[NamedEntity]:
    seen: set[tuple[str, str, int | None]] = set()
    unique: list[NamedEntity] = []
    for entity in entities:
        key = (entity.text.lower(), entity.type.lower(), entity.start)
        if key in seen:
            continue
        seen.add(key)
        unique.append(entity)
        if len(unique) >= limit:
            break
    return unique


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None
