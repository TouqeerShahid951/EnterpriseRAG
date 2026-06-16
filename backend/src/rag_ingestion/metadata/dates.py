"""Date extraction helpers for ingestion metadata."""

from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any

from .crossrefs import extract_cross_references

_ISO_DATE_RE = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
_MONTH_DATE_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
_MONTH_YEAR_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
_EFFECTIVE_RE = re.compile(r"\beffective\s+(?:date\s*)?(?:from|as of|on)?\s*:?\s*([^\n.;]{4,40})", re.IGNORECASE)
_REVISION_RE = re.compile(r"\b(?:revised|revision date)\s*:?\s*([^\n.;]{4,40})", re.IGNORECASE)
_REVIEW_RE = re.compile(r"\b(?:next review due|review date|review due)\s*:?\s*([^\n.;]{4,40})", re.IGNORECASE)


def extract_dates(text: str) -> dict[str, Any]:
    return {
        "document_dates": _document_dates(text),
        "revision_date": _matched_date(text, _REVISION_RE),
        "review_date": _matched_date(text, _REVIEW_RE),
        "supersession_refs": [
            ref.ref_text for ref in extract_cross_references(text) if ref.ref_type in {"supersedes", "replaces"}
        ],
        "effective_date_body": _matched_date(text, _EFFECTIVE_RE),
    }


def _document_dates(text: str) -> list[str]:
    dates: list[str] = []
    seen: set[str] = set()
    for raw in _search_dates(text):
        parsed = _parse_date(raw)
        if parsed and parsed not in seen:
            seen.add(parsed)
            dates.append(parsed)
        if len(dates) >= 50:
            break
    return dates


def _search_dates(text: str) -> list[str]:
    try:
        from dateparser.search import search_dates

        results = search_dates(text[:20000], settings={"PREFER_DAY_OF_MONTH": "first"}) or []
        return [raw for raw, _ in results]
    except Exception:
        values: list[str] = []
        for pattern in (_ISO_DATE_RE, _MONTH_DATE_RE, _MONTH_YEAR_RE):
            values.extend(match.group(0) for match in pattern.finditer(text))
        return values


def _matched_date(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return _parse_date(match.group(1))


def _parse_date(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None
    try:
        import dateparser

        parsed = dateparser.parse(value, settings={"PREFER_DAY_OF_MONTH": "first"})
        if parsed:
            return parsed.date().isoformat()
    except Exception:
        pass
    if _ISO_DATE_RE.fullmatch(value):
        return value
    for fmt in ("%B %d %Y", "%B %d, %Y", "%b %d %Y", "%b %d, %Y", "%B %Y", "%b %Y"):
        try:
            return datetime.strptime(value.replace(",", ""), fmt.replace(",", "")).date().isoformat()
        except ValueError:
            continue
    return None


def days_between(left: str, right: date) -> int | None:
    try:
        left_date = date.fromisoformat(left)
    except ValueError:
        return None
    return abs((left_date - right).days)

