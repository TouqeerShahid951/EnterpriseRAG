"""Artifact request text normalization shared by query intake and planning."""

from __future__ import annotations

import re


GENERATION_VERBS = (
    r"(?:generate|create|make|export|draft|produce|prepare|build)"
)
GENERATION_VERB_RE = re.compile(rf"\b{GENERATION_VERBS}\b", re.IGNORECASE)
OUTPUT_REQUEST_VERBS = r"(?:convert|give|provide|return|save|send|turn)"
_OUTPUT_FORMAT = r"(?:docx|word(?:\s+document)?|pptx|powerpoint|slides?|slide\s+deck|pdf)"
_LEADING_GENERATION_REQUEST_RE = re.compile(
    rf"^\s*(?:(?:please[\s,]+)|(?:can|could|would|will)\s+you\s+(?:please\s+)?|"
    rf"(?:i\s+)?(?:want|need)\s+(?:you\s+)?to\s+|"
    rf"i(?:'d|\s+would)\s+like\s+(?:you\s+)?to\s+)?{GENERATION_VERBS}\b\s+(?:me\s+)?",
    re.IGNORECASE,
)
_LEADING_DESIRED_OUTPUT_RE = re.compile(
    rf"^\s*(?:i\s+(?:want|need)|i(?:'d|\s+would)\s+like)\s+(?:a|an)?\s*(?={_OUTPUT_FORMAT}\b)",
    re.IGNORECASE,
)
_LEADING_OUTPUT_REQUEST_RE = re.compile(
    rf"^\s*(?:please[\s,]+)?{OUTPUT_REQUEST_VERBS}\s+(?:me\s+)?",
    re.IGNORECASE,
)
_TRAILING_OUTPUT_REQUEST_RE = re.compile(
    rf"\s+(?:and\s+)?(?:export|convert|save|return|provide|send)\s+"
    rf"(?:(?:it|this|that|the\s+(?:answer|response|result|report))\s+)?"
    rf"(?:as|in|into|to)\s+(?:a|an)?\s*{_OUTPUT_FORMAT}\b.*$",
    re.IGNORECASE,
)
_TRAILING_OUTPUT_WRAPPER_RE = re.compile(
    r"\b(?:as|in|into|to)\s+(?:a|an)?\s*$",
    re.IGNORECASE,
)
SOFTWARE_SUBJECT_PATTERN = (
    r"(?:api|class|code|component|converter|editor|framework|function|generator|layer|"
    r"library|logic|model|module|package|parser|pattern|renderer|sdk|tier|tool|view|viewer)"
)
_REMOVE_PATTERNS = (
    re.compile(
        rf"(?<!\.)\b(?:docx|word(?:\s+document)?|pptx|powerpoint|slides?|slide\s+deck|presentation|pdf)\b"
        rf"(?!\s+{SOFTWARE_SUBJECT_PATTERN}\b)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:file|deck)\b", re.IGNORECASE),
    GENERATION_VERB_RE,
    re.compile(r"\b(?:as|in|to)\s+(?:a|an)?\s*(?:format|file)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:using|from)\s+(?:the\s+)?(?:indexed|retrieved|available)\s+(?:documents|sources|evidence)\b",
        re.IGNORECASE,
    ),
)
_LEADING_WRAPPER_RE = re.compile(
    r"^(?:(?:that\s+)?(?:contains?|containing)\s+(?:of\s+)?|with\s+|about\s+|on\s+|for\s+)+",
    re.IGNORECASE,
)
_LEADING_FILLER_RE = re.compile(
    r"^(?:please|a|an|the|and|or|about|on|for|of|with|based\s+on)\b[\s:,-]*",
    re.IGNORECASE,
)
_LEADING_DETAIL_MODIFIER_RE = re.compile(
    r"^(?:detailed|comprehensive|full|complete)\s+(?:of\s+)?",
    re.IGNORECASE,
)
_LEADING_OPERATION_NORMALIZERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^summari[sz]ing\b", re.IGNORECASE), "summarize"),
    (re.compile(r"^describing\b", re.IGNORECASE), "describe"),
    (re.compile(r"^explaining\b", re.IGNORECASE), "explain"),
    (re.compile(r"^analy[sz]ing\b", re.IGNORECASE), "analyze"),
    (re.compile(r"^identifying\b", re.IGNORECASE), "identify"),
    (re.compile(r"^listing\b", re.IGNORECASE), "list"),
)


def cleaned_content_query(query: str) -> str:
    cleaned = _TRAILING_OUTPUT_REQUEST_RE.sub("", query.strip())
    cleaned = _LEADING_GENERATION_REQUEST_RE.sub("", cleaned)
    cleaned = _LEADING_DESIRED_OUTPUT_RE.sub("", cleaned)
    cleaned = _LEADING_OUTPUT_REQUEST_RE.sub("", cleaned)
    for pattern in _REMOVE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = _TRAILING_OUTPUT_WRAPPER_RE.sub(" ", cleaned)
    cleaned = re.sub(
        r"\b(?:and|or)\s+(?:a|an|the)?\s*$", " ", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"\b(?:and|or)\b\s*(?=$)", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:a|an|the)\s*$", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[\s:,-]+|[\s:,-]+$", "", cleaned)
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _LEADING_WRAPPER_RE.sub("", cleaned).strip()
        cleaned = _LEADING_FILLER_RE.sub("", cleaned).strip()
        cleaned = _LEADING_DETAIL_MODIFIER_RE.sub("", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\bwith\s+details?\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bin\s+the\s+all\b", "in all", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"^list\s+of\s+all\b", "list all", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^a\s+list\s+of\b", "list", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^list\s+all\s+the\b", "list all", cleaned, flags=re.IGNORECASE)
    for pattern, replacement in _LEADING_OPERATION_NORMALIZERS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned.strip(" :,-.")
