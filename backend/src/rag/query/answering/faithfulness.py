"""Faithfulness judging for synthesized RAG answers."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Literal

from rag.shared.contracts.evidence import EvidenceField, EvidenceWindow, HighlightRange, SourceAnchor
from rag.query.cancellation import QueryCancellationToken, QueryCancelled, call_with_optional_cancellation
from rag.query.http import ServiceRequestError
from rag.query.inference import InferenceClient
from rag.query.reranker import DEFAULT_RERANKER_MODEL, rank_passages
from rag.query.schemas import RAGResponse
from rag.query.sources import source_citation
from rag.shared.contracts.rag_defaults import RerankerDevice

from .entailment import ENTAILMENT_THRESHOLD, score_entailment

FAITHFULNESS_CHECK_FAILED = "faithfulness_check_failed"
NO_EVIDENCE_AVAILABLE = "no_evidence_available"
NO_ACTIONABLE_CLAIMS_SCORE = 0.8
FAITHFULNESS_VERDICT_THRESHOLD = 0.8
_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
_QUOTE_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_IDENTIFIER_RE = re.compile(r"\b[A-Z][A-Z0-9-]*(?:\s+[A-Z0-9][A-Z0-9-]*)+\b")
_CITATION_RE = re.compile(r"\[[^\[\]\n]{1,200}:[^\[\]\n]{1,200}\]")
_LIST_MARKER_RE = re.compile(r"^\d{1,3}[.)]$")
_LIST_ITEM_PREFIX_RE = re.compile(
    r"^(?P<marker>[-*+]|\d{1,3}[.)])\s+"
)
_CLAIM_BOUNDARY_RE = re.compile(
    r"(?P<newline>\r?\n+)|"
    r"(?P<sentence>(?<=[.!?])[ \t]+(?!\[))|"
    r"(?P<citation>(?<=\])[ \t]+(?!\[))"
)
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")
_NON_TERMINAL_ABBREVIATION_RE = re.compile(
    r"(?:\b(?:dr|e\.g|etc|i\.e|jnr|jr|mr|mrs|ms|prof|sr|st|vs)\.|(?:\b[A-Za-z]\.){2,})$",
    re.IGNORECASE,
)
_MAX_QUOTE_CHARS = 600
_MAX_ADAPTIVE_CLAIMS = 3
_TARGET_WINDOW_CHARS = 400
_MAX_WINDOW_CHARS = 600
_ORDER_CUE_RE = re.compile(
    r"\b(?:from\s+(?:least|lowest|earliest|first)\s+to\s+"
    r"(?:most|highest|latest|last)(?:\s+mature)?|"
    r"in\s+(?:(?:ascending|descending|chronological|reverse chronological)\s+)?"
    r"order)\b",
    re.IGNORECASE,
)
_LIST_COUNT_TOKEN = (
    r"(?:[1-9]|1[0-2]|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve)"
)
_STATED_LIST_COUNT_RE = re.compile(
    rf"\b(?P<count>{_LIST_COUNT_TOKEN})\b"
    r"(?:\s+[A-Za-z][A-Za-z0-9_-]*){0,3}\s+"
    r"(?:approaches|categories|characteristics|items|levels|phases|principles|"
    r"requirements|stages|steps|types)\b",
    re.IGNORECASE,
)
_LIST_INTRO_RE = re.compile(r"\s*(?:,\s*)?are\s+", re.IGNORECASE)
_LIST_LABEL_START_RE = re.compile(r"[A-Z0-9]")
_LIST_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_NEGATION_TOKENS = frozenset({"neither", "never", "no", "nor", "not", "without"})
_REQUIRED_VERDICT_KEYS = {
    "score",
    "unfounded_claims",
    "responsive",
    "missing_aspects",
}
_OPTIONAL_VERDICT_KEYS = {"attributions"}
_FAITHFULNESS_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
        "unfounded_claims": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
        },
        "responsive": {"type": "boolean"},
        "missing_aspects": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
        },
    },
    "required": sorted(_REQUIRED_VERDICT_KEYS),
}
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
_QUESTION_STOPWORDS = _CLAIM_STOPWORDS | {
    "give",
    "how",
    "list",
    "name",
    "please",
    "tell",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
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
    is_list_item: bool = False
    starts_new_line: bool = False
    list_marker: str | None = None


@dataclass(frozen=True)
class _ClaimPiece:
    text: str
    starts_new_line: bool
    is_list_item: bool
    list_marker: str | None


@dataclass(frozen=True)
class _CountedListRelation:
    header: CitedClaim
    items: tuple[CitedClaim, ...]
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
    outcome: Literal["pass", "fail", "unavailable"] = "pass"
    responsive: bool = True
    missing_aspects: list[str] = field(default_factory=list)
    attributions: list[AttributionCandidate] = field(default_factory=list)
    evidence_windows: dict[str, list[EvidenceWindow]] = field(default_factory=dict)


def evaluate_faithfulness(
    response: RAGResponse,
    *,
    question: str | None = None,
    ollama: InferenceClient,
    model: str | None,
    reranker_model: str = DEFAULT_RERANKER_MODEL,
    reranker_cache_dir: str | None = "/models/fastembed",
    reranker_device: RerankerDevice = "auto",
    cancellation_token: QueryCancellationToken | None = None,
) -> FaithfulnessResult:
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    sources = evidence_sources(response)
    if not sources:
        return FaithfulnessResult(
            score=0.0,
            unfounded_claims=[NO_EVIDENCE_AVAILABLE],
            outcome="fail",
            responsive=False,
        )
    claims = cited_claims(response.answer)

    try:
        raw = call_with_optional_cancellation(
            ollama.judge_faithfulness,
            cancellation_token,
            prompt=build_faithfulness_prompt(
                question=question,
                answer=response.answer,
                sources=sources,
            ),
            model=model,
            json_schema=_FAITHFULNESS_JSON_SCHEMA,
        )
        result = parse_faithfulness_result(raw)
        filtered = _filter_actionable_claims(result, response.answer)
        score = _faithfulness_score_from_claims(
            claims,
            filtered.unfounded_claims,
        )
        return FaithfulnessResult(
            score=score,
            unfounded_claims=filtered.unfounded_claims,
            outcome=(
                "fail"
                if (
                    score < FAITHFULNESS_VERDICT_THRESHOLD
                    or not filtered.responsive
                )
                else "pass"
            ),
            responsive=filtered.responsive,
            missing_aspects=filtered.missing_aspects,
            attributions=filtered.attributions,
            evidence_windows=build_evidence_windows(
                claims,
                sources,
                filtered.attributions,
                reranker_model=reranker_model,
                reranker_cache_dir=reranker_cache_dir,
                reranker_device=reranker_device,
                support_threshold=FAITHFULNESS_VERDICT_THRESHOLD,
            ),
        )
    except QueryCancelled:
        raise
    except (ServiceRequestError, TypeError, ValueError):
        return FaithfulnessResult(
            score=0.0,
            unfounded_claims=[FAITHFULNESS_CHECK_FAILED],
            outcome="unavailable",
            evidence_windows=build_evidence_windows(
                claims,
                sources,
                [],
                reranker_model=reranker_model,
                reranker_cache_dir=reranker_cache_dir,
                reranker_device=reranker_device,
                support_threshold=FAITHFULNESS_VERDICT_THRESHOLD,
            ),
        )


def screen_faithfulness(
    response: RAGResponse,
    *,
    route_plan: object | None,
    reranker_model: str = DEFAULT_RERANKER_MODEL,
    reranker_cache_dir: str | None = "/models/fastembed",
    reranker_device: RerankerDevice = "auto",
) -> FaithfulnessResult | None:
    """Verify a directly cited low-risk lookup without invoking an LLM judge."""
    if (
        route_plan is None
        or getattr(route_plan, "risk_level", None) != "low"
        or getattr(route_plan, "public_intent", None) != "factual_simple"
        or getattr(route_plan, "response_mode", None) != "lookup"
        or getattr(route_plan, "coverage", None) != "focused"
        or getattr(route_plan, "temporal_scope", None) != "current"
        or response.conflict_flag
    ):
        return None

    if len(cited_claims(response.answer)) > _MAX_ADAPTIVE_CLAIMS:
        return None
    return verify_cited_claims(
        response,
        question=(
            getattr(route_plan, "resolved_query", None)
            or getattr(route_plan, "original_query", None)
        ),
        reranker_model=reranker_model,
        reranker_cache_dir=reranker_cache_dir,
        reranker_device=reranker_device,
    )


def verify_cited_claims(
    response: RAGResponse,
    *,
    question: str | None = None,
    reranker_model: str = DEFAULT_RERANKER_MODEL,
    reranker_cache_dir: str | None = "/models/fastembed",
    reranker_device: RerankerDevice = "auto",
) -> FaithfulnessResult | None:
    """Return a deterministic pass only when every cited claim is entailed."""
    sources = evidence_sources(response)
    claims = cited_claims(response.answer)
    if (
        not sources
        or not claims
        or not _all_material_claims_are_cited(response.answer)
        or not _counted_lists_are_complete(claims)
    ):
        return None
    sources_by_label = {source_citation(source): source for source in sources}
    known_labels = set(sources_by_label)
    if any(
        label not in known_labels
        for claim in claims
        for label in claim.source_labels
    ):
        return None

    (
        structural_claim_ids,
        list_item_claim_ids,
        counted_list_relations,
    ) = _counted_list_claim_roles(claims)
    counted_list_header_ids = _counted_list_header_ids(claims)
    if structural_claim_ids != counted_list_header_ids:
        return None
    claims_by_id = {claim.claim_id: claim for claim in claims}
    structural_claim_ids = {
        claim_id
        for claim_id in structural_claim_ids
        if (claim := claims_by_id.get(claim_id)) is not None
        if any(
            (source := sources_by_label.get(label)) is not None
            and _counted_list_header_support(
                claim.text,
                source.excerpt,
                question=question,
            )
            for label in claim.source_labels
        )
    }
    if structural_claim_ids != counted_list_header_ids:
        return None
    counted_list_relations = [
        relation
        for relation in counted_list_relations
        if relation.header.claim_id in structural_claim_ids
    ]
    windows = build_evidence_windows(
        claims,
        sources,
        [],
        reranker_model=reranker_model,
        reranker_cache_dir=reranker_cache_dir,
        reranker_device=reranker_device,
        support_threshold=FAITHFULNESS_VERDICT_THRESHOLD,
    )
    candidates = [
        (label, index, window)
        for label, source_windows in windows.items()
        for index, window in enumerate(source_windows)
        if window.claim_id not in structural_claim_ids
    ]
    support_scores = {
        (label, index): 1.0
        for label, index, window in candidates
        if (
            _near_verbatim_support(window.claim, window.passage)
            or (
                window.claim_id in list_item_claim_ids
                and _near_verbatim_list_item_support(
                    window.claim,
                    window.passage,
                )
            )
        )
    }
    hypotheses = [
        (label, index, window, hypothesis)
        for label, index, window in candidates
        if (label, index) not in support_scores
        for hypothesis in _entailment_hypotheses(window.claim)
    ]
    scores = []
    if hypotheses:
        try:
            scores = score_entailment(
                [
                    (window.passage, hypothesis)
                    for _, _, window, hypothesis in hypotheses
                ],
                cache_dir=reranker_cache_dir,
            )
        except (RuntimeError, TypeError, ValueError):
            return None
    for (label, index, _, _), score in zip(hypotheses, scores, strict=True):
        key = (label, index)
        support_scores[key] = max(
            support_scores.get(key, 0.0),
            score.entailment,
        )
    for label, index, window in candidates:
        windows[label][index] = window.model_copy(
            update={"support_score": support_scores.get((label, index), 0.0)}
        )
    if any(
        not any(
            window.claim_id == claim.claim_id
            and window.support_score >= ENTAILMENT_THRESHOLD
            for label in claim.source_labels
            for window in windows.get(label, [])
        )
        for claim in claims
        if claim.claim_id not in structural_claim_ids
    ):
        return None
    if not _counted_list_relations_are_supported(
        counted_list_relations,
        windows=windows,
        reranker_cache_dir=reranker_cache_dir,
    ):
        return None

    return FaithfulnessResult(
        score=1.0,
        unfounded_claims=[],
        responsive=True,
        evidence_windows=windows,
    )


def ordered_answer_covers_question(response: RAGResponse, question: str) -> bool:
    """Recognize a complete cited ordered-list answer for disagreement handling."""
    if not question or not _ORDER_CUE_RE.search(question):
        return False
    claims = cited_claims(response.answer)
    if not any(_ordered_list_projection(claim.text) for claim in claims):
        return False
    question_terms = {
        match.group(0).lower()
        for match in _TERM_RE.finditer(question)
        if match.group(0).lower() not in _QUESTION_STOPWORDS
    }
    answer_terms = {
        match.group(0).lower()
        for match in _TERM_RE.finditer(response.answer)
        if match.group(0).lower() not in _QUESTION_STOPWORDS
    }
    if not question_terms:
        return False
    if len(question_terms & answer_terms) / len(question_terms) < 0.8:
        return False
    question_count = _stated_list_count(question)
    answer_count = _stated_list_count(response.answer)
    return question_count is None or question_count == answer_count


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


def build_faithfulness_prompt(
    *,
    answer: str,
    sources: list[SourceAnchor],
    question: str | None = None,
) -> str:
    claims = cited_claims(answer)
    claim_block = "\n".join(
        f"{claim.claim_id}\nClaim: {claim.text}\nCited sources: {', '.join(claim.source_labels)}"
        for claim in claims
    ) or "No cited factual claims were detected."
    evidence = "\n\n".join(format_source(source) for source in sources)
    return (
        "Judge whether the cited answer claims are supported by their cited evidence "
        "and whether the answer directly addresses the user's question. "
        "Use only the evidence below. Do not use outside knowledge. "
        "A cited source must directly support every material fact in its claim. "
        "Treat missing, unknown, or unrelated citations as unfounded. "
        "Return only valid compact JSON with keys score, unfounded_claims, responsive, and missing_aspects. "
        "score must be a number from 0 to 1. "
        "unfounded_claims must contain only exact Claim text values copied from Claims, not claim IDs, citations, or explanations. "
        "responsive must be true only when the answer supplies the entity, attribute, comparison, steps, or other information requested. "
        "missing_aspects must list concise parts of the question that the answer did not address. "
        "A fully supported answer scores 1.0; invented or unsupported facts score below 0.8.\n\n"
        f"Question:\n{question or 'Not provided'}\n\nClaims:\n{claim_block}\n\nEvidence:\n{evidence}"
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
    keys = set(payload)
    if not _REQUIRED_VERDICT_KEYS.issubset(keys) or not keys.issubset(
        _REQUIRED_VERDICT_KEYS | _OPTIONAL_VERDICT_KEYS
    ):
        raise ValueError("faithfulness judge returned an invalid object shape")
    score = _clamp_score(payload.get("score"))
    claims = _parse_claims(payload.get("unfounded_claims"))
    responsive = payload["responsive"]
    if not isinstance(responsive, bool):
        raise ValueError("faithfulness responsive must be boolean")
    return FaithfulnessResult(
        score=score,
        unfounded_claims=claims,
        responsive=responsive,
        missing_aspects=_parse_text_list(payload.get("missing_aspects")),
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


def _parse_text_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("missing_aspects must be a list")
    return [
        text
        for item in value[:8]
        if (text := _optional_text(item))
    ]


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
        outcome=result.outcome,
        responsive=result.responsive,
        missing_aspects=result.missing_aspects,
        attributions=result.attributions,
        evidence_windows=result.evidence_windows,
    )


def _faithfulness_score_from_claims(
    claims: list[CitedClaim],
    unfounded_claims: list[str],
) -> float:
    """Derive groundedness from auditable claim verdicts, not an LLM scalar."""
    if not claims:
        return 0.0 if unfounded_claims else 1.0
    unique_unfounded = {
        _normalize_text(claim)
        for claim in unfounded_claims
        if _normalize_text(claim)
    }
    unfounded_count = min(len(claims), len(unique_unfounded))
    return (len(claims) - unfounded_count) / len(claims)


def cited_claims(answer: str) -> list[CitedClaim]:
    claims: list[CitedClaim] = []
    for piece in _claim_piece_records(answer):
        labels = tuple(dict.fromkeys(_CITATION_RE.findall(piece.text)))
        if not labels:
            continue
        raw_claim = _CITATION_RE.sub("", piece.text).strip()
        prefix = _LIST_ITEM_PREFIX_RE.match(raw_claim)
        list_marker = (
            prefix.group("marker")
            if prefix is not None
            else piece.list_marker
        )
        claim_text = _clean_claim_text(
            raw_claim[prefix.end() :] if prefix is not None else raw_claim
        )
        if not claim_text or not _QUOTE_TOKEN_RE.search(claim_text):
            continue
        claims.append(
            CitedClaim(
                claim_id=f"claim-{len(claims) + 1}",
                text=claim_text,
                source_labels=labels,
                is_list_item=piece.is_list_item or list_marker is not None,
                starts_new_line=piece.starts_new_line,
                list_marker=list_marker,
            )
        )
    return claims


def build_evidence_windows(
    claims: list[CitedClaim],
    sources: list[SourceAnchor],
    attributions: list[AttributionCandidate],
    *,
    reranker_model: str,
    reranker_cache_dir: str | None,
    reranker_device: RerankerDevice = "auto",
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
                reranker_device=reranker_device,
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
        status = (
            "complete"
            if windows or result.outcome != "unavailable"
            else "unavailable"
        )
        attributed.append(source.model_copy(update={"evidence_windows": windows, "attribution_status": status}))
    return attributed


def structured_retrieval_attributed_sources(
    answer: str, sources: list[SourceAnchor]
) -> list[SourceAnchor]:
    claims = cited_claims(answer)
    attributed: list[SourceAnchor] = []
    for source in sources:
        if (
            source.attribution_kind != "table_row"
            or not source.attribution_fields
            or not source.excerpt
        ):
            attributed.append(source)
            continue
        label = source_citation(source)
        source_claims = [claim for claim in claims if label in claim.source_labels]
        if source_claims:
            claim = CitedClaim(
                claim_id=source_claims[0].claim_id,
                text=" ".join(item.text for item in source_claims),
                source_labels=(label,),
            )
            windows = [
                _window_from_range(
                    source,
                    claim=claim,
                    focus_start=0,
                    focus_end=len(source.excerpt),
                    support_status="semantic_fallback",
                    support_score=_structured_claim_coverage(
                        claim, source.attribution_fields
                    ),
                    quote=claim.text,
                )
            ]
        else:
            windows = []
        attributed.append(
            source.model_copy(
                update={
                    "evidence_windows": windows,
                    "attribution_status": "complete" if windows else "pending",
                }
            )
        )
    return attributed


def _structured_claim_coverage(
    claim: CitedClaim, fields: list[EvidenceField]
) -> float:
    return sum(_field_supports_quote(field, claim.text) for field in fields) / len(fields)


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
    reranker_device: RerankerDevice,
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
            device=reranker_device,
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
        support_score=max(
            _score_probability(raw_score),
            _lexical_support_score(claim.text, source),
        ),
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


def _lexical_support_score(claim: str, source: SourceAnchor) -> float:
    claim_terms = _claim_terms(claim)
    if not claim_terms:
        return 0.0
    evidence_terms = _claim_terms(f"{source.doc_title}\n{source.excerpt}")
    return len(claim_terms & evidence_terms) / len(claim_terms)


def _near_verbatim_support(claim: str, passage: str) -> bool:
    claim_tokens = [
        token.lower() for token in _QUOTE_TOKEN_RE.findall(_normalize_text(claim))
    ]
    evidence_tokens = [
        token.lower()
        for token in _QUOTE_TOKEN_RE.findall(_normalize_text(passage))
    ]
    if len(claim_tokens) < 2 or not _claim_terms(claim):
        return False
    width = len(claim_tokens)
    return any(
        evidence_tokens[start : start + width] == claim_tokens
        for start in range(len(evidence_tokens) - width + 1)
    )


def _near_verbatim_list_item_support(claim: str, passage: str) -> bool:
    claim_tokens = [
        token.lower() for token in _QUOTE_TOKEN_RE.findall(_normalize_text(claim))
    ]
    evidence_tokens = [
        token.lower()
        for token in _QUOTE_TOKEN_RE.findall(_normalize_text(passage))
    ]
    if (
        not claim_tokens
        or len(claim_tokens) > 12
        or not _claim_terms(claim)
        or any(token in _NEGATION_TOKENS for token in claim_tokens)
    ):
        return False
    if len(claim_tokens) == 1:
        token = claim_tokens[0]
        if (
            len(token) < 4
            or token.isdigit()
            or token in _LOW_INFORMATION_QUOTES
        ):
            return False
    width = len(claim_tokens)
    candidate_widths = (width,) if width == 1 else (width, width + 1)
    for candidate_width in candidate_widths:
        for start in range(len(evidence_tokens) - candidate_width + 1):
            candidate = evidence_tokens[start : start + candidate_width]
            context = evidence_tokens[
                max(0, start - 3) : start + candidate_width
            ]
            if any(token in _NEGATION_TOKENS for token in context):
                continue
            if _tokens_match_with_one_insertion(claim_tokens, candidate):
                return True
    return False


def _tokens_match_with_one_insertion(
    expected: list[str],
    actual: list[str],
) -> bool:
    expected_index = 0
    insertion_count = 0
    for token in actual:
        if (
            expected_index < len(expected)
            and _simple_inflection_root(token)
            == _simple_inflection_root(expected[expected_index])
        ):
            expected_index += 1
            continue
        if token.isdigit():
            return False
        insertion_count += 1
        if insertion_count > 1:
            return False
    return expected_index == len(expected)


def _simple_inflection_root(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith("es"):
        without_es = token[:-2]
        if without_es.endswith(("s", "x", "z", "ch", "sh")):
            return without_es
    if len(token) > 3 and token.endswith("s") and not token.endswith(
        ("as", "is", "ss", "us")
    ):
        return token[:-1]
    return token


def _counted_list_header_support(
    claim: str,
    passage: str,
    *,
    question: str | None,
) -> bool:
    count_terms = set(_LIST_COUNT_WORDS) | {
        str(value) for value in range(1, 13)
    }
    topic_terms = _claim_terms(claim).difference(
        count_terms,
        {"below", "following", "listed"},
    )
    if not topic_terms:
        return False
    evidence_terms = _claim_terms(passage)
    evidence_coverage = len(topic_terms.intersection(evidence_terms)) / len(
        topic_terms
    )
    if evidence_coverage >= 0.75:
        return True
    if not question or evidence_coverage < 0.5:
        return False
    combined_terms = evidence_terms | _claim_terms(question)
    return len(topic_terms.intersection(combined_terms)) / len(topic_terms) >= 0.75


def _counted_list_claim_roles(
    claims: list[CitedClaim],
) -> tuple[set[str], set[str], list[_CountedListRelation]]:
    structural_claim_ids: set[str] = set()
    item_claim_ids: set[str] = set()
    relations: list[_CountedListRelation] = []
    for index, claim in enumerate(claims):
        if not claim.text.rstrip().endswith(":"):
            continue
        stated_count = _stated_list_count(claim.text)
        items = _contiguous_list_items(claims, index)
        common_labels = set(claim.source_labels)
        for item in items:
            common_labels.intersection_update(item.source_labels)
        if (
            stated_count is None
            or len(items) != stated_count
            or not common_labels
        ):
            continue
        structural_claim_ids.add(claim.claim_id)
        item_claim_ids.update(item.claim_id for item in items)
        relations.append(
            _CountedListRelation(
                header=claim,
                items=tuple(items),
                source_labels=tuple(
                    label
                    for label in claim.source_labels
                    if label in common_labels
                ),
            )
        )
    return structural_claim_ids, item_claim_ids, relations


def _counted_list_relations_are_supported(
    relations: list[_CountedListRelation],
    *,
    windows: dict[str, list[EvidenceWindow]],
    reranker_cache_dir: str | None,
) -> bool:
    candidates: list[tuple[str, str, str]] = []
    for relation in relations:
        claim_ids = {
            relation.header.claim_id,
            *(item.claim_id for item in relation.items),
        }
        hypothesis = _counted_list_hypothesis(relation)
        for label in relation.source_labels:
            passages = list(
                dict.fromkeys(
                    window.passage
                    for window in windows.get(label, [])
                    if window.claim_id in claim_ids and window.passage
                )
            )
            if passages:
                candidates.append(
                    (
                        relation.header.claim_id,
                        "\n".join(passages),
                        hypothesis,
                    )
                )
    if len({candidate[0] for candidate in candidates}) != len(relations):
        return False
    if not candidates:
        return True
    try:
        scores = score_entailment(
            [(passage, hypothesis) for _, passage, hypothesis in candidates],
            cache_dir=reranker_cache_dir,
        )
    except (RuntimeError, TypeError, ValueError):
        return False
    supported = {
        relation_id
        for (relation_id, _, _), score in zip(
            candidates,
            scores,
            strict=True,
        )
        if score.entailment >= ENTAILMENT_THRESHOLD
    }
    return all(
        relation.header.claim_id in supported
        for relation in relations
    )


def _counted_list_hypothesis(relation: _CountedListRelation) -> str:
    header = relation.header.text.rstrip().removesuffix(":").rstrip()
    items = "; ".join(
        item.text.rstrip().rstrip(".;:")
        for item in relation.items
    )
    return f"{header} {items}."


def _counted_lists_are_complete(claims: list[CitedClaim]) -> bool:
    for index, claim in enumerate(claims):
        if not claim.text.rstrip().endswith(":"):
            continue
        stated_count = _stated_list_count(claim.text)
        if (
            stated_count is not None
            and len(_contiguous_list_items(claims, index)) != stated_count
        ):
            return False
    return True


def _counted_list_header_ids(claims: list[CitedClaim]) -> set[str]:
    return {
        claim.claim_id
        for index, claim in enumerate(claims)
        if claim.text.rstrip().endswith(":")
        if (stated_count := _stated_list_count(claim.text)) is not None
        if len(_contiguous_list_items(claims, index)) == stated_count
    }


def _contiguous_list_items(
    claims: list[CitedClaim],
    header_index: int,
) -> list[CitedClaim]:
    items: list[CitedClaim] = []
    marker_family: str | None = None
    for claim in claims[header_index + 1 :]:
        if claim.is_list_item:
            family = _list_marker_family(claim.list_marker)
            if family is None:
                break
            if marker_family is None:
                marker_family = family
            elif family != marker_family:
                break
            if family == "numbered" and _list_marker_number(
                claim.list_marker
            ) != len(items) + 1:
                break
            items.append(claim)
            continue
        if claim.starts_new_line:
            break
    return items


def _list_marker_family(marker: str | None) -> str | None:
    if marker in {"-", "*", "+"}:
        return "bullet"
    return "numbered" if marker and _LIST_MARKER_RE.fullmatch(marker) else None


def _list_marker_number(marker: str | None) -> int | None:
    if not marker:
        return None
    match = re.match(r"\d{1,3}", marker)
    return int(match.group(0)) if match else None


def _all_material_claims_are_cited(answer: str) -> bool:
    for piece in _claim_pieces(answer):
        claim_text = _clean_claim_text(_CITATION_RE.sub("", piece))
        if (
            _QUOTE_TOKEN_RE.search(claim_text)
            and not _LIST_MARKER_RE.fullmatch(claim_text)
            and not _CITATION_RE.search(piece)
        ):
            return False
    return True


def _claim_pieces(answer: str) -> list[str]:
    return [piece.text for piece in _claim_piece_records(answer)]


def _claim_piece_records(answer: str) -> list[_ClaimPiece]:
    pieces: list[_ClaimPiece] = []
    start = 0
    preceding_boundary: str | None = None
    for boundary in _CLAIM_BOUNDARY_RE.finditer(answer):
        _append_claim_piece(
            pieces,
            answer[start : boundary.start()],
            preceding_boundary=preceding_boundary,
        )
        start = boundary.end()
        preceding_boundary = boundary.lastgroup
    _append_claim_piece(
        pieces,
        answer[start:],
        preceding_boundary=preceding_boundary,
    )
    return pieces


def _append_claim_piece(
    pieces: list[_ClaimPiece],
    value: str,
    *,
    preceding_boundary: str | None,
) -> None:
    text = value.strip()
    if not text:
        return
    starts_new_line = preceding_boundary == "newline"
    previous_text = (
        _CITATION_RE.sub("", pieces[-1].text).rstrip()
        if pieces
        else ""
    )
    previous_is_marker = bool(
        pieces
        and _LIST_MARKER_RE.fullmatch(_clean_claim_text(previous_text))
    )
    if (
        pieces
        and preceding_boundary == "sentence"
        and (
            previous_is_marker
            or _NON_TERMINAL_ABBREVIATION_RE.search(previous_text)
        )
    ):
        previous = pieces[-1]
        pieces[-1] = _ClaimPiece(
            text=f"{previous.text} {text}",
            starts_new_line=previous.starts_new_line,
            is_list_item=previous.is_list_item or previous_is_marker,
            list_marker=(
                previous.list_marker
                or (previous_text if previous_is_marker else None)
            ),
        )
        return
    prefix = _LIST_ITEM_PREFIX_RE.match(text)
    standalone_marker = (
        text
        if _LIST_MARKER_RE.fullmatch(_clean_claim_text(text))
        else None
    )
    list_marker = (
        prefix.group("marker")
        if prefix is not None
        else standalone_marker
    )
    pieces.append(
        _ClaimPiece(
            text=text,
            starts_new_line=starts_new_line,
            is_list_item=list_marker is not None,
            list_marker=list_marker,
        )
    )


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


def _entailment_hypotheses(claim: str) -> tuple[str, ...]:
    ordered_projection = _ordered_list_projection(claim)
    return (
        (claim, ordered_projection)
        if ordered_projection is not None
        else (claim,)
    )


def _ordered_list_projection(claim: str) -> str | None:
    parts = _ordered_list_parts(claim)
    if parts is None:
        return None
    prefix, raw_items, colonless = parts
    item_text = raw_items.strip().rstrip(".!?")
    if not item_text:
        return None
    items = [
        re.sub(
            r"^(?:and|then)\s+",
            "",
            item.strip(" \t\r\n-*#`_"),
            flags=re.IGNORECASE,
        )
        for item in re.split(r"\s*[,;]\s*", item_text)
    ]
    if len(items) == 1:
        items = re.split(r"\s+(?:and|then)\s+", item_text, flags=re.IGNORECASE)
    items = [
        item.strip(" \t\r\n-*#`_")
        for item in items
        if _TERM_RE.search(item)
    ]
    if not 2 <= len(items) <= 12 or any(len(item) > 120 for item in items):
        return None
    if colonless and any(not _LIST_LABEL_START_RE.match(item) for item in items):
        return None
    stated_count = _stated_list_count(prefix)
    if stated_count is not None and stated_count != len(items):
        return None
    if len(items) == 2:
        remainder = items[1]
    else:
        remainder = f"{', '.join(items[1:-1])}, and {items[-1]}"
    return f"{items[0]} is followed by {remainder}."


def _ordered_list_parts(claim: str) -> tuple[str, str, bool] | None:
    prefix, separator, raw_items = claim.partition(":")
    if separator:
        return (prefix, raw_items, False) if _ORDER_CUE_RE.search(prefix) else None
    cue = _ORDER_CUE_RE.search(claim)
    if cue is None:
        return None
    intro = _LIST_INTRO_RE.match(claim, cue.end())
    prefix = claim[: cue.end()]
    if intro is None or _stated_list_count(prefix) is None:
        return None
    return prefix, claim[intro.end() :], True


def _stated_list_count(text: str) -> int | None:
    count_match = _STATED_LIST_COUNT_RE.search(text)
    if count_match is None:
        return None
    count_text = count_match.group("count").lower()
    return (
        int(count_text)
        if count_text.isdigit()
        else _LIST_COUNT_WORDS[count_text]
    )


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
