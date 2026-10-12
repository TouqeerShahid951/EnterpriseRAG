"""Abbreviation glossary rules shared across upload, ingestion, and query."""

from __future__ import annotations

import re


ABBREVIATION_GLOSSARY_DOC_TYPE = "abbreviation_glossary"

_ABBREVIATION_LABELS = {
    "abbreviation",
    "abbreviations",
    "acronym",
    "acronyms",
    "short form",
    "short forms",
    "short word",
    "short words",
    "code",
    "codes",
}
_EXPANSION_LABELS = {
    "expansion",
    "expansions",
    "full form",
    "full forms",
    "full expression",
    "full expressions",
    "meaning",
    "meanings",
    "definition",
    "definitions",
}
_ABBREVIATION_RE = re.compile(
    r"[A-Z][A-Z0-9./&-]*(?: [A-Z0-9./&-]+)*",
    re.IGNORECASE,
)
_DELIMITED_ENTRY_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9./&-]{1,19})\s*(?:—|–|-|:|=)\s*(.{2,240}?)\s*$"
)


def abbreviation_entries(
    text: str,
    structured_fields: object = None,
) -> list[tuple[str, str]]:
    """Return recognized ``(abbreviation, expansion)`` pairs."""
    return list(
        dict.fromkeys(
            (abbreviation, expansion.strip())
            for abbreviation, expansion in abbreviation_entry_candidates(text, structured_fields)
            if abbreviation_entry_failure_reason(abbreviation, expansion) is None
        )
    )


def abbreviation_entry_candidates(
    text: str,
    structured_fields: object = None,
) -> list[tuple[str, str]]:
    """Return parseable glossary candidates before domain validation."""
    entries: list[tuple[str, str]] = []
    if isinstance(structured_fields, list):
        fields = {
            _normalized_label(item.get("label")): str(item.get("value") or "").strip()
            for item in structured_fields
            if isinstance(item, dict)
        }
        abbreviation = next(
            (fields[label] for label in _ABBREVIATION_LABELS if fields.get(label)),
            "",
        )
        expansion = next(
            (fields[label] for label in _EXPANSION_LABELS if fields.get(label)),
            "",
        )
        if abbreviation or expansion:
            entries.append((abbreviation, expansion))

    for line in text.splitlines():
        match = _DELIMITED_ENTRY_RE.fullmatch(line)
        if match:
            entries.append((match[1], match[2]))
    return list(dict.fromkeys(entries))


def abbreviation_entry_failure_reason(abbreviation: str, expansion: str) -> str | None:
    """Return the user-actionable reason a candidate cannot be imported."""
    normalized_abbreviation = " ".join(abbreviation.split())
    normalized_expansion = " ".join(expansion.split())
    if not 2 <= len(normalized_abbreviation) <= 20 or not _ABBREVIATION_RE.fullmatch(
        normalized_abbreviation
    ):
        return "abbreviation must be 2–20 letters, digits, spaces, or ./&- characters"
    if not normalized_expansion:
        return "full expression is blank"
    if normalized_abbreviation.casefold() == normalized_expansion.casefold():
        return "full expression matches the abbreviation"
    if len(normalized_expansion) > 240:
        return "full expression exceeds 240 characters"
    return None


def normalize_abbreviation_entry(
    abbreviation: str,
    expansion: str,
) -> tuple[str, str]:
    """Normalize and validate a managed glossary entry."""
    normalized_abbreviation = " ".join(abbreviation.split()).upper()
    normalized_expansion = " ".join(expansion.split())
    if not _valid_entry(normalized_abbreviation, normalized_expansion):
        raise ValueError("abbreviation and expansion must form a usable glossary entry")
    return normalized_abbreviation, normalized_expansion


def preserved_document_type(current: str | None, candidate: str | None) -> str | None:
    if current == ABBREVIATION_GLOSSARY_DOC_TYPE:
        return current
    return candidate or current


def _valid_entry(abbreviation: str, expansion: str) -> bool:
    return abbreviation_entry_failure_reason(abbreviation, expansion) is None


def _normalized_label(value: object) -> str:
    return " ".join(re.sub(r"[^a-z]+", " ", str(value or "").casefold()).split())
