"""Deterministic scoring and failure attribution for RAG evaluation cases."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .answer_verifier import ANSWER_VERIFIER_VERSION
from rag.evaluations.schemas import EvaluationCase, EvaluationFailureStage
from ..query.schemas import RAGResponse
from rag.query.sources import parse_citation_tokens, source_citation
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

AnswerContentJudge = Callable[[EvaluationCase, RAGResponse, LiteralCheckResult], dict[str, object]]


def score_case_result(
    case: EvaluationCase,
    *,
    response: RAGResponse | None,
    diagnostic: dict[str, Any],
    error_message: str | None = None,
    answer_content_judge: AnswerContentJudge | None = None,
    interrupt_error_types: tuple[type[Exception], ...] = (),
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
        interrupt_error_types=interrupt_error_types,
    )
    semantic_judge_required = bool(case.expected_answer)
    answer_content_passed = (
        not literal.present_must_not_include
        and (
            _required_semantic_judge_passed(llm_verifier)
            if semantic_judge_required
            else literal.passed or _llm_answer_content_passed(llm_verifier)
        )
    )
    final_source_passed, final_source_titles = _source_doc_pass(
        case.expected_source_docs,
        [source.model_dump() for source in response.sources],
    )
    min_sources_passed = len(response.sources) >= case.min_sources
    legacy_reranking_passed = (
        True
        if not diagnostic.get("expected_docs_retrieved") or not case.expected_source_docs
        else final_source_passed
    )
    evidence_check = dict(checks.get("evidence_expectations") or {})
    evidence_required = evidence_check.get("required") is True
    evidence_pre_rerank_passed = evidence_check.get("pre_rerank_passed") is True
    evidence_post_rerank_passed = evidence_check.get("post_rerank_passed") is True
    evidence_reranking_passed = (
        not evidence_required
        or not evidence_pre_rerank_passed
        or evidence_post_rerank_passed
    )
    reranking_passed = legacy_reranking_passed and evidence_reranking_passed
    citation = _citation_check(case, response)
    faithfulness = _faithfulness_check(case, response)
    degradation_passed = case.allow_degraded or not response.degraded
    latency_passed = case.latency_threshold_ms is None or response.latency_ms <= case.latency_threshold_ms

    checks.update(
        {
            "answer_content": {
                "passed": answer_content_passed,
                "required": semantic_judge_required,
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
                "message": _reranking_failure_message(
                    legacy_reranking_passed=legacy_reranking_passed,
                    evidence_reranking_passed=evidence_reranking_passed,
                ),
                "evidence_expectations": {
                    "reranked": dict(evidence_check.get("stages") or {}).get(
                        "reranked", {}
                    ),
                    "final_evidence": dict(evidence_check.get("stages") or {}).get(
                        "final_evidence", {}
                    ),
                },
            },
            "citation": citation,
            "faithfulness": faithfulness,
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
    if not citation["passed"]:
        failure_stages.append("citation")
    if faithfulness["status"] == "failed" or (faithfulness["required"] and faithfulness["status"] != "passed"):
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
    interrupt_error_types: tuple[type[Exception], ...],
) -> dict[str, object] | None:
    required = bool(case.expected_answer)
    if answer_content_judge is None:
        if required:
            return {
                "used": False,
                "version": ANSWER_VERIFIER_VERSION,
                "status": "unavailable",
                "passed": False,
            }
        return None
    if not required and (literal.passed or not literal.missing_must_include or literal.present_must_not_include):
        return None
    try:
        return answer_content_judge(case, response, literal)
    except Exception as exc:  # noqa: BLE001 - scoring should record judge errors, not fail the run
        if isinstance(exc, interrupt_error_types):
            raise
        return {
            "used": True,
            "version": ANSWER_VERIFIER_VERSION,
            "status": "error",
            "passed": False,
            "error_type": type(exc).__name__,
        }


def _llm_answer_content_passed(verdict: dict[str, object] | None) -> bool:
    if verdict is None or verdict.get("passed") is not True:
        return False
    return not verdict.get("missing_must_include") and not verdict.get("present_must_not_include")


def _required_semantic_judge_passed(verdict: dict[str, object] | None) -> bool:
    return bool(verdict and verdict.get("status") == "checked" and _llm_answer_content_passed(verdict))


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for item in results if item.get("passed"))
    latencies = [int(item.get("latency_ms") or 0) for item in results if int(item.get("latency_ms") or 0) >= 0]
    failure_breakdown: dict[str, int] = {}
    for item in results:
        primary = item.get("primary_failure_stage")
        if primary:
            failure_breakdown[str(primary)] = failure_breakdown.get(str(primary), 0) + 1
    summary = {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": _rate(passed, total),
        "retrieval_pass_rate": _check_rate(results, "retrieval"),
        "citation_pass_rate": _check_rate(results, "citation"),
        "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
        "max_latency_ms": max(latencies, default=0),
        "failure_breakdown": failure_breakdown,
    }
    summary.update(_faithfulness_summary(results))
    summary.update(_semantic_judge_summary(results))
    return summary


def _faithfulness_check(case: EvaluationCase, response: RAGResponse) -> dict[str, Any]:
    required = case.must_cite_source or case.min_faithfulness_score > 0
    source_status = response.faithfulness_status
    if source_status == "checked":
        passed = response.faithfulness_score >= case.min_faithfulness_score and not response.unfounded_claims
        return {
            "passed": passed,
            "status": "passed" if passed else "failed",
            "source_status": source_status,
            "score": response.faithfulness_score,
            "min_score": case.min_faithfulness_score,
            "required": required,
            "unfounded_claims": response.unfounded_claims,
        }
    return {
        "passed": None,
        "status": "error" if source_status == "failed" else "not_evaluated",
        "source_status": source_status,
        "score": None,
        "min_score": case.min_faithfulness_score,
        "required": required,
        "unfounded_claims": response.unfounded_claims,
    }


def _faithfulness_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    checks = [
        dict(item.get("checks") or {}).get("faithfulness", {})
        for item in results
        if "faithfulness" in dict(item.get("checks") or {})
    ]
    evaluated = [check for check in checks if check.get("status") in {"passed", "failed"}]
    passed = sum(1 for check in evaluated if check.get("status") == "passed")
    return {
        "faithfulness_pass_rate": _rate(passed, len(evaluated)) if evaluated else None,
        "faithfulness_coverage_rate": _rate(len(evaluated), len(checks)),
        "faithfulness_evaluated_count": len(evaluated),
        "faithfulness_not_evaluated_count": sum(1 for check in checks if check.get("status") == "not_evaluated"),
        "faithfulness_error_count": sum(1 for check in checks if check.get("status") == "error"),
    }


def _semantic_judge_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    required = [
        dict(item.get("checks") or {}).get("answer_content", {})
        for item in results
        if dict(item.get("checks") or {}).get("answer_content", {}).get("required") is True
    ]
    evaluated = [
        check
        for check in required
        if dict(check.get("llm_verifier") or {}).get("status") == "checked"
    ]
    passed = sum(1 for check in evaluated if check.get("passed") is True)
    errors = sum(
        1 for check in required if dict(check.get("llm_verifier") or {}).get("status") == "error"
    )
    return {
        "semantic_judge_pass_rate": _rate(passed, len(evaluated)) if evaluated else None,
        "semantic_judge_coverage_rate": _rate(len(evaluated), len(required)),
        "semantic_judge_required_count": len(required),
        "semantic_judge_evaluated_count": len(evaluated),
        "semantic_judge_not_evaluated_count": len(required) - len(evaluated) - errors,
        "semantic_judge_error_count": errors,
    }


def _base_checks(case: EvaluationCase, diagnostic: dict[str, Any]) -> dict[str, Any]:
    expected_docs_indexed = bool(diagnostic.get("expected_docs_indexed", True))
    expected_docs_retrieved = bool(diagnostic.get("expected_docs_retrieved", True))
    expected_pages_retrieved = bool(diagnostic.get("expected_pages_retrieved", True))
    evidence = _evidence_expectation_check(case, diagnostic)
    legacy_pages = _legacy_page_expectation_check(case, diagnostic)
    return {
        "dataset": {"passed": _has_any_expectation(case)},
        "ingestion_indexing": {
            "passed": expected_docs_indexed
            and evidence["resolution_passed"]
            and legacy_pages["resolution_passed"],
            "expected_source_docs": case.expected_source_docs,
            "indexed_source_docs": diagnostic.get("indexed_source_docs", []),
            "missing_indexed_source_docs": diagnostic.get("missing_indexed_source_docs", []),
            "evidence_expectations_resolved": evidence["resolution_passed"],
            "legacy_page_expectation_resolved": legacy_pages[
                "resolution_passed"
            ],
        },
        "retrieval": {
            "passed": expected_docs_retrieved
            and expected_pages_retrieved
            and evidence["pre_rerank_passed"],
            "expected_source_docs": case.expected_source_docs,
            "retrieved_source_docs": diagnostic.get("retrieved_source_docs", []),
            "acceptable_source_pages": case.acceptable_source_pages,
            "retrieved_pages": diagnostic.get("retrieved_pages", []),
            "evidence_expectations": {
                "retrieved": evidence["stages"].get("retrieved", {}),
                "rerank_input": evidence["stages"].get("rerank_input", {}),
            },
            "legacy_page_expectation": legacy_pages,
            "top_k": diagnostic.get("top_k"),
            "error": diagnostic.get("error"),
        },
        "evidence_expectations": evidence,
        "legacy_page_expectation": legacy_pages,
    }


def _evidence_expectation_check(
    case: EvaluationCase, diagnostic: dict[str, Any]
) -> dict[str, Any]:
    required = bool(case.evidence_expectations)
    raw = diagnostic.get("evidence_expectations")
    evidence = dict(raw) if isinstance(raw, dict) else {}
    raw_stages = evidence.get("stages")
    stages = dict(raw_stages) if isinstance(raw_stages, dict) else {}
    resolution_passed = (
        bool(evidence.get("resolution_passed")) if required else True
    )
    stage_passes = {
        name: _evidence_stage_passed(stages, name=name, required=required)
        for name in ("retrieved", "rerank_input", "reranked", "final_evidence")
    }
    pre_rerank_passed = (
        resolution_passed
        and stage_passes["retrieved"]
        and stage_passes["rerank_input"]
    )
    # Final evidence is the contract boundary after parent promotion and budgeting.
    post_rerank_passed = stage_passes["final_evidence"]
    return {
        "required": required,
        "passed": resolution_passed
        and pre_rerank_passed
        and post_rerank_passed,
        "resolution_passed": resolution_passed,
        "pre_rerank_passed": pre_rerank_passed,
        "post_rerank_passed": post_rerank_passed,
        "expectations": evidence.get("expectations", []),
        "stages": stages,
    }


def _evidence_stage_passed(
    stages: dict[str, Any], *, name: str, required: bool
) -> bool:
    if not required:
        return True
    stage = stages.get(name)
    return bool(isinstance(stage, dict) and stage.get("passed") is True)


def _legacy_page_expectation_check(
    case: EvaluationCase, diagnostic: dict[str, Any]
) -> dict[str, Any]:
    required = bool(case.acceptable_source_pages)
    raw = diagnostic.get("legacy_page_expectation")
    legacy = dict(raw) if isinstance(raw, dict) else {}
    resolution_passed = (
        legacy.get("resolution_status") == "resolved" if required else True
    )
    return {
        **legacy,
        "required": required,
        "deprecated": True,
        "resolution_passed": resolution_passed,
        "passed": bool(legacy.get("passed")) if required else True,
    }


def _has_any_expectation(case: EvaluationCase) -> bool:
    return bool(
        case.expected_answer
        or case.must_include
        or case.must_not_include
        or case.expected_source_docs
        or case.acceptable_source_pages
        or case.evidence_expectations
        or case.min_sources
        or case.must_cite_source
        or case.min_faithfulness_score
        or case.latency_threshold_ms
    )


def _reranking_failure_message(
    *,
    legacy_reranking_passed: bool,
    evidence_reranking_passed: bool,
) -> str | None:
    if not evidence_reranking_passed:
        return "Expected document-bound evidence survived retrieval but was lost before final evidence selection."
    if not legacy_reranking_passed:
        return "Expected source was retrieved diagnostically but omitted from final answer sources."
    return None


def _source_doc_pass(expected: list[str], actual: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    if not expected:
        return True, [str(item.get("doc_title") or "") for item in actual]
    expected_norm = {_normalize_title(item) for item in expected}
    actual_titles = [str(item.get("doc_title") or "") for item in actual]
    actual_norm = {_normalize_title(item) for item in actual_titles}
    return expected_norm.issubset(actual_norm), actual_titles


def _normalize_title(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _citation_check(case: EvaluationCase, response: RAGResponse) -> dict[str, Any]:
    citations = list(parse_citation_tokens(response.answer))
    returned = {source_citation(source) for source in response.sources}
    resolved = [citation for citation in citations if citation in returned]
    unresolved = [citation for citation in citations if citation not in returned]
    return {
        "passed": (bool(citations) or not case.must_cite_source) and not unresolved,
        "required": case.must_cite_source,
        "citations": citations,
        "resolved_citations": resolved,
        "unresolved_citations": unresolved,
    }


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
