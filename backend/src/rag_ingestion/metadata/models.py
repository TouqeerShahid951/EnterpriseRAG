"""Typed metadata extraction records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NamedEntity:
    text: str
    type: str
    start: int | None = None
    end: int | None = None

    def as_payload(self) -> dict[str, object]:
        return {"text": self.text, "type": self.type, "start": self.start, "end": self.end}


@dataclass(frozen=True)
class CrossReference:
    ref_text: str
    ref_type: str
    position: int | None = None

    def as_payload(self) -> dict[str, object]:
        return {"ref_text": self.ref_text, "ref_type": self.ref_type, "position": self.position}


@dataclass(frozen=True)
class DocumentMetadataBundle:
    metadata_version: int = 1
    summary: str = ""
    topics: list[str] = field(default_factory=list)
    topic_scores: dict[str, float] = field(default_factory=dict)
    llm_topics: list[str] = field(default_factory=list)
    doc_type: str = ""
    auto_doc_type: str = ""
    auto_doc_type_confidence: float = 0.0
    metadata_confidence: dict[str, float] = field(default_factory=dict)
    metadata_provenance: dict[str, str] = field(default_factory=dict)
    language: str = "unknown"
    named_entities: list[NamedEntity] = field(default_factory=list)
    extracted_dates: dict[str, Any] = field(default_factory=dict)
    cross_references: list[CrossReference] = field(default_factory=list)
    metadata_flags: dict[str, Any] = field(default_factory=dict)
    claims: list[dict[str, str]] = field(default_factory=list)

    def as_worker_metadata(self) -> dict[str, Any]:
        return {
            "metadata_version": self.metadata_version,
            "summary": self.summary,
            "topics": self.topics,
            "topic_scores": self.topic_scores,
            "llm_topics": self.llm_topics,
            "doc_type": self.doc_type,
            "auto_doc_type": self.auto_doc_type,
            "auto_doc_type_confidence": self.auto_doc_type_confidence,
            "metadata_confidence": self.metadata_confidence,
            "metadata_provenance": self.metadata_provenance,
            "language": self.language,
            "named_entities": [entity.as_payload() for entity in self.named_entities],
            "extracted_dates": self.extracted_dates,
            "cross_references": [ref.as_payload() for ref in self.cross_references],
            "metadata_flags": self.metadata_flags,
            "claims": self.claims,
        }
