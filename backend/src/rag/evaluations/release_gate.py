"""Fail-closed release checks over two pinned RAG evaluation runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import re
import unicodedata
from typing import Any

from .runtime_pins import RUNTIME_PINS_KEY


_REQUIRED_PINS = (
    "dataset_semantic_hash",
    "ranking_gold_hash",
    "corpus_manifest_hash",
    "rag_config_hash",
    "query_settings_hash",
    "model_identifiers_hash",
    "prompt_policy_version",
    "image_digest",
    "active_generation",
    "active_document_content_hash",
    "host_profile",
)
_SPECIAL_TYPES = {"exhaustive_list", "cross_document", "relational_multi_hop"}


def evaluate_release_gate(
    runs: list[dict[str, Any]],
    *,
    ranking_gold: dict[str, Any],
    dataset_cases: list[dict[str, Any]],
    expected_pins: dict[str, Any],
) -> dict[str, Any]:
    """Return a JSON-safe release report; unavailable evidence always blocks."""
    failures: set[str] = set()
    gold_cases = _indexed_rows(ranking_gold.get("cases"), "gold", failures)
    cases = _indexed_rows(dataset_cases, "dataset", failures)
    if ranking_gold.get("case_count") != len(gold_cases):
        failures.add("benchmark_case_count_mismatch")
    if set(gold_cases) != set(cases):
        failures.add("benchmark_case_ids_mismatch")
    for case_id in set(gold_cases) & set(cases):
        _validate_alignment(case_id, gold_cases[case_id], cases[case_id], failures)

    if len(runs) != 2:
        failures.add("requires_two_runs")
    run_ids = [str(run.get("id") or "") for run in runs]
    if len(run_ids) != len(set(run_ids)) or any(not run_id for run_id in run_ids):
        failures.add("requires_two_distinct_run_ids")
    _validate_expected_pins(expected_pins, failures)

    run_reports = [
        _evaluate_run(
            run,
            gold_cases=gold_cases,
            dataset_cases=cases,
            expected_pins=expected_pins,
        )
        for run in runs
    ]
    for report in run_reports:
        failures.update(report["failures"])
    if len(runs) == 2:
        _validate_pair(runs, failures)
    return {
        "passed": not failures,
        "failures": sorted(failures),
        "run_reports": run_reports,
    }


def _evaluate_run(
    run: dict[str, Any],
    *,
    gold_cases: dict[str, dict[str, Any]],
    dataset_cases: dict[str, dict[str, Any]],
    expected_pins: dict[str, Any],
) -> dict[str, Any]:
    run_id = str(run.get("id") or "missing")
    failures: set[str] = set()
    prefix = f"run:{run_id}"
    if run.get("status") != "complete":
        failures.add(f"{prefix}:not_complete")
    _validate_run_pins(run, expected_pins, failures, prefix)
    results = _indexed_rows(run.get("cases"), f"{prefix}:results", failures)
    expected_ids = set(gold_cases)
    if set(results) != expected_ids:
        failures.add(f"{prefix}:case_ids_mismatch")
    if run.get("case_count") != len(expected_ids):
        failures.add(f"{prefix}:case_count_mismatch")
    if run.get("completed_count") != len(expected_ids):
        failures.add(f"{prefix}:terminal_denominator_incomplete")

    correctness_required = correctness_passed = judge_checked = 0
    citation_required = citation_passed = citation_checked = 0
    faithfulness_required = faithfulness_passed = faithfulness_checked = 0
    ordinary_latencies: list[int] = []
    special_latencies: list[int] = []
    pre_location_total = pre_location_matched = 0
    special_location_total = special_location_matched = 0
    pre_exact_total = pre_exact_matched = 0
    exact_span_unavailable = False
    exhaustive_anchor_total = exhaustive_anchor_matched = 0
    exhaustive_anchor_unavailable = False
    reranker_candidates = reranker_scored = 0
    ranking_case_count = 0
    pre_top_ten_total = pre_top_ten_matched = 0
    post_top_ten_total = post_top_ten_matched = 0
    pre_reciprocal_rank_total = 0.0
    post_reciprocal_rank_total = 0.0

    for case_id in sorted(expected_ids & set(results) & set(dataset_cases)):
        result = results[case_id]
        case = dataset_cases[case_id]
        gold = gold_cases[case_id]
        case_prefix = f"{prefix}:case:{case_id}"
        if result.get("status") != "ok":
            failures.add(f"{case_prefix}:execution_error")
        checks = _dict(result.get("checks"))
        answer_check = _dict(checks.get("answer_content"))
        if case.get("expected_answer"):
            correctness_required += 1
            verdict = _dict(answer_check.get("llm_verifier"))
            if verdict.get("status") == "checked":
                judge_checked += 1
                correctness_passed += answer_check.get("passed") is True
            else:
                failures.add(f"{case_prefix}:metric_unavailable:semantic_judge")

        if case.get("must_cite_source"):
            citation_required += 1
            citation = _dict(checks.get("citation"))
            unresolved = citation.get("unresolved_citations")
            if isinstance(unresolved, list) and "passed" in citation:
                citation_checked += 1
                citation_passed += citation.get("passed") is True and not unresolved
            else:
                failures.add(f"{case_prefix}:metric_unavailable:citation_resolution")

        if case.get("must_cite_source") or float(
            case.get("min_faithfulness_score") or 0
        ) > 0:
            faithfulness_required += 1
            faithfulness = _dict(checks.get("faithfulness"))
            if faithfulness.get("status") in {"passed", "failed"}:
                faithfulness_checked += 1
                faithfulness_passed += faithfulness.get("status") == "passed"
            else:
                failures.add(f"{case_prefix}:metric_unavailable:faithfulness")

        latency = result.get("latency_ms")
        question_type = str(case.get("question_type") or "")
        is_special = question_type in _SPECIAL_TYPES
        is_exhaustive = question_type == "exhaustive_list"
        if isinstance(latency, int) and not isinstance(latency, bool) and latency >= 0:
            (special_latencies if is_special else ordinary_latencies).append(latency)
        else:
            failures.add(f"{case_prefix}:metric_unavailable:latency")

        diagnostic = _dict(result.get("diagnostic"))
        trace = diagnostic.get("retrieval_trace")
        stages = _trace_stages(trace)
        if not isinstance(trace, list):
            failures.add(f"{case_prefix}:metric_unavailable:retrieval_trace")
        pre_candidates = stages.get("rerank_input")
        reranked = stages.get("reranked")
        final_candidates = stages.get("final_evidence")
        for stage_name, candidates in (
            ("rerank_input", pre_candidates),
            ("reranked", reranked),
            ("final_evidence", final_candidates),
        ):
            if candidates is None:
                failures.add(f"{case_prefix}:metric_unavailable:{stage_name}")

        latest_pre_candidates = _latest_trace_candidates(trace, "rerank_input")
        latest_reranked = _latest_trace_candidates(trace, "reranked")
        _, ranking_obligation_total = _location_obligations(gold, [])
        if (
            ranking_obligation_total
            and latest_pre_candidates is not None
            and latest_reranked is not None
        ):
            pre_matched, pre_total = _location_obligations(
                gold, latest_pre_candidates[:10]
            )
            post_matched, post_total = _location_obligations(
                gold, latest_reranked[:10]
            )
            ranking_case_count += 1
            pre_top_ten_matched += pre_matched
            pre_top_ten_total += pre_total
            post_top_ten_matched += post_matched
            post_top_ten_total += post_total
            pre_reciprocal_rank_total += _reciprocal_rank_at_10(
                gold, latest_pre_candidates
            )
            post_reciprocal_rank_total += _reciprocal_rank_at_10(
                gold, latest_reranked
            )

        if pre_candidates is not None:
            matched, total = _location_obligations(gold, pre_candidates)
            pre_location_matched += matched
            pre_location_total += total
            if is_special:
                special_location_matched += matched
                special_location_total += total

        required_spans = gold.get("required_evidence_spans")
        if required_spans:
            expected_anchor_total = _gold_anchor_total(required_spans)
            anchor_counts = _evidence_anchor_counts(
                diagnostic,
                stage_name="rerank_input",
                expected_total=expected_anchor_total,
                accepted_statuses={"completed", "skipped", "partially_skipped"},
            )
            if anchor_counts is None:
                exact_span_unavailable = True
                failures.add(
                    f"{case_prefix}:metric_unavailable:pre_rerank_exact_span_recall"
                )
            else:
                matched, total = anchor_counts
                pre_exact_matched += matched
                pre_exact_total += total

        if reranked is not None:
            max_candidates = int(
                _dict(gold.get("reranker_gold")).get("max_candidates") or 0
            )
            if max_candidates and _max_attempt_size(trace, "rerank_input") > max_candidates:
                failures.add(f"{case_prefix}:reranker_candidate_cap_exceeded")
            required_status = _dict(gold.get("reranker_gold")).get(
                "required_status"
            )
            forbidden = set(
                _dict(gold.get("reranker_gold")).get("forbidden_statuses") or []
            )
            for candidate in reranked:
                reranker_candidates += 1
                status = candidate.get("rerank_status")
                if status == required_status and status not in forbidden:
                    reranker_scored += 1
                else:
                    failures.add(f"{case_prefix}:reranker_not_scored")

        if is_exhaustive and required_spans:
            anchor_counts = _evidence_anchor_counts(
                diagnostic,
                stage_name="final_evidence",
                expected_total=_gold_anchor_total(required_spans),
                accepted_statuses={"completed"},
            )
            if anchor_counts is None:
                exhaustive_anchor_unavailable = True
                failures.add(
                    f"{case_prefix}:metric_unavailable:final_exhaustive_anchor_recall"
                )
            else:
                matched, total = anchor_counts
                exhaustive_anchor_matched += matched
                exhaustive_anchor_total += total
        elif is_exhaustive and final_candidates is not None:
            matched, total = _location_obligations(gold, final_candidates)
            exhaustive_anchor_matched += matched
            exhaustive_anchor_total += total

    metrics = {
        "terminal_case_count": len(results),
        "pre_rerank_location_recall": _rate(
            pre_location_matched, pre_location_total
        ),
        "pre_rerank_exact_span_recall": (
            None
            if exact_span_unavailable
            else (
                _rate(pre_exact_matched, pre_exact_total)
                if pre_exact_total
                else _rate(pre_location_matched, pre_location_total)
            )
        ),
        "special_route_pre_rerank_location_recall": _rate(
            special_location_matched, special_location_total
        ),
        "final_exhaustive_anchor_recall": _rate(
            exhaustive_anchor_matched, exhaustive_anchor_total
        )
        if not exhaustive_anchor_unavailable
        else None,
        "semantic_judge_coverage": _rate(judge_checked, correctness_required),
        "answer_correctness": _rate(correctness_passed, correctness_required),
        "citation_resolution": _rate(citation_passed, citation_required),
        "citation_coverage": _rate(citation_checked, citation_required),
        "faithfulness_coverage": _rate(
            faithfulness_checked, faithfulness_required
        ),
        "claim_support_pass_rate": _rate(
            faithfulness_passed, faithfulness_required
        ),
        "reranker_scored_rate": _rate(reranker_scored, reranker_candidates),
        "pre_rerank_recall_at_10": _rate(
            pre_top_ten_matched, pre_top_ten_total
        ),
        "post_rerank_recall_at_10": _rate(
            post_top_ten_matched, post_top_ten_total
        ),
        "pre_rerank_mrr_at_10": (
            pre_reciprocal_rank_total / ranking_case_count
            if ranking_case_count
            else None
        ),
        "post_rerank_mrr_at_10": (
            post_reciprocal_rank_total / ranking_case_count
            if ranking_case_count
            else None
        ),
        "ordinary_p95_ms": _nearest_rank_p95(ordinary_latencies),
        "special_route_p95_ms": _nearest_rank_p95(special_latencies),
    }
    _apply_thresholds(
        metrics,
        failures,
        prefix,
        ordinary_required=any(
            str(case.get("question_type") or "") not in _SPECIAL_TYPES
            for case in dataset_cases.values()
        ),
        special_required=any(
            str(case.get("question_type") or "") in _SPECIAL_TYPES
            for case in dataset_cases.values()
        ),
        exhaustive_required=any(
            str(case.get("question_type") or "") == "exhaustive_list"
            for case in dataset_cases.values()
        ),
    )
    return {
        "run_id": run_id,
        "passed": not failures,
        "failures": sorted(failures),
        "metrics": metrics,
    }


def _apply_thresholds(
    metrics: dict[str, int | float | None],
    failures: set[str],
    prefix: str,
    *,
    ordinary_required: bool,
    special_required: bool,
    exhaustive_required: bool,
) -> None:
    thresholds = {
        "pre_rerank_location_recall": 0.98,
        "pre_rerank_exact_span_recall": 0.98,
        "special_route_pre_rerank_location_recall": 1.0,
        "semantic_judge_coverage": 1.0,
        "answer_correctness": 0.95,
        "citation_resolution": 1.0,
        "citation_coverage": 1.0,
        "faithfulness_coverage": 1.0,
        "claim_support_pass_rate": 0.95,
        "reranker_scored_rate": 1.0,
    }
    for name, minimum in thresholds.items():
        value = metrics.get(name)
        if value is None:
            failures.add(f"{prefix}:metric_unavailable:{name}")
        elif value < minimum:
            failures.add(f"{prefix}:threshold_failed:{name}")
    for pre_name, post_name in (
        ("pre_rerank_recall_at_10", "post_rerank_recall_at_10"),
        ("pre_rerank_mrr_at_10", "post_rerank_mrr_at_10"),
    ):
        pre_value = metrics.get(pre_name)
        post_value = metrics.get(post_name)
        if pre_value is None or post_value is None:
            failures.add(f"{prefix}:metric_unavailable:{post_name}")
        elif post_value < pre_value:
            failures.add(f"{prefix}:threshold_failed:{post_name}")
    exhaustive_recall = metrics.get("final_exhaustive_anchor_recall")
    if exhaustive_required and exhaustive_recall is None:
        failures.add(
            f"{prefix}:metric_unavailable:final_exhaustive_anchor_recall"
        )
    elif exhaustive_recall is not None and exhaustive_recall < 1.0:
        failures.add(f"{prefix}:threshold_failed:final_exhaustive_anchor_recall")
    ordinary_p95 = metrics.get("ordinary_p95_ms")
    if ordinary_required and ordinary_p95 is None:
        failures.add(f"{prefix}:metric_unavailable:ordinary_p95_ms")
    elif ordinary_p95 is not None and ordinary_p95 >= 10_000:
        failures.add(f"{prefix}:threshold_failed:ordinary_p95_ms")
    special_p95 = metrics.get("special_route_p95_ms")
    if special_required and special_p95 is None:
        failures.add(f"{prefix}:metric_unavailable:special_route_p95_ms")
    elif special_p95 is not None and special_p95 >= 30_000:
        failures.add(f"{prefix}:threshold_failed:special_route_p95_ms")


def _validate_run_pins(
    run: dict[str, Any],
    expected: dict[str, Any],
    failures: set[str],
    prefix: str,
) -> None:
    pins = _dict(run.get("pins"))
    if run.get("dataset_id") != expected.get("dataset_id"):
        failures.add(f"{prefix}:pin_mismatch:dataset_id")
    for key in _REQUIRED_PINS:
        if key not in expected or _missing(expected.get(key)):
            failures.add(f"pin_unavailable:{key}")
        elif pins.get(key) != expected[key]:
            failures.add(f"{prefix}:pin_mismatch:{key}")
    expected_config = expected.get("rag_config_snapshot")
    if not isinstance(expected_config, Mapping):
        failures.add("pin_unavailable:rag_config_snapshot")
    elif _stable_config(run.get("rag_config_snapshot")) != _stable_config(
        expected_config
    ):
        failures.add(f"{prefix}:pin_mismatch:rag_config_snapshot")
    expected_reranker = expected.get("reranker_model")
    if not expected_reranker:
        failures.add("pin_unavailable:reranker_model")
        return
    results = run.get("cases")
    if not isinstance(results, list):
        return
    models = {
        _dict(result.get("diagnostic")).get("reranker_model")
        for result in results
        if isinstance(result, Mapping)
    }
    if None in models or models != {expected_reranker}:
        failures.add(f"{prefix}:pin_mismatch:reranker_model")


def _validate_expected_pins(
    expected: dict[str, Any], failures: set[str]
) -> None:
    for key in (
        "dataset_id",
        *_REQUIRED_PINS,
        "rag_config_snapshot",
        "reranker_model",
    ):
        if key not in expected or _missing(expected.get(key)):
            failures.add(f"pin_unavailable:{key}")


def _validate_pair(runs: list[dict[str, Any]], failures: set[str]) -> None:
    if runs[0].get("dataset_id") != runs[1].get("dataset_id"):
        failures.add("pair_pin_mismatch:dataset_id")


def _validate_alignment(
    case_id: str,
    gold: dict[str, Any],
    case: dict[str, Any],
    failures: set[str],
) -> None:
    if _normalize_text(str(gold.get("query") or "")) != _normalize_text(
        str(case.get("question") or "")
    ):
        failures.add(f"benchmark_alignment_mismatch:{case_id}:query")
    gold_docs = {_normalize_text(str(item)) for item in gold.get("required_documents") or []}
    case_docs = {
        _normalize_text(str(item)) for item in case.get("expected_source_docs") or []
    }
    if gold_docs != case_docs:
        failures.add(f"benchmark_alignment_mismatch:{case_id}:documents")
    if set(gold.get("required_pages") or []) != set(
        case.get("acceptable_source_pages") or []
    ):
        failures.add(f"benchmark_alignment_mismatch:{case_id}:pages")


def _indexed_rows(
    raw: object, label: str, failures: set[str]
) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, list):
        failures.add(f"{label}:rows_missing")
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping) or not item.get("id") and not item.get("case_id"):
            failures.add(f"{label}:invalid_row")
            continue
        row = dict(item)
        row_id = str(row.get("case_id") or row.get("id"))
        if row_id in indexed:
            failures.add(f"{label}:duplicate:{row_id}")
        indexed[row_id] = row
    return indexed


def _trace_stages(raw: object) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(raw, list):
        return {}
    stages: dict[str, list[dict[str, Any]]] = {}
    for stage in raw:
        if not isinstance(stage, Mapping) or not isinstance(stage.get("candidates"), list):
            continue
        name = str(stage.get("name") or "")
        stages.setdefault(name, []).extend(
            dict(candidate)
            for candidate in stage["candidates"]
            if isinstance(candidate, Mapping)
        )
    return stages


def _max_attempt_size(raw: object, stage_name: str) -> int:
    if not isinstance(raw, list):
        return 0
    return max(
        (
            len(stage.get("candidates") or [])
            for stage in raw
            if isinstance(stage, Mapping) and stage.get("name") == stage_name
        ),
        default=0,
    )


def _latest_trace_candidates(
    raw: object, stage_name: str
) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    latest: list[dict[str, Any]] | None = None
    for stage in raw:
        if not isinstance(stage, Mapping) or stage.get("name") != stage_name:
            continue
        candidates = stage.get("candidates")
        if not isinstance(candidates, list):
            continue
        latest = [dict(item) for item in candidates if isinstance(item, Mapping)]
    return latest


def _location_obligations(
    gold: dict[str, Any], candidates: list[dict[str, Any]]
) -> tuple[int, int]:
    spans = gold.get("required_evidence_spans") or []
    pages = gold.get("required_pages") or []
    documents = gold.get("required_documents") or []
    if spans:
        obligations = [
            (str(span.get("document") or ""), int(span.get("page") or 0))
            for span in spans
            if isinstance(span, Mapping)
        ]
        return (
            sum(
                _candidate_matches(candidates, document=document, page=page)
                for document, page in obligations
            ),
            len(obligations),
        )
    if pages:
        return (
            sum(
                any(
                    _candidate_matches(candidate, documents=documents, page=int(page))
                    for candidate in candidates
                )
                for page in pages
            ),
            len(pages),
        )
    return (
        sum(
            any(
                _normalize_text(str(candidate.get("doc_title") or ""))
                == _normalize_text(str(document))
                for candidate in candidates
            )
            for document in documents
        ),
        len(documents),
    )


def _candidate_matches(
    candidates: list[dict[str, Any]] | dict[str, Any],
    *,
    page: int,
    document: str | None = None,
    documents: Sequence[object] = (),
) -> bool:
    rows = candidates if isinstance(candidates, list) else [candidates]
    allowed = {
        _normalize_text(str(item))
        for item in ([document] if document else documents)
        if item
    }
    return any(
        (not allowed or _normalize_text(str(row.get("doc_title") or "")) in allowed)
        and _covers_page(row, page)
        for row in rows
    )


def _reciprocal_rank_at_10(
    gold: dict[str, Any], candidates: list[dict[str, Any]]
) -> float:
    for rank, candidate in enumerate(candidates[:10], start=1):
        matched, _ = _location_obligations(gold, [candidate])
        if matched:
            return 1 / rank
    return 0.0


def _gold_anchor_total(raw_spans: object) -> int | None:
    if not isinstance(raw_spans, list) or not raw_spans:
        return None
    total = 0
    for span in raw_spans:
        anchors = span.get("must_contain") if isinstance(span, Mapping) else None
        if not isinstance(anchors, list) or not all(
            isinstance(anchor, str) and anchor.strip() for anchor in anchors
        ):
            return None
        total += len(anchors)
    return total or None


def _evidence_anchor_counts(
    diagnostic: Mapping[str, Any],
    *,
    stage_name: str,
    expected_total: int | None,
    accepted_statuses: set[str],
) -> tuple[int, int] | None:
    evidence = _dict(diagnostic.get("evidence_expectations"))
    stage = _dict(_dict(evidence.get("stages")).get(stage_name))
    expectations = stage.get("expectations")
    if (
        expected_total is None
        or stage.get("status") not in accepted_statuses
        or not isinstance(expectations, list)
    ):
        return None

    matched_total = required_total = 0
    for raw in expectations:
        expectation = _dict(raw)
        required = expectation.get("required_anchor_count")
        matched = expectation.get("matched_anchor_count")
        indexes = expectation.get("matched_anchor_indexes")
        recall = expectation.get("anchor_recall")
        if (
            not _non_negative_int(required)
            or not _non_negative_int(matched)
            or matched > required
            or not isinstance(indexes, list)
            or len(indexes) != matched
            or not all(
                _non_negative_int(index) and index < required for index in indexes
            )
            or len(set(indexes)) != len(indexes)
            or isinstance(recall, bool)
            or not isinstance(recall, int | float)
            or not math.isfinite(recall)
            or not 0 <= recall <= 1
            or not math.isclose(recall, matched / required if required else 1.0)
            or not isinstance(expectation.get("anchors_passed"), bool)
        ):
            return None
        required_total += required
        matched_total += matched
    if required_total != expected_total:
        return None
    return matched_total, required_total


def _non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _covers_page(row: Mapping[str, Any], page: int) -> bool:
    direct = row.get("page")
    if isinstance(direct, int) and not isinstance(direct, bool) and direct == page:
        return True
    start = row.get("page_start")
    end = row.get("page_end")
    start = start if isinstance(start, int) and not isinstance(start, bool) else end
    end = end if isinstance(end, int) and not isinstance(end, bool) else start
    return bool(isinstance(start, int) and isinstance(end, int) and start <= page <= end)


def _stable_config(raw: object) -> dict[str, Any]:
    config = _dict(raw)
    config.pop(RUNTIME_PINS_KEY, None)
    config.pop("health", None)  # health timestamps/latencies are observations, not policy
    return config


def _nearest_rank_p95(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _dict(raw: object) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, Mapping) else {}


def _missing(value: object) -> bool:
    return value is None or value == ""


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", normalized).split())
