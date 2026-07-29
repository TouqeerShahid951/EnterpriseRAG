from copy import deepcopy

from rag.evaluations.release_gate import _nearest_rank_p95, evaluate_release_gate


MODEL = "local/reranker"


def test_release_gate_accepts_two_complete_pinned_runs() -> None:
    runs, gold, cases, pins = _fixture()

    report = evaluate_release_gate(
        runs, ranking_gold=gold, dataset_cases=cases, expected_pins=pins
    )

    assert report["passed"] is True
    assert report["failures"] == []


def test_release_gate_fails_closed_for_missing_trace_metric_and_pin_drift() -> None:
    runs, gold, cases, pins = _fixture()
    runs[0]["cases"][0]["diagnostic"]["retrieval_trace"] = [
        stage
        for stage in runs[0]["cases"][0]["diagnostic"]["retrieval_trace"]
        if stage["name"] != "rerank_input"
    ]
    runs[1]["pins"]["image_digest"] = "different"

    report = evaluate_release_gate(
        runs, ranking_gold=gold, dataset_cases=cases, expected_pins=pins
    )

    assert report["passed"] is False
    assert any("metric_unavailable:rerank_input" in item for item in report["failures"])
    assert any("pin_mismatch:image_digest" in item for item in report["failures"])


def test_release_gate_rejects_reranking_that_loses_top_ten_recall() -> None:
    runs, gold, cases, pins = _fixture()
    decoys = [
        {
            "doc_title": f"Decoy-{index}.pdf",
            "page": 1,
            "rerank_status": "scored",
        }
        for index in range(10)
    ]
    relevant = {
        "doc_title": "One.pdf",
        "page": 1,
        "rerank_status": "scored",
    }
    for run in runs:
        trace = run["cases"][0]["diagnostic"]["retrieval_trace"]
        for stage in trace:
            if stage["name"] == "rerank_input":
                stage["candidates"] = [relevant, *decoys]
            elif stage["name"] == "reranked":
                stage["candidates"] = [*decoys, relevant]

    report = evaluate_release_gate(
        runs, ranking_gold=gold, dataset_cases=cases, expected_pins=pins
    )

    assert report["passed"] is False
    metrics = report["run_reports"][0]["metrics"]
    assert metrics["post_rerank_recall_at_10"] < metrics["pre_rerank_recall_at_10"]
    assert metrics["post_rerank_mrr_at_10"] < metrics["pre_rerank_mrr_at_10"]
    assert any(
        "threshold_failed:post_rerank_recall_at_10" in failure
        for failure in report["failures"]
    )


def test_opaque_anchor_diagnostics_prove_exact_recall() -> None:
    runs, gold, cases, pins = _fixture()
    cases[0]["question_type"] = "exhaustive_list"
    gold["cases"][0]["required_evidence_spans"] = [
        {"document": "One.pdf", "page": 1, "must_contain": ["alpha"]}
    ]
    for run in runs:
        _set_anchor_diagnostic(run["cases"][0], "rerank_input", required=1, matched=1)
        _set_anchor_diagnostic(run["cases"][0], "final_evidence", required=1, matched=1)

    report = evaluate_release_gate(
        runs, ranking_gold=gold, dataset_cases=cases, expected_pins=pins
    )

    assert report["passed"] is True
    assert report["run_reports"][0]["metrics"]["pre_rerank_exact_span_recall"] == 1
    assert report["run_reports"][0]["metrics"]["final_exhaustive_anchor_recall"] == 1


def test_missing_pre_rerank_anchor_fails_release_threshold() -> None:
    runs, gold, cases, pins = _fixture()
    gold["cases"][0]["required_evidence_spans"] = [
        {
            "document": "One.pdf",
            "page": 1,
            "must_contain": ["alpha", "beta"],
        }
    ]
    for run in runs:
        _set_anchor_diagnostic(run["cases"][0], "rerank_input", required=2, matched=1)

    report = evaluate_release_gate(
        runs, ranking_gold=gold, dataset_cases=cases, expected_pins=pins
    )

    assert report["passed"] is False
    assert report["run_reports"][0]["metrics"]["pre_rerank_exact_span_recall"] == 0.5
    assert any(
        "threshold_failed:pre_rerank_exact_span_recall" in item
        for item in report["failures"]
    )


def test_absent_or_malformed_anchor_diagnostics_fail_unavailable() -> None:
    for malformed in (False, True):
        runs, gold, cases, pins = _fixture()
        gold["cases"][0]["required_evidence_spans"] = [
            {"document": "One.pdf", "page": 1, "must_contain": ["alpha"]}
        ]
        if malformed:
            for run in runs:
                _set_anchor_diagnostic(
                    run["cases"][0], "rerank_input", required=2, matched=1
                )
        else:
            for run in runs:
                run["cases"][0]["sources"] = [
                    {"doc_title": "One.pdf", "page": 1, "excerpt": "alpha"}
                ]

        report = evaluate_release_gate(
            runs, ranking_gold=gold, dataset_cases=cases, expected_pins=pins
        )

        assert report["passed"] is False
        assert report["run_reports"][0]["metrics"][
            "pre_rerank_exact_span_recall"
        ] is None
        assert any(
            "metric_unavailable:pre_rerank_exact_span_recall" in item
            for item in report["failures"]
        )


