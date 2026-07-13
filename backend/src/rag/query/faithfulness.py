"""Faithfulness judging for synthesized RAG answers."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

from ..shared.contracts.evidence import EvidenceField, EvidenceWindow, HighlightRange, SourceAnchor
from .cancellation import QueryCancellationToken, QueryCancelled, call_with_optional_cancellation
from .http import ServiceRequestError
from .inference import InferenceClient
from .reranker import DEFAULT_RERANKER_MODEL, rank_passages
from .schemas import RAGResponse
from .sources import source_citation

FAITHFULNESS_CHECK_FAILED = "faithfulness_check_failed"
NO_EVIDENCE_AVAILABLE = "no_evidence_available"
NO_ACTIONABLE_CLAIMS_SCORE = 0.8
_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
_QUOTE_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_IDENTIFIER_RE = re.compile(r"\b[A-Z][A-Z0-9-]*(?:\s+[A-Z0-9][A-Z0-9-]*)+\b")
_CITATION_RE = re.compile(r"\[[^\[\]\n]{1,200}:[^\[\]\n]{1,200}\]")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")
_MAX_QUOTE_CHARS = 600
_TARGET_WINDOW_CHARS = 400
_MAX_WINDOW_CHARS = 600
_CLAIM_STOPWORDS = {
    "and",
    "are",
    "for",
    "from",
    "has",
    "have",
    "that",
    "the",
    "this",
    "was",
    "were",
    "with",
}
_LOW_INFORMATION_QUOTES = _CLAIM_STOPWORDS | {
    "a",
    "an",
    "as",
    "at",
    "by",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "to",
}


@dataclass(frozen=True)
class CitedClaim:
    claim_id: str
    text: str
    source_labels: tuple[str, ...]


@dataclass(frozen=True)
class AttributionCandidate:
    claim_id: str
    claim: str
    source_label: str
    quote: str
    support_score: float


@dataclass(frozen=True)
class FaithfulnessResult:
    score: float
    unfounded_claims: list[str]
    failed: bool = False
    attributions: list[AttributionCandidate] = field(default_factory=list)
    evidence_windows: dict[str, list[EvidenceWindow]] = field(default_factory=dict)


def evaluate_faithfulness(
    response: RAGResponse,
    *,
    ollama: InferenceClient,
    model: str | None,
    reranker_model: str = DEFAULT_RERANKER_MODEL,
    reranker_cache_dir: str | None = "/models/fastembed",
    support_threshold: float = 0.8,
    cancellation_token: QueryCancellationToken | None = None,
) -> FaithfulnessResult:
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    sources = evidence_sources(response)
    if not sources:
        return FaithfulnessResult(score=0.0, unfounded_claims=[NO_EVIDENCE_AVAILABLE])
    claims = cited_claims(response.answer)

    try:
        raw = call_with_optional_cancellation(
            ollama.judge_faithfulness,
            cancellation_token,
            prompt=build_faithfulness_prompt(answer=response.answer, sources=sources),
            model=model,
        )
        result = parse_faithfulness_result(raw)
        filtered = _filter_actionable_claims(result, response.answer)
        return FaithfulnessResult(
            score=filtered.score,
            unfounded_claims=filtered.unfounded_claims,
            failed=filtered.failed,
            attributions=filtered.attributions,
            evidence_windows=build_evidence_windows(
                claims,
                sources,
                filtered.attributions,
                reranker_model=reranker_model,
                reranker_cache_dir=reranker_cache_dir,
                support_threshold=support_threshold,
            ),
        )
    except QueryCancelled:
        raise
    except (ServiceRequestError, TypeError, ValueError):
        return FaithfulnessResult(
            score=0.0,
            unfounded_claims=[FAITHFULNESS_CHECK_FAILED],
            failed=True,
            evidence_windows=build_evidence_windows(
                claims,
                sources,
                [],
                reranker_model=reranker_model,
                reranker_cache_dir=reranker_cache_dir,
                support_threshold=support_threshold,
            ),
        )


def evidence_sources(response: RAGResponse) -> list[SourceAnchor]:
    seen: set[tuple[str, str]] = set()
    sources: list[SourceAnchor] = []

    def add(source: SourceAnchor) -> None:
        key = (source.doc_id, source.chunk_id)
        if key in seen:
            return
        seen.add(key)
        sources.append(source)

    for source in response.sources:
        add(source)
    for conflict in response.conflict_detail or []:
        add(conflict.source_a)
        add(conflict.source_b)
    return sources


def build_faithfulness_prompt(*, answer: str, sources: list[SourceAnchor]) -> str:
    claims = cited_claims(answer)
    claim_block = "\n".join(
        f"{claim.claim_id}\nClaim: {claim.text}\nCited sources: {', '.join(claim.source_labels)}"
        for claim in claims
    ) or "No cited factual claims were detected."
    evidence = "\n\n".join(format_source(source) for source in sources)
    return (
        "Judge whether the cited answer claims are supported by their cited evidence. "
        "Use only the evidence below. Do not use outside knowledge. "
        "A cited source must directly support every material fact in its claim. "
        "Treat missing, unknown, or unrelated citations as unfounded. "
        "Return only valid compact JSON with keys score and unfounded_claims. "
        "score must be a number from 0 to 1. "
        "unfounded_claims must contain only exact Claim text values copied from Claims, not claim IDs, citations, or explanations. "
        "A fully supported answer scores 1.0; invented or unsupported facts score below 0.8.\n\n"
        f"Claims:\n{claim_block}\n\nEvidence:\n{evidence}"
    )


def format_source(source: SourceAnchor) -> str:
    page = f" {page_label(source)}" if page_label(source) else ""
    return (
        f"{source_citation(source)} {source.doc_title}{page}\n"
        f"Group: {source.group_path}\n"
        f"Effective date: {source.effective_date or 'unknown'}\n"
        f"Excerpt:\n{source.excerpt}"
    )


def page_label(source: SourceAnchor) -> str:
    start = source.page_start or source.page
    end = source.page_end or start
    if start is None:
        return ""
    return f"pages {start}-{end}" if end and end != start else f"page {start}"


def parse_faithfulness_result(raw: str) -> FaithfulnessResult:
    payload = _load_json_object(raw)
    score = _clamp_score(payload.get("score"))
    claims = _parse_claims(payload.get("unfounded_claims"))
    return FaithfulnessResult(
        score=score,
        unfounded_claims=claims,
        attributions=_parse_attributions(payload.get("attributions")),
    )


def _load_json_object(raw: str) -> dict[str, object]:
    text = raw.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("faithfulness judge did not return JSON") from None
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("faithfulness judge returned non-object JSON")
    return value


def _clamp_score(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("faithfulness score must be numeric")
    if isinstance(value, str):
        value = float(value)
    if not isinstance(value, int | float):
        raise ValueError("faithfulness score must be numeric")
    return max(0.0, min(1.0, float(value)))


def _parse_claims(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("unfounded_claims must be a list")
    claims: list[str] = []
    for item in value[:8]:
        claim = _claim_text(item)
        if claim:
            claims.append(claim)
    return claims


def _parse_attributions(value: object) -> list[AttributionCandidate]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("attributions must be a list")
    attributions: list[AttributionCandidate] = []
    for item in value[:24]:
        if not isinstance(item, dict):
            continue
        claim_id = _optional_text(item.get("claim_id"))
        claim = _optional_text(item.get("claim"))
        source_label = _optional_text(item.get("source_label") or item.get("source") or item.get("citation"))
        quote = _optional_text(item.get("quote"))
        if not source_label or not quote or (not claim_id and not claim):
            continue
        try:
            support_score = _clamp_score(item.get("support_score", 0.0))
        except (TypeError, ValueError):
            continue
        attributions.append(
            AttributionCandidate(
                claim_id=claim_id,
                claim=claim,
                source_label=source_label,
                quote=quote,
                support_score=support_score,
            )
        )
    return attributions


def _filter_actionable_claims(result: FaithfulnessResult, answer: str) -> FaithfulnessResult:
    filtered = [claim for claim in result.unfounded_claims if _claim_appears_in_answer(claim, answer)]
    if filtered == result.unfounded_claims:
        return result
    score = result.score
    if not filtered:
        score = max(score, NO_ACTIONABLE_CLAIMS_SCORE)
    return FaithfulnessResult(
        score=score,
        unfounded_claims=filtered,
        failed=result.failed,
        attributions=result.attributions,
        evidence_windows=result.evidence_windows,
    )


def cited_claims(answer: str) -> list[CitedClaim]:
    claims: list[CitedClaim] = []
    for piece in _claim_pieces(answer):
        labels = tuple(dict.fromkeys(_CITATION_RE.findall(piece)))
        if not labels:
            continue
        claim_text = _clean_claim_text(_CITATION_RE.sub("", piece))
        if not claim_text or not _QUOTE_TOKEN_RE.search(claim_text):
            continue
        claims.append(CitedClaim(claim_id=f"claim-{len(claims) + 1}", text=claim_text, source_labels=labels))
    return claims


def build_evidence_windows(
    claims: list[CitedClaim],
    sources: list[SourceAnchor],
    attributions: list[AttributionCandidate],
    *,
    reranker_model: str,
    reranker_cache_dir: str | None,
    support_threshold: float,
) -> dict[str, list[EvidenceWindow]]:
    sources_by_label = {source_citation(source): source for source in sources}
    windows: dict[str, list[EvidenceWindow]] = {}
    for claim in claims:
        for source_label in claim.source_labels:
            source = sources_by_label.get(source_label)
            if source is None:
                continue
            verified = _verified_window_for_claim(
                claim,
                source_label,
                source,
                attributions,
                support_threshold=support_threshold,
            )
            window = verified or _semantic_window_for_claim(
                claim,
                source,
                reranker_model=reranker_model,
                reranker_cache_dir=reranker_cache_dir,
            )
            if window is not None:
                windows.setdefault(source_label, []).append(window)
    for source_windows in windows.values():
        source_windows.sort(key=lambda item: item.support_status != "verified")
    return windows


def attributed_sources(sources: list[SourceAnchor], result: FaithfulnessResult) -> list[SourceAnchor]:
    attributed: list[SourceAnchor] = []
    for source in sources:
        windows = result.evidence_windows.get(source_citation(source), [])
        status = "complete" if windows or not result.failed else "unavailable"
        attributed.append(source.model_copy(update={"evidence_windows": windows, "attribution_status": status}))
    return attributed


def _verified_window_for_claim(
    claim: CitedClaim,
    source_label: str,
    source: SourceAnchor,
    attributions: list[AttributionCandidate],
    *,
    support_threshold: float,
) -> EvidenceWindow | None:
    matching = [
        item
        for item in attributions
        if (
            item.source_label == source_label
            and item.support_score >= support_threshold
            and _candidate_matches_claim(item, claim)
        )
    ]
    for candidate in sorted(matching, key=lambda item: len(item.quote)):
        quote_range = _verified_quote_range(source.excerpt, candidate.quote)
        if quote_range is None:
            continue
        quote_start, quote_end = quote_range
        return _window_from_range(
            source,
            claim=claim,
            focus_start=quote_start,
            focus_end=quote_end,
            support_status="verified",
            support_score=candidate.support_score,
            quote_start=quote_start,
            quote_end=quote_end,
            quote=candidate.quote,
        )
    return None


def _semantic_window_for_claim(
    claim: CitedClaim,
    source: SourceAnchor,
    *,
    reranker_model: str,
    reranker_cache_dir: str | None,
) -> EvidenceWindow | None:
    spans = _sentence_spans(source.excerpt)
    if not spans:
        return None
    passages = [source.excerpt[start:end].strip() for start, end in spans]
    try:
        ranked = rank_passages(
            claim.text,
            passages,
            model_name=reranker_model,
            cache_dir=reranker_cache_dir,
        )
    except (RuntimeError, TypeError, ValueError):
        return None
    if not ranked:
        return None
    best_index, raw_score = ranked[0]
    focus_start, focus_end = spans[best_index]
    return _window_from_range(
        source,
        claim=claim,
        focus_start=focus_start,
        focus_end=focus_end,
        support_status="semantic_fallback",
        support_score=_score_probability(raw_score),
    )


def _window_from_range(
    source: SourceAnchor,
    *,
    claim: CitedClaim,
    focus_start: int,
    focus_end: int,
    support_status: str,
    support_score: float,
    quote_start: int | None = None,
    quote_end: int | None = None,
    quote: str = "",
) -> EvidenceWindow:
    source_start, source_end = _context_window(source.excerpt, focus_start, focus_end)
    passage = source.excerpt[source_start:source_end]
    highlights = (
        [HighlightRange(start=quote_start - source_start, end=quote_end - source_start)]
        if quote_start is not None and quote_end is not None
        else []
    )
    fields = [
        field.model_copy(update={"supports_claim": _field_supports_quote(field, quote)})
        for field in source.attribution_fields
    ]
    return EvidenceWindow(
        claim_id=claim.claim_id,
        claim=claim.text,
        kind=source.attribution_kind,
        passage=passage,
        highlight_ranges=highlights,
        support_status=support_status,
        support_score=support_score,
        source_start=source_start,
        source_end=source_end,
        quote_start=quote_start,
        quote_end=quote_end,
        truncated_start=source_start > 0,
        truncated_end=source_end < len(source.excerpt),
        table_title=source.attribution_table_title or None,
        fields=fields,
    )


def _verified_quote_range(source_text: str, quote: str) -> tuple[int, int] | None:
    normalized_quote = _normalize_text(quote)
    quote_tokens = _QUOTE_TOKEN_RE.findall(normalized_quote)
    if (
        not normalized_quote
        or len(quote) > _MAX_QUOTE_CHARS
        or (len(quote_tokens) == 1 and quote_tokens[0] in _LOW_INFORMATION_QUOTES)
    ):
        return None
    normalized_source, positions = _normalize_with_positions(source_text)
    match_start = normalized_source.find(normalized_quote)
    if match_start < 0:
        return None
    match_end = match_start + len(normalized_quote)
    return positions[match_start], positions[match_end - 1] + 1


def _normalize_text(value: str) -> str:
    normalized, _ = _normalize_with_positions(value)
    return normalized


def _normalize_with_positions(value: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    positions: list[int] = []
    pending_space: int | None = None
    for index, character in enumerate(value):
        if character.isspace():
            if chars and chars[-1] != " " and pending_space is None:
                pending_space = index
            continue
        if pending_space is not None:
            chars.append(" ")
            positions.append(pending_space)
            pending_space = None
        for lowered in character.lower():
            chars.append(lowered)
            positions.append(index)
    return "".join(chars), positions


def _context_window(text: str, focus_start: int, focus_end: int) -> tuple[int, int]:
    spans = _sentence_spans(text)
    intersecting = [
        index
        for index, (start, end) in enumerate(spans)
        if start < focus_end and end > focus_start
    ]
    if intersecting:
        first = max(0, intersecting[0] - 1)
        last = min(len(spans) - 1, intersecting[-1] + 1)
        start, end = spans[first][0], spans[last][1]
    else:
        start, end = focus_start, focus_end
    if end - start <= _MAX_WINDOW_CHARS:
        return _trim_window(text, start, end)
    focus_length = focus_end - focus_start
    target = min(_MAX_WINDOW_CHARS, max(_TARGET_WINDOW_CHARS, focus_length))
    side_budget = max(0, target - focus_length)
    start = max(start, focus_start - side_budget // 2)
    end = min(end, start + target)
    if end - start < target:
        start = max(0, end - target)
    return _trim_window(text, start, end, focus_start=focus_start, focus_end=focus_end)


def _trim_window(
    text: str,
    start: int,
    end: int,
    *,
    focus_start: int | None = None,
    focus_end: int | None = None,
) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if focus_start is not None and start > 0 and start < focus_start:
        word_end = text.find(" ", start)
        if 0 <= word_end < focus_start:
            start = word_end + 1
    if focus_end is not None and end < len(text) and end > focus_end:
        word_start = text.rfind(" ", focus_end, end)
        if word_start > focus_end:
            end = word_start
    return start, end


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for boundary in _SENTENCE_BOUNDARY_RE.finditer(text):
        end = boundary.start()
        span = _non_whitespace_span(text, start, end)
        if span is not None:
            spans.append(span)
        start = boundary.end()
    span = _non_whitespace_span(text, start, len(text))
    if span is not None:
        spans.append(span)
    return spans


def _non_whitespace_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None


def _candidate_matches_claim(candidate: AttributionCandidate, claim: CitedClaim) -> bool:
    if candidate.claim_id:
        return candidate.claim_id == claim.claim_id
    return _normalize_text(candidate.claim) == _normalize_text(claim.text)


def _field_supports_quote(field: EvidenceField, quote: str) -> bool:
    if not quote:
        return False
    value = _normalize_text(field.value)
    normalized_quote = _normalize_text(quote)
    return bool(value and normalized_quote and (value in normalized_quote or normalized_quote in value))


def _score_probability(score: float) -> float:
    bounded = max(-20.0, min(20.0, score))
    return 1.0 / (1.0 + math.exp(-bounded))


def _claim_pieces(answer: str) -> list[str]:
    pieces = re.split(r"(?<=[.!?])\s+(?!\[)|(?<=\])\s+|\n+", answer)
    return [piece.strip() for piece in pieces if piece.strip()]


def _clean_claim_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("|", " ").strip(" \t\r\n-*#`"))


def _optional_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _claim_appears_in_answer(claim: str, answer: str) -> bool:
    answer_normalized = answer.lower()
    identifiers = [identifier.lower() for identifier in _IDENTIFIER_RE.findall(claim)]
    if identifiers and not all(identifier in answer_normalized for identifier in identifiers):
        return False

    claim_terms = _claim_terms(claim)
    if not claim_terms:
        return False
    answer_terms = _claim_terms(answer)
    return len(claim_terms & answer_terms) / len(claim_terms) >= 0.5


def _claim_terms(text: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in _TERM_RE.finditer(text)
        if match.group(0).lower() not in _CLAIM_STOPWORDS
    }


def _claim_text(value: object) -> str:
    if isinstance(value, str):
        return _clean_unfounded_claim(value)
    if isinstance(value, dict):
        for key in ("claim", "text", "statement"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return _clean_unfounded_claim(item)
    raise ValueError("unfounded_claims must contain claim strings")


def _clean_unfounded_claim(value: str) -> str:
    claim = value.strip()
    claim = re.sub(r"^claim-\d+\s*:\s*", "", claim, flags=re.IGNORECASE)
    claim = re.sub(r"\s*\|\s*cited sources?:.*$", "", claim, flags=re.IGNORECASE)
    return claim.strip()
