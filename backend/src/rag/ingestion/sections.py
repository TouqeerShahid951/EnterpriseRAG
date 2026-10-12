"""Numbered section identifiers shared by ingestion and document queries."""

import re

_HEADING = re.compile(
    r"^(?:(section|chapter|part|appendix|annex)\s+)?"
    r"(\d+(?:\.\d+)*|[ivxlcdm]+|[a-z])(?:[.):]\s*|\s+|$)",
    re.IGNORECASE,
)


def section_identifier(title: str) -> tuple[str, str] | None:
    match = _HEADING.match(title.strip())
    if match is None:
        return None
    return ((match.group(1) or "section").lower(), match.group(2).lower())
