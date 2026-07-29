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
    "code",
    "codes",
}
_EXPANSION_LABELS = {
    "expansion",
    "expansions",
    "full form",
    "full forms",
    "meaning",
    "meanings",
    "definition",
    "definitions",
}
_ABBREVIATION_RE = re.compile(r"[A-Z][A-Z0-9./&-]{1,19}")
_DELIMITED_ENTRY_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9./&-]{1,19})\s*(?:—|–|-|:|=)\s*(.{2,240}?)\s*$"
)


def abbreviation_entries(
    text: str,
    structured_fields: object = None,
) -> list[tuple[str, str]]:
    """Return recognized ``(abbreviation, expansion)`` pairs."""
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
        if _valid_entry(abbreviation, expansion):
            entries.append((abbreviation, expansion))

    for line in text.splitlines():
        match = _DELIMITED_ENTRY_RE.fullmatch(line)
        if match and _valid_entry(match[1], match[2]):
            entries.append((match[1], match[2].strip()))
    return list(dict.fromkeys(entries))


def normalize_abbreviation_entry(
    abbreviation: str,
    expansion: str,
) -> tuple[str, str]:
    """Normalize and validate a managed glossary entry."""
    normalized_abbreviation = abbreviation.strip().upper()
    normalized_expansion = " ".join(expansion.split())
    if not _valid_entry(normalized_abbreviation, normalized_expansion):
        raise ValueError("abbreviation and expansion must form a usable glossary entry")
    return normalized_abbreviation, normalized_expansion


def preserved_document_type(current: str | None, candidate: str | None) -> str | None:
    if current == ABBREVIATION_GLOSSARY_DOC_TYPE:
        return current
    return candidate or current


def _valid_entry(abbreviation: str, expansion: str) -> bool:
    normalized_expansion = " ".join(expansion.split())
    return bool(
        _ABBREVIATION_RE.fullmatch(abbreviation)
        and normalized_expansion
        and abbreviation.casefold() != normalized_expansion.casefold()
        and len(normalized_expansion) <= 240
    )


def _normalized_label(value: object) -> str:
    return " ".join(re.sub(r"[^a-z]+", " ", str(value or "").casefold()).split())
