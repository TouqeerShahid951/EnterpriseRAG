"""Inventory every material answer unit, including units without citations."""

import re

from rag.shared.contracts.evidence import PARTIAL_NOTICE, CitationClaim
from rag.query.sources import parse_citation_tokens

_CITATION = re.compile(r"\[[^\[\]\r\n]{1,200}:[^\[\]\r\n]{1,200}\]")
_SEPARATOR = re.compile(r"[\s|:\-]+")


def _cited_units(raw: str):
    """Split only at completed cited sentences, retaining adjacent source labels."""
    citations = list(_CITATION.finditer(raw))
    start = 0
    for index, citation in enumerate(citations):
        end = citation.end()
        if index + 1 < len(citations) and not raw[end:citations[index + 1].start()].strip(" \t,;"):
            continue
        punctuation = re.match(r"[.!?۔。！？]*", raw[end:]).group()
        end += len(punctuation)
        before = _CITATION.sub("", raw[start:citation.start()]).rstrip(" \t,;")
        if not punctuation and not before.endswith((".", "!", "?", "۔", "。", "！", "？")):
            continue
        tail = raw[end:].lstrip()
        # A following qualifier belongs with the assertion it limits.
        if re.match(r"(?i)(?:unless|except|provided|subject to|but|however|only if)\b", tail):
            continue
        if tail:
            yield start, end
            start = end
    if start < len(raw):
        yield start, len(raw)


def answer_claims(answer: str) -> list[CitationClaim]:
    # ponytail: citation boundaries are explicit; uncited compound text stays whole.
    claims: list[CitationClaim] = []
    table_header = ""
    lines = list(re.finditer(r"[^\r\n]+", answer))
    for index, match in enumerate(lines):
        raw = match.group()
        text = _CITATION.sub("", raw).strip().strip("#*>` ")
        if raw.strip() == PARTIAL_NOTICE or not text or _SEPARATOR.fullmatch(text):
            continue
        if raw.lstrip().startswith("|") and index + 1 < len(lines):
            if _SEPARATOR.fullmatch(lines[index + 1].group()):
                table_header = text
                continue
        if not any(character.isalnum() for character in text):
            continue
        if raw.lstrip().startswith("|") and table_header:
            text = f"Columns: {table_header}\nRow: {text}"
        elif not raw.lstrip().startswith("|"):
            table_header = ""
        units = [(0, len(raw))] if raw.lstrip().startswith("|") else _cited_units(raw)
        for start, end in units:
            unit = raw[start:end]
            unit_text = text if raw.lstrip().startswith("|") else _CITATION.sub("", unit).strip().strip("#*>` ")
            if not any(character.isalnum() for character in unit_text):
                continue
            claims.append(
                CitationClaim(
                    claim_id=f"claim-{len(claims) + 1}",
                    answer_start=match.start() + start,
                    answer_end=match.start() + end,
                    text=unit_text,
                    source_labels=list(dict.fromkeys(parse_citation_tokens(unit))),
                )
            )
    return claims
