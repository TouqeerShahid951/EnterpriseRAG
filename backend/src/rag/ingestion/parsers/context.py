"""Context rules for PyMuPDF extracted text."""

from __future__ import annotations

import re

_TABLE_TITLE_RE = re.compile(r"^table\s+(?:\d+|[ivxlcdm]+)[.:]?\s+\S", re.IGNORECASE)
_BOILERPLATE_SUBSTRINGS = (
    "downloaded from www.manualslib.com manuals search engine",
)


def is_boilerplate_text(text: str) -> bool:
    normalized = _normalized(text)
    return any(marker in normalized for marker in _BOILERPLATE_SUBSTRINGS)


def is_table_title(text: str | None) -> bool:
    return bool(text and _TABLE_TITLE_RE.match(text.strip()))


def contextualized_item(text: str, item_type: str, section_title: str | None) -> tuple[str, str]:
    if not is_table_title(section_title) or text.startswith(str(section_title)):
        return text, item_type
    if item_type in {"text", "table"}:
        return f"{section_title}\n{text}", "table"
    return text, item_type


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())
