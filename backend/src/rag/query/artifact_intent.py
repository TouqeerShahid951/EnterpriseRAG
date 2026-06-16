"""Natural-language detection for generated file requests."""

from __future__ import annotations

from dataclasses import dataclass
import re

from ..schemas.query import ArtifactFormat


GENERATION_VERB_RE = re.compile(r"\b(?:generate|create|make|export|download|draft|produce|prepare|build)\b", re.IGNORECASE)
OUTPUT_FORMAT_CONTEXT_RE = re.compile(
    r"\b(?:as|in|to)\s+(?:a|an)?\s*(?:docx|word(?:\s+document)?|pptx|powerpoint|slides?|slide\s+deck|pdf)\b",
    re.IGNORECASE,
)
FORMAT_PATTERNS: tuple[tuple[ArtifactFormat, re.Pattern[str]], ...] = (
    ("docx", re.compile(r"(?<!\.)\b(?:docx|word(?:\s+document)?)\b", re.IGNORECASE)),
    ("pptx", re.compile(r"(?<!\.)\b(?:pptx|powerpoint|slides?|slide\s+deck|presentation)\b", re.IGNORECASE)),
    ("pdf", re.compile(r"(?<!\.)\bpdf\b", re.IGNORECASE)),
)
REMOVE_PATTERNS = (
    re.compile(r"(?<!\.)\b(?:docx|word(?:\s+document)?|pptx|powerpoint|slides?|slide\s+deck|presentation|pdf)\b", re.IGNORECASE),
    re.compile(r"\b(?:file|deck)\b", re.IGNORECASE),
    GENERATION_VERB_RE,
    re.compile(r"\b(?:as|in|to)\s+(?:a|an)?\s*(?:format|file)\b", re.IGNORECASE),
    re.compile(r"\b(?:using|from)\s+(?:the\s+)?(?:indexed|retrieved|available)\s+(?:documents|sources|evidence)\b", re.IGNORECASE),
)
LEADING_WRAPPER_RE = re.compile(
    r"^(?:(?:that\s+)?(?:contains?|containing)\s+(?:of\s+)?|with\s+|about\s+|on\s+|for\s+)+",
    re.IGNORECASE,
)
LEADING_FILLER_RE = re.compile(r"^(?:please|a|an|the|and|or|about|on|for|of|with|based\s+on)\b[\s:,-]*", re.IGNORECASE)
EMPTY_TOPICS = {
    "",
    "it",
    "this",
    "that",
    "answer",
    "the answer",
    "current answer",
    "previous answer",
    "the sources",
    "sources",
    "documents",
    "the documents",
}
DOCUMENT_SCOPE_REQUIRED_RE = re.compile(
    r"^(?:summari[sz]e|summary\s+of|outline|describe|explain)\s+(?:the\s+|this\s+|selected\s+)?documents?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ArtifactRequest:
    original_query: str
    content_query: str
    formats: tuple[ArtifactFormat, ...]
    needs_clarification: bool = False


def parse_artifact_request(query: str) -> ArtifactRequest | None:
    normalized = query.strip()
    if not normalized:
        return None
    formats = _requested_formats(normalized)
    if not formats:
        return None
    if GENERATION_VERB_RE.search(normalized) is None and OUTPUT_FORMAT_CONTEXT_RE.search(normalized) is None:
        return None
    content_query = cleaned_content_query(normalized)
    return ArtifactRequest(
        original_query=normalized,
        content_query=content_query,
        formats=tuple(formats),
        needs_clarification=_needs_clarification(content_query),
    )


def cleaned_content_query(query: str) -> str:
    cleaned = query.strip()
    for pattern in REMOVE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"\b(?:and|or)\s+(?:a|an|the)?\s*$", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:and|or)\b\s*(?=$)", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[\s:,-]+|[\s:,-]+$", "", cleaned)
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = LEADING_WRAPPER_RE.sub("", cleaned).strip()
        cleaned = LEADING_FILLER_RE.sub("", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"^list\s+of\s+all\b", "list all", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^a\s+list\s+of\b", "list", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^list\s+all\s+the\b", "list all", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" :,-.")


def _requested_formats(query: str) -> list[ArtifactFormat]:
    matches: list[tuple[int, ArtifactFormat]] = []
    for artifact_format, pattern in FORMAT_PATTERNS:
        match = pattern.search(query)
        if match is not None:
            matches.append((match.start(), artifact_format))
    seen: set[ArtifactFormat] = set()
    ordered: list[ArtifactFormat] = []
    for _position, artifact_format in sorted(matches, key=lambda item: item[0]):
        if artifact_format in seen:
            continue
        seen.add(artifact_format)
        ordered.append(artifact_format)
    return ordered


def _needs_clarification(content_query: str) -> bool:
    normalized = content_query.strip().lower()
    if normalized in EMPTY_TOPICS:
        return True
    if requires_document_scope(content_query):
        return True
    return not re.search(r"[A-Za-z0-9]{3,}", normalized)


def requires_document_scope(content_query: str) -> bool:
    return DOCUMENT_SCOPE_REQUIRED_RE.search(content_query.strip()) is not None
