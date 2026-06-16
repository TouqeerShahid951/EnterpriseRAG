"""Metadata extraction orchestration."""

from __future__ import annotations

from datetime import date
from typing import Any

from ..messages import IngestJobPayload
from .crossrefs import extract_cross_references
from .dates import days_between, extract_dates
from .entities import extract_named_entities
from .language import detect_language
from .models import DocumentMetadataBundle
from .topics import classify_doc_type, classify_topics

DOC_TYPES = {"policy", "procedure", "report", "contract", "memo", "manual", "other"}


def build_metadata_bundle(
    *,
    text: str,
    job: IngestJobPayload,
    llm_metadata: dict[str, Any],
    topic_taxonomy: tuple[str, ...],
    use_gliner: bool,
) -> DocumentMetadataBundle:
    auto_topics, topic_scores = classify_topics(text, topic_taxonomy)
    auto_doc_type, auto_doc_type_confidence = classify_doc_type(text)
    extracted_dates = extract_dates(text)
    language = detect_language(text)
    llm_topics = _string_list(llm_metadata.get("llm_topics") or llm_metadata.get("topics"))[:8]
    topics = _unique([*auto_topics, *_taxonomy_matches(llm_topics, topic_taxonomy)])
    metadata_flags = _metadata_flags(job, extracted_dates, auto_doc_type, auto_doc_type_confidence)
    extraction = _dict(llm_metadata.get("_metadata_extraction"))
    if extraction:
        metadata_flags["metadata_extraction"] = extraction
    entities = extract_named_entities(text, use_gliner=use_gliner)
    claims = _claims(llm_metadata.get("claims"))
    llm_doc_type = _doc_type(llm_metadata.get("doc_type"))
    return DocumentMetadataBundle(
        metadata_version=int(extraction.get("version", 2) or 2) if extraction else 2,
        summary=str(llm_metadata.get("summary", "")).strip(),
        topics=topics,
        topic_scores=topic_scores,
        llm_topics=llm_topics,
        doc_type=llm_doc_type,
        auto_doc_type=auto_doc_type,
        auto_doc_type_confidence=auto_doc_type_confidence,
        metadata_confidence=_metadata_confidence(
            summary=str(llm_metadata.get("summary", "")).strip(),
            llm_doc_type=llm_doc_type,
            llm_topics=llm_topics,
            topic_scores=topic_scores,
            auto_doc_type_confidence=auto_doc_type_confidence,
            entities=entities,
            extracted_dates=extracted_dates,
            claims=claims,
        ),
        metadata_provenance=_metadata_provenance(llm_doc_type=llm_doc_type, extraction=extraction),
        language=language,
        named_entities=entities,
        extracted_dates=extracted_dates,
        cross_references=extract_cross_references(text),
        metadata_flags=metadata_flags,
        claims=claims,
    )


def _metadata_flags(
    job: IngestJobPayload,
    extracted_dates: dict[str, Any],
    auto_doc_type: str,
    auto_doc_type_confidence: float,
) -> dict[str, Any]:
    flags: dict[str, Any] = {}
    body_effective = extracted_dates.get("effective_date_body")
    if isinstance(body_effective, str) and job.effective_date:
        try:
            declared = date.fromisoformat(job.effective_date)
        except ValueError:
            declared = None
        delta = days_between(body_effective, declared) if declared else None
        if delta is not None and delta > 30:
            flags["effective_date_mismatch"] = {
                "declared": job.effective_date,
                "detected": body_effective,
                "delta_days": delta,
            }
    declared_doc_type = job.doc_type.strip().lower()
    if declared_doc_type != "other" and auto_doc_type != "other" and auto_doc_type != declared_doc_type and auto_doc_type_confidence > 0.85:
        flags["doc_type_mismatch"] = {
            "declared": declared_doc_type,
            "detected": auto_doc_type,
            "confidence": auto_doc_type_confidence,
        }
    supersession_refs = extracted_dates.get("supersession_refs")
    if isinstance(supersession_refs, list) and supersession_refs and not job.supersedes:
        flags["supersession_suggested"] = {"references": supersession_refs[:10]}
    return flags


def _taxonomy_matches(values: list[str], taxonomy: tuple[str, ...]) -> list[str]:
    taxonomy_set = {topic.lower(): topic for topic in taxonomy}
    matches: list[str] = []
    for value in values:
        key = value.strip().lower()
        if key in taxonomy_set:
            matches.append(taxonomy_set[key])
    return matches


def _claims(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    claims: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        entity = str(item.get("entity", "")).strip()
        attribute = str(item.get("attribute", "")).strip()
        claim_value = str(item.get("value", "")).strip()
        if entity and attribute and claim_value:
            claims.append({"entity": entity, "attribute": attribute, "value": claim_value})
    return claims[:20]


def _doc_type(value: Any) -> str:
    doc_type = str(value or "other").strip().lower()
    return doc_type if doc_type in DOC_TYPES else "other"


def _metadata_confidence(
    *,
    summary: str,
    llm_doc_type: str,
    llm_topics: list[str],
    topic_scores: dict[str, float],
    auto_doc_type_confidence: float,
    entities: list[Any],
    extracted_dates: dict[str, Any],
    claims: list[dict[str, str]],
) -> dict[str, float]:
    topic_confidence = max(topic_scores.values()) if topic_scores else (0.7 if llm_topics else 0.0)
    return {
        "summary": 0.75 if summary else 0.0,
        "doc_type": 0.82 if llm_doc_type != "other" else round(auto_doc_type_confidence, 3),
        "topics": round(min(1.0, topic_confidence), 3),
        "entities": 0.65 if entities else 0.0,
        "dates": 0.8 if extracted_dates else 0.0,
        "claims": 0.7 if claims else 0.0,
    }


def _metadata_provenance(*, llm_doc_type: str, extraction: dict[str, Any]) -> dict[str, str]:
    mode = str(extraction.get("mode", "single_pass_v1") if extraction else "single_pass_v1")
    return {
        "summary": "llm",
        "doc_type": "llm" if llm_doc_type != "other" else "deterministic_keyword",
        "topics": "deterministic_taxonomy+llm_taxonomy",
        "auto_doc_type": "deterministic_keyword",
        "entities": "deterministic_or_gliner",
        "dates": "deterministic_regex",
        "claims": "llm",
        "extraction_mode": mode,
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        text = value.strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            normalized.append(text)
    return normalized
