"""Cross-reference detection for document body text."""

from __future__ import annotations

import re

from .models import CrossReference

CROSS_REF_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("see_also", re.compile(r"(?:ref(?:erence)?|see also|per|as per|pursuant to)\s+([A-Z]{2,}-[\d/]+)", re.IGNORECASE)),
    ("supersedes", re.compile(r"supersedes?\s+([A-Z]{2,}-[\d/]+)", re.IGNORECASE)),
    ("replaces", re.compile(r"replaces?\s+([A-Z]{2,}-[\d/]+)", re.IGNORECASE)),
    ("amends", re.compile(r"amends?\s+([A-Z]{2,}-[\d/]+)", re.IGNORECASE)),
    ("see_also", re.compile(r"(?:circular|notification|order|sop)\s+(?:no\.?\s*)?(\d{1,4}[/\-]\d{2,4})", re.IGNORECASE)),
)


def extract_cross_references(text: str, *, limit: int = 100) -> list[CrossReference]:
    refs: list[CrossReference] = []
    seen: set[tuple[str, str, int]] = set()
    for ref_type, pattern in CROSS_REF_PATTERNS:
        for match in pattern.finditer(text):
            ref_text = match.group(1).strip()
            key = (ref_text.lower(), ref_type, match.start(1))
            if ref_text and key not in seen:
                seen.add(key)
                refs.append(CrossReference(ref_text=ref_text, ref_type=ref_type, position=match.start(1)))
                if len(refs) >= limit:
                    return refs
    return refs

