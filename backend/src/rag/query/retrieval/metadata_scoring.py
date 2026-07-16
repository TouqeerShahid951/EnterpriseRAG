"""Soft metadata scoring for retrieval and reranking."""

from __future__ import annotations

import re

from rag.shared.contracts.structured_payloads import normalized_match_tokens

from rag.query.qdrant import SearchHit

_STOPWORDS = {
    "and",
    "document",
    "documents",
    "from",
    "give",
    "list",
    "manual",
    "policy",
    "procedure",
    "report",
    "show",
    "the",
    "what",
    "which",
    "with",
}
_TEXT_FIELDS = (
    "doc_title",
    "doc_summary",
    "doc_type",
    "generated_doc_type",
    "auto_doc_type",
    "section_title",
    "table_title",
    "table_caption",
    "table_row_label",
)
_LIST_FIELDS = (
    "section_path",
    "table_column_headers",
    "structured_field_names",
)
TOPIC_BOOST_CAP = 0.05
LLM_TOPIC_WEIGHT = 0.5
LOW_VALUE_PENALTY_CAP = 0.35
FOOTNOTE_PENALTY = 0.08
_LOW_VALUE_FLAG_WEIGHTS = {
    "boilerplate": 0.25,
    "footer": 0.25,
    "header": 0.25,
    "page_footer": 0.25,
    "page_header": 0.25,
    "page_number": 0.25,
    "page-number": 0.25,
    "page_no": 0.25,
    "repeated_boilerplate": 0.25,
    "table_of_contents": LOW_VALUE_PENALTY_CAP,
    "toc": LOW_VALUE_PENALTY_CAP,
    "contents": LOW_VALUE_PENALTY_CAP,
    "index": LOW_VALUE_PENALTY_CAP,
    "footnote": FOOTNOTE_PENALTY,
    "endnote": FOOTNOTE_PENALTY,
}
_BOILERPLATE_PHRASES = (
    "downloaded from www.manualslib.com manuals search engine",
    "page intentionally left blank",
    "this page intentionally left blank",
    "intentionally left blank",
)
_LOW_INFORMATION_STOPWORDS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "page",
    "the",
    "to",
}
_PAGE_NUMBER_ONLY_RE = re.compile(
    r"^(?:page\s*)?(?:\d+|[ivxlcdm]+)(?:\s*(?:of|/)\s*(?:\d+|[ivxlcdm]+))?$",
    re.IGNORECASE,
)
_DOT_LEADER_LINE_RE = re.compile(
    r"\S.{0,120}(?:\.{3,}|(?:\s\.){3,})\s*(?:\d+|[ivxlcdm]+)\s*$", re.IGNORECASE
)
_UNAMBIGUOUS_TOC_HEADING_RE = re.compile(
    r"^table\s+of\s+contents$",
    re.IGNORECASE,
)
_AMBIGUOUS_TOC_HEADING_RE = re.compile(r"^(?:contents|index)$", re.IGNORECASE)
_FLAT_TOC_ENTRY_RE = re.compile(r"(?:^|\s)(\d{1,4})\s+(?=[A-Z][A-Za-z])")


