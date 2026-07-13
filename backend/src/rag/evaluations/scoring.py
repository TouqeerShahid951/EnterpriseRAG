"""Deterministic scoring and failure attribution for RAG evaluation cases."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ..schemas.evaluations import EvaluationCase, EvaluationFailureStage
from ..query.schemas import RAGResponse
from ..shared.evaluation.answer_checks import LiteralCheckResult, evaluate_literal_checks


FAILURE_STAGE_PRIORITY: tuple[EvaluationFailureStage, ...] = (
    "runtime",
    "dataset",
    "ingestion/indexing",
    "retrieval",
    "reranking/source_selection",
    "answer_content",
    "citation",
    "faithfulness",
    "degradation",
    "latency",
)

_CITATION_RE = re.compile(r"\[[^\[\]\r\n]{1,200}:\d+\]")
AnswerContentJudge = Callable[[EvaluationCase, RAGResponse, LiteralCheckResult], dict[str, object]]


def score_case_result(
    case: EvaluationCase,
    *,
    response: RAGResponse | None,
    diagnostic: dict[str, Any],
    error_message: str | None = None,
    answer_content_judge: AnswerContentJudge | None = None,
) -> dict[str, Any]:
    checks = _base_checks(case, diagnostic)
    failure_stages: list[EvaluationFailureStage] = []

    if error_message:
        checks["runtime"] = {"passed": False, "error": error_message}
        failure_stages.append("runtime")
    if not _has_any_expectation(case):
        checks["dataset"] = {"passed": False, "message": "Case has no answer, source, citation, or faithfulness expectation."}
        failure_stages.append("dataset")
    if not checks["ingestion_indexing"]["passed"]:
        failure_stages.append("ingestion/indexing")
    if not checks["retrieval"]["passed"]:
        failure_stages.append("retrieval")

    if response is None:
        passed = False
        primary = _primary_stage(failure_stages)
        return {
            "passed": passed,
            "primary_failure_stage": primary,
            "failure_stages": _ordered_stages(failure_stages),
            "checks": checks,
        }

    literal = evaluate_literal_checks(response.answer, case.must_include, case.must_not_include)
    llm_verifier = _llm_answer_content_verdict(
        case,
        response,
        literal,
        answer_content_judge=answer_content_judge,
    )
    answer_content_passed = literal.passed or _llm_answer_content_passed(llm_verifier)
    final_source_passed, final_source_titles = _source_doc_pass(
        case.expected_source_docs,
        [source.model_dump() for source in response.sources],
    )
    min_sources_passed = len(response.sources) >= case.min_sources
    reranking_passed = (
        True
        if not diagnostic.get("expected_docs_retrieved") or not case.expected_source_docs
        else final_source_passed
    )
    citation_passed = not case.must_cite_source or _has_citation(response.answer)
    faithfulness_passed = response.faithfulness_score >= case.min_faithfulness_score and not response.unfounded_claims
    degradation_passed = case.allow_degraded or not response.degraded
    latency_passed = case.latency_threshold_ms is None or response.latency_ms <= case.latency_threshold_ms

    checks.update(
        {
            "answer_content": {
                "passed": answer_content_passed,
                "missing_must_include": [] if answer_content_passed else list(literal.missing_must_include),
                "present_must_not_include": list(literal.present_must_not_include),
                "literal_passed": literal.passed,
                "literal_missing_must_include": list(literal.missing_must_include),
                "llm_verifier": llm_verifier,
            },
            "final_sources": {
                "passed": final_source_passed and min_sources_passed,
                "expected_source_docs": case.expected_source_docs,
                "source_doc_titles": final_source_titles,
                "min_sources": case.min_sources,
                "actual_source_count": len(response.sources),
            },
            "reranking_source_selection": {
                "passed": reranking_passed,
                "message": "Expected source was retrieved diagnostically but omitted from final answer sources."
                if not reranking_passed
                else None,
            },
            "citation": {
                "passed": citation_passed,
                "required": case.must_cite_source,
            },
            "faithfulness": {
                "passed": faithfulness_passed,
                "score": response.faithfulness_score,
                "min_score": case.min_faithfulness_score,
                "status": response.faithfulness_status,
                "unfounded_claims": response.unfounded_claims,
            },
            "degradation": {
                "passed": degradation_passed,
                "allow_degraded": case.allow_degraded,
                "degraded": response.degraded,
                "degraded_reason": response.degraded_reason,
            },
            "latency": {
                "passed": latency_passed,
                "latency_ms": response.latency_ms,
                "threshold_ms": case.latency_threshold_ms,
            },
        }
    )
    if not answer_content_passed:
        failure_stages.append("answer_content")
    if not reranking_passed:
        failure_stages.append("reranking/source_selection")
    if not citation_passed:
        failure_stages.append("citation")
    if not faithfulness_passed:
        failure_stages.append("faithfulness")
    if not degradation_passed:
        failure_stages.append("degradation")
    if not latency_passed:
        failure_stages.append("latency")

    # A missing final source is answer/source selection unless diagnostic retrieval already failed.
    if not final_source_passed and checks["retrieval"]["passed"]:
        failure_stages.append("reranking/source_selection")
    if not min_sources_passed and "reranking/source_selection" not in failure_stages:
        failure_stages.append("reranking/source_selection")

    ordered = _ordered_stages(failure_stages)
    return {
        "passed": not ordered,
        "primary_failure_stage": _primary_stage(ordered),
        "failure_stages": ordered,
        "checks": checks,
    }


def _llm_answer_content_verdict(
    case: EvaluationCase,
    response: RAGResponse,
    literal: LiteralCheckResult,
    *,
    answer_content_judge: AnswerContentJudge | None,
) -> dict[str, object] | None:
    if (
        answer_content_judge is None
        or literal.passed
        or not literal.missing_must_include
        or literal.present_must_not_include
    ):
        return None
    try:
        return answer_content_judge(case, response, literal)
    except Exception as exc:  # noqa: BLE001 - scoring should record judge errors, not fail the run
        return {
            "used": True,
            "status": "error",
            "passed": False,
            "error_type": type(exc).__name__,
        }


def _llm_answer_content_passed(verdict: dict[str, object] | None) -> bool:
    if verdict is None or verdict.get("passed") is not True:
        return False
    return not verdict.get("missing_must_include") and not verdict.get("present_must_not_include")


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for item in results if item.get("passed"))
    latencies = [int(item.get("latency_ms") or 0) for item in results if int(item.get("latency_ms") or 0) >= 0]
    failure_breakdown: dict[str, int] = {}
    for item in results:
        primary = item.get("primary_failure_stage")
        if primary:
            failure_breakdown[str(primary)] = failure_breakdown.get(str(primary), 0) + 1
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": _rate(passed, total),
        "retrieval_pass_rate": _check_rate(results, "retrieval"),
        "citation_pass_rate": _check_rate(results, "citation"),
        "faithfulness_pass_rate": _check_rate(results, "faithfulness"),
        "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
        "max_latency_ms": max(latencies, default=0),
        "failure_breakdown": failure_breakdown,
    }


def _base_checks(case: EvaluationCase, diagnostic: dict[str, Any]) -> dict[str, Any]:
    expected_docs_indexed = bool(diagnostic.get("expected_docs_indexed", True))
    expected_docs_retrieved = bool(diagnostic.get("expected_docs_retrieved", True))
    expected_pages_retrieved = bool(diagnostic.get("expected_pages_retrieved", True))
    return {
        "dataset": {"passed": _has_any_expectation(case)},
        "ingestion_indexing": {
            "passed": expected_docs_indexed,
            "expected_source_docs": case.expected_source_docs,
            "indexed_source_docs": diagnostic.get("indexed_source_docs", []),
            "missing_indexed_source_docs": diagnostic.get("missing_indexed_source_docs", []),
        },
        "retrieval": {
            "passed": expected_docs_retrieved and expected_pages_retrieved,
            "expected_source_docs": case.expected_source_docs,
            "retrieved_source_docs": diagnostic.get("retrieved_source_docs", []),
            "acceptable_source_pages": case.acceptable_source_pages,
            "retrieved_pages": diagnostic.get("retrieved_pages", []),
            "top_k": diagnostic.get("top_k"),
            "error": diagnostic.get("error"),
        },
    }


def _has_any_expectation(case: EvaluationCase) -> bool:
    return bool(
        case.must_include
        or case.must_not_include
        or case.expected_source_docs
        or case.acceptable_source_pages
        or case.min_sources
        or case.must_cite_source
        or case.min_faithfulness_score
        or case.latency_threshold_ms
    )


def _source_doc_pass(expected: list[str], actual: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    if not expected:
        return True, [str(item.get("doc_title") or "") for item in actual]
    expected_norm = {_normalize_title(item) for item in expected}
    actual_titles = [str(item.get("doc_title") or "") for item in actual]
    actual_norm = {_normalize_title(item) for item in actual_titles}
    return expected_norm.issubset(actual_norm), actual_titles


def _normalize_title(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _has_citation(answer: str) -> bool:
    return bool(_CITATION_RE.search(answer))


def _ordered_stages(stages: list[EvaluationFailureStage]) -> list[EvaluationFailureStage]:
    unique = set(stages)
    return [stage for stage in FAILURE_STAGE_PRIORITY if stage in unique]


def _primary_stage(stages: list[EvaluationFailureStage]) -> EvaluationFailureStage | None:
    ordered = _ordered_stages(stages)
    return ordered[0] if ordered else None


def _rate(passed: int, total: int) -> float:
    return round(passed / total, 4) if total else 0.0


def _check_rate(results: list[dict[str, Any]], key: str) -> float:
    relevant = [item for item in results if key in dict(item.get("checks") or {})]
    if not relevant:
        return 0.0
    passed = sum(1 for item in relevant if dict(item.get("checks") or {}).get(key, {}).get("passed"))
    return _rate(passed, len(relevant))
