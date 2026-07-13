"""Natural-language detection for generated file requests."""

from __future__ import annotations

from dataclasses import dataclass
import re

from ..artifact_jobs.request_text import (
    GENERATION_VERB_RE as GENERATION_VERB_RE,
    GENERATION_VERBS,
    OUTPUT_REQUEST_VERBS,
    cleaned_content_query as cleaned_content_query,
)
from ..artifact_jobs.types import ArtifactFormat


DIRECT_GENERATION_REQUEST_RE = re.compile(
    rf"""
    ^\s*(?:
        (?:please[\s,]+)?{GENERATION_VERBS}\b
        |(?:can|could|would|will)\s+you\s+(?:please\s+)?{GENERATION_VERBS}\b
        |(?:i\s+)?(?:want|need)\s+(?:you\s+)?to\s+{GENERATION_VERBS}\b
        |i(?:'d|\s+would)\s+like\s+(?:you\s+)?to\s+{GENERATION_VERBS}\b
        |(?:using|from|with|based\s+on)\b[^,;:]{{0,240}}[,;:]\s*
            (?:please[\s,]+)?{GENERATION_VERBS}\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
DIRECT_OUTPUT_REQUEST_RE = re.compile(
    rf"""
    ^\s*(?:
        (?:please[\s,]+)?{OUTPUT_REQUEST_VERBS}\b
        |(?:can|could|would|will)\s+you\s+(?:please\s+)?{OUTPUT_REQUEST_VERBS}\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
OUTPUT_FORMAT_CONTEXT_RE = re.compile(
    r"\b(?:as|in|into|to)\s+(?:a|an)?\s*(?:docx|word(?:\s+document)?|pptx|powerpoint|slides?|slide\s+deck|pdf)\b",
    re.IGNORECASE,
)
PRESENTATION_SOFTWARE_CONTEXT_RE = re.compile(
    r"\bpresentation\s+(?:api|component|framework|layer|logic|model|pattern|tier|view)\b",
    re.IGNORECASE,
)
CONCRETE_FILE_FORMAT_RE = re.compile(
    r"(?<!\.)\b(?:docx|word\s+document|pptx|powerpoint|slides?|slide\s+deck|pdf)\b",
    re.IGNORECASE,
)
FORMAT_PATTERNS: tuple[tuple[ArtifactFormat, re.Pattern[str]], ...] = (
    ("docx", re.compile(r"(?<!\.)\b(?:docx|word(?:\s+document)?)\b", re.IGNORECASE)),
    (
        "pptx",
        re.compile(
            r"(?<!\.)\b(?:pptx|powerpoint|slides?|slide\s+deck|presentation)\b",
            re.IGNORECASE,
        ),
    ),
    ("pdf", re.compile(r"(?<!\.)\bpdf\b", re.IGNORECASE)),
)
EMPTY_TOPICS = {
    "",
    "it",
    "this",
    "that",
    "answer",
    "the answer",
    "current answer",
    "the current answer",
    "previous answer",
    "the previous answer",
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
    if not _is_explicit_artifact_request(normalized):
        return None
    content_query = cleaned_content_query(normalized)
    return ArtifactRequest(
        original_query=normalized,
        content_query=content_query,
        formats=tuple(formats),
        needs_clarification=_needs_clarification(content_query),
    )


def _is_explicit_artifact_request(query: str) -> bool:
    if (
        PRESENTATION_SOFTWARE_CONTEXT_RE.search(query) is not None
        and CONCRETE_FILE_FORMAT_RE.search(query) is None
    ):
        return False
    if DIRECT_GENERATION_REQUEST_RE.search(query) is not None:
        return True
    return (
        DIRECT_OUTPUT_REQUEST_RE.search(query) is not None
        and OUTPUT_FORMAT_CONTEXT_RE.search(query) is not None
    )


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