def annotate_metadata_matches(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    query_tokens = _query_tokens(query)
    if not query_tokens:
        return hits
    annotated: list[SearchHit] = []
    for hit in hits:
        matches = sorted(query_tokens & _metadata_tokens(hit))
        score = min(1.0, len(matches) / max(2, len(query_tokens))) if matches else 0.0
        topic_matches, topic_score_value = _topic_match_score(query_tokens, hit)
        if score <= 0 and topic_score_value <= 0:
            annotated.append(hit)
            continue
        payload = dict(hit.payload)
        boosted_score = hit.score
        if score > 0:
            metadata_boost = min(0.15, score * 0.15)
            boosted_score += metadata_boost
            payload.update(
                {
                    "_metadata_score": round(score, 3),
                    "_metadata_matches": matches[:12],
                    "_metadata_boosted_score": round(hit.score + metadata_boost, 6),
                }
            )
        if topic_score_value > 0:
            topic_boost = min(TOPIC_BOOST_CAP, topic_score_value * TOPIC_BOOST_CAP)
            boosted_score += topic_boost
            payload.update(
                {
                    "_topic_score": round(topic_score_value, 3),
                    "_topic_matches": topic_matches[:12],
                    "_topic_boost": round(topic_boost, 6),
                    "_topic_boosted_score": round(boosted_score, 6),
                }
            )
        annotated.append(
            SearchHit(
                point_id=hit.point_id,
                score=hit.score,
                payload=payload,
            )
        )
    return annotated


def metadata_boost_hits(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    annotated = annotate_metadata_matches(query, hits)
    ordered = sorted(
        enumerate(annotated),
        key=lambda item: (
            -_combined_boosted_score(item[1]),
            -float(item[1].payload.get("_metadata_score", 0.0)),
            -topic_score(item[1]),
            item[0],
        ),
    )
    return [hit for _, hit in ordered]


def metadata_score(hit: SearchHit) -> float:
    value = hit.payload.get("_metadata_score", 0.0)
    return float(value) if isinstance(value, int | float) else 0.0


def topic_score(hit: SearchHit) -> float:
    value = hit.payload.get("_topic_score", 0.0)
    return float(value) if isinstance(value, int | float) else 0.0


def annotate_low_value_chunk(
    query: str, hit: SearchHit, *, rerank_score: float | None = None
) -> SearchHit:
    penalty, reasons = low_value_chunk_penalty(query, hit)
    payload = dict(hit.payload)
    payload["_low_value_penalty"] = round(penalty, 6)
    payload["_low_value_reasons"] = reasons
    if rerank_score is not None:
        payload["_rerank_adjusted_score"] = round(rerank_score - penalty, 6)
    return SearchHit(point_id=hit.point_id, score=hit.score, payload=payload)


def low_value_penalty_score(hit: SearchHit) -> float:
    value = hit.payload.get("_low_value_penalty", 0.0)
    return float(value) if isinstance(value, int | float) else 0.0


def low_value_chunk_penalty(query: str, hit: SearchHit) -> tuple[float, list[str]]:
    payload = hit.payload
    query_tokens = _query_tokens(query)
    text = str(payload.get("text") or "")
    text_normalized = _normalized_text(text)
    structured_hit = _is_structured_hit(hit)
    reasons: list[str] = []
    penalty = 0.0

    for flag in _quality_flags(payload):
        flag_penalty = _flag_penalty(flag, query_tokens)
        if flag_penalty <= 0:
            continue
        penalty += flag_penalty
        reasons.append(f"quality_flag:{flag}")

    if not _query_asks_for_toc(query_tokens) and _looks_like_toc_payload(payload, text):
        penalty += LOW_VALUE_PENALTY_CAP
        reasons.append("toc_or_index")
    if (
        not structured_hit
        and not _query_asks_for_page_number(query_tokens)
        and _is_page_number_only(text_normalized)
    ):
        penalty += 0.25
        reasons.append("page_number_only")
    if not _query_asks_for_footnotes(query_tokens) and _looks_like_footnote(
        payload, text_normalized
    ):
        penalty += FOOTNOTE_PENALTY
        reasons.append("footnote")
    if _looks_like_boilerplate(text_normalized):
        penalty += 0.25
        reasons.append("boilerplate")
    if (
        not structured_hit
        and not _is_page_number_only(text_normalized)
        and _looks_low_information(text)
    ):
        penalty += 0.12
        reasons.append("low_information_text")

    if penalty <= 0:
        return 0.0, []
    return round(min(LOW_VALUE_PENALTY_CAP, penalty), 6), _unique_reasons(reasons)


def _combined_boosted_score(hit: SearchHit) -> float:
    for key in ("_topic_boosted_score", "_metadata_boosted_score"):
        value = hit.payload.get(key)
        if isinstance(value, int | float):
            return float(value)
    return hit.score


def _metadata_tokens(hit: SearchHit) -> set[str]:
    payload = hit.payload
    tokens: set[str] = set()
    for field in _TEXT_FIELDS:
        value = payload.get(field)
        if isinstance(value, str):
            tokens.update(normalized_match_tokens(value))
    for field in _LIST_FIELDS:
        value = payload.get(field)
        if isinstance(value, list):
            for item in value:
                tokens.update(normalized_match_tokens(str(item)))
    return {token for token in tokens if len(token) > 2}


def _topic_match_score(
    query_tokens: set[str], hit: SearchHit
) -> tuple[list[str], float]:
    curated_tokens = _list_tokens(hit.payload.get("topics"))
    generated_tokens = _list_tokens(hit.payload.get("llm_topics"))
    if not curated_tokens and not generated_tokens:
        return [], 0.0
    weighted_overlap = 0.0
    matches: list[str] = []
    for token in sorted(query_tokens):
        if token in curated_tokens:
            weighted_overlap += 1.0
            matches.append(token)
        elif token in generated_tokens:
            weighted_overlap += LLM_TOPIC_WEIGHT
            matches.append(token)
    if weighted_overlap <= 0:
        return [], 0.0
    return matches, min(1.0, weighted_overlap / max(1, len(query_tokens)))


def _list_tokens(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    tokens: set[str] = set()
    for item in value:
        tokens.update(normalized_match_tokens(str(item)))
    return {token for token in tokens if len(token) > 2}


def _query_tokens(query: str) -> set[str]:
    return {
        token
        for token in normalized_match_tokens(query)
        if len(token) > 2 and token not in _STOPWORDS
    }


def _quality_flags(payload: dict[str, object]) -> list[str]:
    flags = payload.get("quality_flags")
    if not isinstance(flags, list):
        return []
    return [_normalize_flag(str(flag)) for flag in flags if str(flag).strip()]


def _flag_penalty(flag: str, query_tokens: set[str]) -> float:
    if flag in {
        "table_of_contents",
        "toc",
        "contents",
        "index",
    } and _query_asks_for_toc(query_tokens):
        return 0.0
    if flag in {
        "page_number",
        "page-number",
        "page_no",
    } and _query_asks_for_page_number(query_tokens):
        return 0.0
    if flag in {"footnote", "endnote"} and _query_asks_for_footnotes(query_tokens):
        return 0.0
    return _LOW_VALUE_FLAG_WEIGHTS.get(flag, 0.0)


def _looks_like_toc_payload(payload: dict[str, object], text: str) -> bool:
    section_parts: list[str] = []
    section_title = payload.get("section_title")
    if isinstance(section_title, str):
        section_parts.append(section_title)
    section_path = payload.get("section_path")
    if isinstance(section_path, list):
        section_parts.extend(str(part) for part in section_path)
    if any(
        _UNAMBIGUOUS_TOC_HEADING_RE.match(part.strip())
        for part in section_parts
        if part.strip()
    ):
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    if any(_UNAMBIGUOUS_TOC_HEADING_RE.match(line) for line in lines):
        return True
    dot_leader_lines = sum(1 for line in lines[:12] if _DOT_LEADER_LINE_RE.search(line))
    if dot_leader_lines >= 2 and dot_leader_lines >= max(2, len(lines[:12]) // 3):
        return True
    ambiguous_heading = any(
        _AMBIGUOUS_TOC_HEADING_RE.match(part.strip())
        for part in section_parts
        if part.strip()
    ) or any(_AMBIGUOUS_TOC_HEADING_RE.match(line) for line in lines)
    if ambiguous_heading:
        return False
    flat_page_numbers = [
        int(value) for value in _FLAT_TOC_ENTRY_RE.findall(text) if int(value) <= 500
    ]
    if len(flat_page_numbers) < 2 or len(set(flat_page_numbers)) < 2:
        return False
    current_page = _payload_page(payload)
    sparse_prose = len(re.findall(r"[.!?]", text)) <= max(
        1,
        len(flat_page_numbers) // 3,
    )
    return bool(
        sparse_prose
        and (
            current_page is None
            or min(flat_page_numbers) >= current_page
            and max(flat_page_numbers) > current_page + 1
        )
    )


def _payload_page(payload: dict[str, object]) -> int | None:
    for field in ("page_start", "page"):
        value = payload.get(field)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip().isdecimal():
            return int(value.strip())
    return None


def _is_page_number_only(text: str) -> bool:
    if not text or len(text) > 40:
        return False
    return bool(_PAGE_NUMBER_ONLY_RE.match(text))


def _looks_like_footnote(payload: dict[str, object], text: str) -> bool:
    if "footnote" in _normalized_text(str(payload.get("section_title") or "")):
        return True
    return (
        text.startswith("footnote ")
        or text.startswith("note:")
        or bool(re.match(r"^\[\d+\]\s+\S", text))
    )


def _looks_like_boilerplate(text: str) -> bool:
    return any(phrase in text for phrase in _BOILERPLATE_PHRASES)


def _looks_low_information(text: str) -> bool:
    normalized = _normalized_text(text)
    if not normalized or len(normalized) > 80:
        return False
    tokens = {
        token
        for token in normalized_match_tokens(normalized)
        if len(token) > 1 and token not in _LOW_INFORMATION_STOPWORDS
    }
    return len(tokens) <= 2


def _is_structured_hit(hit: SearchHit) -> bool:
    payload = hit.payload
    if payload.get("chunk_type") in {"table", "table_row", "kv_record"}:
        return True
    structured_kind = payload.get("structured_kind")
    if isinstance(structured_kind, str) and structured_kind.strip():
        return True
    table_json = payload.get("table_json")
    structured_fields = payload.get("structured_fields")
    return (
        isinstance(table_json, dict)
        and bool(table_json)
        or isinstance(structured_fields, list)
        and bool(structured_fields)
    )


def _query_asks_for_toc(query_tokens: set[str]) -> bool:
    return bool(
        {"toc", "contents"} & query_tokens
        or {"table", "contents"} <= query_tokens
        or "index" in query_tokens
    )


def _query_asks_for_page_number(query_tokens: set[str]) -> bool:
    return "page" in query_tokens or {"page", "number"} <= query_tokens


def _query_asks_for_footnotes(query_tokens: set[str]) -> bool:
    return bool(
        {"footnote", "footnotes", "endnote", "endnotes", "note", "notes"} & query_tokens
    )


def _normalized_text(text: str) -> str:
    return " ".join(text.lower().split())


def _normalize_flag(flag: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", flag.strip().lower()).strip("_")


def _unique_reasons(reasons: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        unique.append(reason)
    return unique[:12]
