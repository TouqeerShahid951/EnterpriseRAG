"""Temporal query helpers for retrieval filters."""

from __future__ import annotations

import calendar
import re

_DATE_RE = re.compile(r"\b((?:19|20)\d{2})(?:-(\d{2})(?:-(\d{2}))?)?\b")


def target_date_for_query(query: str) -> str | None:
    match = _DATE_RE.search(query)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2) or "12")
    day = int(match.group(3) or str(calendar.monthrange(year, month)[1]))
    return f"{year:04d}-{month:02d}-{day:02d}"


def add_effective_date_scope(qdrant_filter: dict[str, object], target_date: str | None) -> dict[str, object]:
    if target_date is None:
        return qdrant_filter
    scoped = dict(qdrant_filter)
    must = list(scoped.get("must", []))
    must.append(
        {
            "should": [
                {"key": "effective_date", "range": {"lte": target_date}},
                {"is_empty": {"key": "effective_date"}},
            ]
        }
    )
    scoped["must"] = must
    return scoped