def test_nearest_rank_p95_uses_strict_release_boundaries() -> None:
    assert _nearest_rank_p95([1] * 18 + [9_999, 60_000]) == 9_999
    assert _nearest_rank_p95([1] * 18 + [10_000, 60_000]) == 10_000
    assert _nearest_rank_p95([]) is None


def _fixture() -> tuple[
    list[dict[str, object]],
    dict[str, object],
    list[dict[str, object]],
    dict[str, object],
]:
    cases: list[dict[str, object]] = [
        {
            "id": "ordinary",
            "question": "What is alpha?",
            "question_type": "fact",
            "expected_answer": "alpha",
            "expected_source_docs": ["One.pdf"],
            "acceptable_source_pages": [1],
            "must_cite_source": True,
            "min_faithfulness_score": 0.8,
        },
        {
            "id": "joined",
            "question": "Join alpha and beta.",
            "question_type": "cross_document",
            "expected_answer": "alpha beta",
            "expected_source_docs": ["One.pdf", "Two.pdf"],
            "acceptable_source_pages": [],
            "must_cite_source": True,
            "min_faithfulness_score": 0.8,
        },
    ]
    gold_cases = [
        _gold("ordinary", "What is alpha?", ["One.pdf"], [1]),
        _gold("joined", "Join alpha and beta.", ["One.pdf", "Two.pdf"], []),
    ]
    gold: dict[str, object] = {"case_count": 2, "cases": gold_cases}
    file_pins = {
        "dataset_semantic_hash": "dataset",
        "ranking_gold_hash": "gold",
        "corpus_manifest_hash": "corpus",
        "rag_config_hash": "sha256:config",
        "query_settings_hash": "sha256:query-settings",
        "model_identifiers_hash": "sha256:models",
        "prompt_policy_version": "prompts-v1",
        "image_digest": "sha256:image",
        "active_generation": "generation-1",
        "active_document_content_hash": "sha256:documents",
        "host_profile": "test-host-v1",
    }
    pins: dict[str, object] = {
        "dataset_id": "dataset-id",
        **file_pins,
        "rag_config_snapshot": {"reranker_model": MODEL, "health": {"checked_at": "one"}},
        "reranker_model": MODEL,
    }
    base_run: dict[str, object] = {
        "dataset_id": "dataset-id",
        "status": "complete",
        "case_count": 2,
        "completed_count": 2,
        "pins": file_pins,
        "rag_config_snapshot": {
            "reranker_model": MODEL,
            "health": {"checked_at": "two"},
        },
        "cases": [
            _result("ordinary", [("One.pdf", 1)], latency_ms=100),
            _result("joined", [("One.pdf", 1), ("Two.pdf", 1)], latency_ms=200),
        ],
    }
    first = deepcopy(base_run)
    first["id"] = "run-1"
    second = deepcopy(base_run)
    second["id"] = "run-2"
    return [first, second], gold, cases, pins


def _gold(
    case_id: str, query: str, documents: list[str], pages: list[int]
) -> dict[str, object]:
    return {
        "id": case_id,
        "query": query,
        "required_documents": documents,
        "required_pages": pages,
        "required_evidence_spans": [],
        "content_anchors": ["alpha"],
        "reranker_gold": {
            "max_candidates": 40,
            "required_status": "scored",
            "forbidden_statuses": ["fallback", "error"],
        },
    }


def _result(
    case_id: str, sources: list[tuple[str, int]], *, latency_ms: int
) -> dict[str, object]:
    candidates = [
        {
            "doc_title": title,
            "page": page,
            "rerank_status": "scored",
        }
        for title, page in sources
    ]
    return {
        "id": f"result-{case_id}",
        "case_id": case_id,
        "status": "ok",
        "latency_ms": latency_ms,
        "checks": {
            "answer_content": {
                "passed": True,
                "llm_verifier": {"status": "checked"},
            },
            "citation": {"passed": True, "unresolved_citations": []},
            "faithfulness": {"status": "passed"},
        },
        "sources": [],
        "diagnostic": {
            "reranker_model": MODEL,
            "retrieval_trace": [
                {
                    "name": name,
                    "attempt": 0,
                    "status": "completed",
                    "candidates": deepcopy(candidates),
                }
                for name in (
                    "retrieved",
                    "rerank_input",
                    "reranked",
                    "post_policy",
                    "final_evidence",
                )
            ],
        },
    }


def _set_anchor_diagnostic(
    result: dict[str, object],
    stage_name: str,
    *,
    required: int,
    matched: int,
) -> None:
    diagnostic = result["diagnostic"]
    assert isinstance(diagnostic, dict)
    evidence = diagnostic.setdefault("evidence_expectations", {"stages": {}})
    assert isinstance(evidence, dict)
    stages = evidence["stages"]
    assert isinstance(stages, dict)
    stages[stage_name] = {
        "status": "completed",
        "expectations": [
            {
                "required_anchor_count": required,
                "matched_anchor_count": matched,
                "matched_anchor_indexes": list(range(matched)),
                "anchor_recall": matched / required,
                "anchors_passed": matched == required,
            }
        ],
    }
