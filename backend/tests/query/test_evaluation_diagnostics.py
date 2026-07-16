from types import SimpleNamespace

from rag.auth.context import UserContext
from rag.evaluations.adapters.memory import InMemoryEvaluationRepository
from rag.evaluations.execution import EvaluationCaseExecutor
from rag.evaluations.scoring import score_case_result
from rag.query.nodes import QueryNodes
from rag.query.qdrant import SearchHit
from rag.query.configuration.mapping import rag_config_response
from rag.query.configuration.models import RagConfigRecord
from rag.query.retrieval.retrieval_trace import RetrievalTrace, retrieval_trace_stage
from rag.query.routing.routing_models import RoutePlan
from rag.query.schemas import QueryRequest, RAGResponse
from rag.query.service import QueryExecutionResult
from rag.query.state import initial_state
from rag.evaluations.schemas import EvaluationCase, EvaluationEvidenceExpectation


class FakeDocumentRepo:
    def __init__(self, documents: list[object] | None = None) -> None:
        self.documents = documents or [
            document("doc-a", "Doc A.pdf", "hash-a"),
            document("doc-b", "Doc B.pdf", "hash-b"),
        ]

    def list_documents(self, *, state: str) -> list[object]:
        assert state == "active"
        return self.documents


def document(
    document_id: str,
    title: str,
    content_hash: str,
    *,
    is_current: bool = True,
    ingest_status: str = "complete",
) -> object:
    return SimpleNamespace(
        id=document_id,
        title=title,
        content_hash=content_hash,
        is_current=is_current,
        ingest_status=ingest_status,
        deleted_at=None,
    )


class FakeRagService:
    def __init__(self, trace: RetrievalTrace) -> None:
        self.calls = 0
        self.trace = trace
        self.rag_config = SimpleNamespace(reranker_model="BAAI/bge-reranker-base")

    def execute_query(
        self,
        request: QueryRequest,
        _user: object,
        *,
        capture_retrieval_trace: bool = False,
        force_faithfulness_check: bool = False,
    ) -> QueryExecutionResult:
        self.calls += 1
        assert request.query == "What evidence is relevant?"
        assert capture_retrieval_trace is True
        assert force_faithfulness_check is True
        return QueryExecutionResult(response=_response(), retrieval_trace=self.trace)


def hit(point_id: str, score: float, doc_title: str, **payload: object) -> SearchHit:
    return SearchHit(
        point_id=point_id,
        score=score,
        payload={
            "doc_id": doc_title.removesuffix(".pdf").lower().replace(" ", "-"),
            "doc_title": doc_title,
            "chunk_id": point_id,
            "page": 4,
            "page_start": 4,
            "page_end": 5,
            "group_path": "/space",
            "text": f"{doc_title} evidence text",
            **payload,
        },
    )


def test_evaluation_uses_one_production_query_and_records_actual_trace() -> None:
    first_attempt = [hit("old", 0.2, "Old.pdf", page="3")]
    retrieved = [hit("a", 0.4, "Doc A.pdf"), hit("b", 0.6, "Doc B.pdf")]
    reranked = [
        hit(
            "b",
            0.6,
            "Doc B.pdf",
            _rerank_score=0.91,
            _rerank_adjusted_score=0.56,
            _rerank_status="scored",
            _low_value_penalty=0.35,
            _low_value_reasons=["toc_or_index"],
        ),
        hit("a", 0.4, "Doc A.pdf", _rerank_score=0.22, _rerank_status="scored"),
    ]
    trace = RetrievalTrace(
        stages=(
            retrieval_trace_stage("retrieved", first_attempt, attempt=0),
            retrieval_trace_stage("rerank_input", first_attempt, attempt=0),
            retrieval_trace_stage("reranked", first_attempt, attempt=0),
            retrieval_trace_stage("post_policy", first_attempt, attempt=0),
            retrieval_trace_stage("retrieved", retrieved, attempt=1),
            retrieval_trace_stage("rerank_input", retrieved, attempt=1),
            retrieval_trace_stage("reranked", reranked, attempt=1),
            retrieval_trace_stage("post_policy", reranked, attempt=1),
            retrieval_trace_stage("final_evidence", reranked[:1], attempt=1),
        )
    )
    service = FakeRagService(trace)
    received_configs: list[RagConfigRecord] = []
    repo = InMemoryEvaluationRepository()
    case = EvaluationCase(
        id="case",
        question="What evidence is relevant?",
        must_include=["grounded"],
        expected_source_docs=["Doc A.pdf", "Doc B.pdf"],
        acceptable_source_pages=[4],
        min_faithfulness_score=0.5,
    )
    dataset = repo.create_dataset(
        name="Trace dataset",
        description=None,
        source_format="jsonl",
        cases=[case],
        metadata={},
        created_by="user",
    )
    run = repo.create_run(
        dataset_id=dataset.id,
        user_id="user",
        permission_version=1,
        user_email="user@example.com",
        account_type="member",
        group_paths=["/space"],
        clearance_level="NATO_UNCLASSIFIED",
        group_path="/space",
        document_ids=[],
        selected_case_ids=[case.id],
        rag_config_snapshot=_snapshot(),
        case_count=1,
        retention_days=1,
    )
    executor = EvaluationCaseExecutor(
        document_repo_factory=FakeDocumentRepo,
        rag_service_factory=lambda config, _settings: received_configs.append(config)
        or service,
        config=SimpleNamespace(evaluation_answer_llm_verifier_enabled=False),  # type: ignore[arg-type]
    )

    payload = executor.execute_case(run, case)

    assert service.calls == 1
    assert len(received_configs) == 1
    assert received_configs[0].chat_model == "qwen3:8b"
    assert received_configs[0].base_url == "http://ollama:11434"
    assert repo.list_case_results(run.id) == []
    diagnostic = payload.diagnostic_json
    assert diagnostic["retrieved_source_docs"] == ["Doc A.pdf", "Doc B.pdf"]
    assert diagnostic["reranked_source_docs"] == ["Doc B.pdf", "Doc A.pdf"]
    assert diagnostic["rerank_input_candidates"][0]["chunk_id"] == "a"
    assert diagnostic["reranked_candidates"][0]["rerank_score"] == 0.91
    assert diagnostic["reranked_candidates"][0]["low_value_penalty"] == 0.35
    assert diagnostic["reranked_candidates"][0]["low_value_reasons"] == ["toc_or_index"]
    assert diagnostic["hits"] == diagnostic["retrieval_candidates"]
    assert diagnostic["final_evidence_candidates"][0]["chunk_id"] == "b"
    retrieved_stages = [
        stage for stage in diagnostic["retrieval_trace"] if stage["name"] == "retrieved"
    ]
    assert [stage["attempt"] for stage in retrieved_stages] == [0, 1]
    assert retrieved_stages[0]["candidates"][0]["chunk_id"] == "old"
    assert retrieved_stages[0]["candidates"][0]["page"] == 3
    assert [row["chunk_id"] for row in retrieved_stages[1]["candidates"]] == [
        "a",
        "b",
    ]
    assert "text" not in diagnostic["retrieval_candidates"][0]


def test_document_bound_pages_never_match_another_document() -> None:
    case = _evidence_case(
        EvaluationEvidenceExpectation(document_id="doc-a", pages=[4])
    )
    other_document = [hit("b", 0.9, "Doc B.pdf", page=4)]
    diagnostic = _diagnostic(case, _single_wave_trace(other_document))

    retrieved = diagnostic["evidence_expectations"]["stages"]["retrieved"]

    assert retrieved["passed"] is False
    assert retrieved["expectations"][0]["matched_pages"] == []
    scored = score_case_result(case, response=_response(), diagnostic=diagnostic)
    assert scored["primary_failure_stage"] == "retrieval"


def test_any_and_all_page_matching_are_applied_per_document() -> None:
    case = EvaluationCase(
        id="case",
        question="What evidence is relevant?",
        evidence_expectations=[
            EvaluationEvidenceExpectation(
                document_id="doc-a", pages=[4, 9], page_match="any"
            ),
            EvaluationEvidenceExpectation(
                content_hash="hash-b", pages=[4, 5], page_match="all"
            ),
        ],
    )
    candidates = [
        hit("a", 0.8, "Doc A.pdf", page=4, page_start=4, page_end=4),
        hit("b", 0.7, "Doc B.pdf", page=None, page_start=4, page_end=5),
    ]
    diagnostic = _diagnostic(case, _single_wave_trace(candidates))

    stages = diagnostic["evidence_expectations"]["stages"]

    assert all(stage["passed"] is True for stage in stages.values())
    assert stages["retrieved"]["expectations"][0]["matched_pages"] == [4]
    assert stages["retrieved"]["expectations"][1]["matched_pages"] == [4, 5]
    scored = score_case_result(case, response=_response(), diagnostic=diagnostic)
    assert scored["passed"] is True


def test_inclusive_page_ranges_fail_all_when_one_page_is_outside() -> None:
    case = _evidence_case(
        EvaluationEvidenceExpectation(
            document_id="doc-a", pages=[4, 5, 6], page_match="all"
        )
    )
    ranged = [
        hit("a", 0.8, "Doc A.pdf", page=None, page_start=4, page_end=5)
    ]
    diagnostic = _diagnostic(case, _single_wave_trace(ranged))

    retrieved = diagnostic["evidence_expectations"]["stages"]["retrieved"]

    assert retrieved["expectations"][0]["matched_pages"] == [4, 5]
    assert retrieved["passed"] is False


def test_stage_checks_union_candidates_across_all_retry_waves() -> None:
    case = _evidence_case(
        EvaluationEvidenceExpectation(
            document_id="doc-a",
            pages=[4, 5],
            page_match="all",
            anchors=["Safety Goggles", "Heating Bag"],
        )
    )
    stages = []
    for stage_name in ("retrieved", "rerank_input", "reranked", "final_evidence"):
        stages.extend(
            [
                retrieval_trace_stage(
                    stage_name,
                    [
                        hit(
                            f"{stage_name}-4",
                            0.8,
                            "Doc A.pdf",
                            page=4,
                            text="Safety Goggles",
                        )
                    ],
                    attempt=0,
                ),
                retrieval_trace_stage(
                    stage_name,
                    [
                        hit(
                            f"{stage_name}-5",
                            0.7,
                            "Doc A.pdf",
                            page=5,
                            text="Heating Bag",
                        )
                    ],
                    attempt=1,
                ),
            ]
        )
    diagnostic = _diagnostic(case, RetrievalTrace(stages=tuple(stages)))

    evidence_stages = diagnostic["evidence_expectations"]["stages"]

    assert all(stage["passed"] is True for stage in evidence_stages.values())
    assert all(stage["attempts"] == [0, 1] for stage in evidence_stages.values())
    assert all(
        stage["expectations"][0]["matched_pages"] == [4, 5]
        for stage in evidence_stages.values()
    )
    assert all(
        stage["expectations"][0]["matched_anchor_indexes"] == [0, 1]
        for stage in evidence_stages.values()
    )


def test_anchor_diagnostics_report_candidate_fate_without_persisting_text() -> None:
    secret = "AUTHORIZED-ONLY-SENTINEL"
    case = _evidence_case(
        EvaluationEvidenceExpectation(
            document_id="doc-a",
            pages=[4],
            page_match="all",
            anchors=["Safety Goggles", "Heating Bag"],
        )
    )
    complete = [
        hit(
            "complete",
            0.9,
            "Doc A.pdf",
            page=4,
            text=f"{secret} Safety Goggles and Heating Bag",
        )
    ]
    partial = [
        hit(
            "partial",
            0.8,
            "Doc A.pdf",
            page=4,
            text=f"{secret} Safety Goggles",
        )
    ]
    trace = RetrievalTrace(
        stages=(
            retrieval_trace_stage("retrieved", complete, attempt=0),
            retrieval_trace_stage("rerank_input", partial, attempt=0),
            retrieval_trace_stage("reranked", partial, attempt=0),
            retrieval_trace_stage("final_evidence", complete, attempt=0),
        )
    )

    diagnostic = _diagnostic(case, trace)
    stages = diagnostic["evidence_expectations"]["stages"]

    assert stages["retrieved"]["expectations"][0] == {
        "index": 0,
        "resolved_document_id": "doc-a",
        "candidate_count": 1,
        "matched_pages": [4],
        "required_anchor_count": 2,
        "matched_anchor_count": 2,
        "matched_anchor_indexes": [0, 1],
        "anchor_recall": 1.0,
        "anchors_passed": True,
        "passed": True,
    }
    assert stages["rerank_input"]["expectations"][0][
        "matched_anchor_indexes"
    ] == [0]
    assert stages["rerank_input"]["expectations"][0]["anchor_recall"] == 0.5
    assert stages["rerank_input"]["passed"] is False
    assert stages["final_evidence"]["passed"] is True
    assert secret not in str(diagnostic)
    for stage in diagnostic["retrieval_trace"]:
        for candidate in stage["candidates"]:
            assert {"evidence_text", "text", "parent_text", "table_json", "excerpt"}.isdisjoint(
                candidate
            )


def test_anchor_diagnostics_match_unicode_document_text() -> None:
    case = _evidence_case(
        EvaluationEvidenceExpectation(
            document_id="doc-a",
            pages=[4],
            anchors=["حفاظتی ماسک"],
        )
    )
    candidates = [
        hit("urdu", 0.9, "Doc A.pdf", page=4, text="ضروری حفاظتی ماسک")
    ]

    diagnostic = _diagnostic(case, _single_wave_trace(candidates))

    assert all(
        stage["expectations"][0]["matched_anchor_indexes"] == [0]
        for stage in diagnostic["evidence_expectations"]["stages"].values()
    )


def test_skipped_reranker_is_scored_as_pass_through_without_fake_model_input() -> None:
    case = _evidence_case(
        EvaluationEvidenceExpectation(document_id="doc-a", pages=[4])
    )
    candidates = [hit("a", 0.8, "Doc A.pdf", page=4)]
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=case.question),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/space",),
        ),
        started=0.0,
        capture_retrieval_trace=True,
    )
    ctx["route_plan"] = RoutePlan(
        original_query=case.question,
        resolved_query=case.question,
        intent="summarization",
        public_intent="summarization",
        use_reranker=False,
        top_k=4,
    )
    nodes = object.__new__(QueryNodes)
    nodes.retrieval_service = SimpleNamespace(retrieve=lambda _ctx: candidates)

    nodes.abac_retriever(ctx)
    nodes.reranker(ctx)
    nodes.evidence_builder(ctx)

    trace = RetrievalTrace(stages=tuple(ctx["retrieval_trace"]))
    diagnostic = _diagnostic(case, trace)
    scored = score_case_result(case, response=_response(), diagnostic=diagnostic)

    rerank_input = diagnostic["evidence_expectations"]["stages"]["rerank_input"]
    assert rerank_input["status"] == "skipped"
    assert rerank_input["passed"] is True
    assert diagnostic["rerank_input_candidates"] == []
    assert scored["passed"] is True
    assert scored["failure_stages"] == []
    assert next(
        stage
        for stage in diagnostic["retrieval_trace"]
        if stage["name"] == "rerank_input"
    )["status"] == "skipped"


def test_missing_trace_stages_are_not_reported_completed() -> None:
    case = _evidence_case(
        EvaluationEvidenceExpectation(document_id="doc-a", pages=[4])
    )

    diagnostic = _diagnostic(case, RetrievalTrace())

    assert {
        stage["status"]
        for stage in diagnostic["evidence_expectations"]["stages"].values()
    } == {"missing"}


def test_unresolved_document_id_or_content_hash_fails_ingestion_indexing() -> None:
    for expectation in (
        EvaluationEvidenceExpectation(document_id="missing-document"),
        EvaluationEvidenceExpectation(content_hash="missing-hash"),
    ):
        case = _evidence_case(expectation)
        diagnostic = _diagnostic(case, _single_wave_trace([]))

        assert diagnostic["evidence_expectations"]["resolution_passed"] is False
        assert diagnostic["evidence_expectations"]["expectations"][0][
            "resolution_status"
        ] == "unresolved"
        scored = score_case_result(case, response=_response(), diagnostic=diagnostic)
        assert scored["primary_failure_stage"] == "ingestion/indexing"


def test_samsung_style_pre_rerank_loss_is_classified_as_retrieval() -> None:
    case = _evidence_case(
        EvaluationEvidenceExpectation(document_id="samsung", pages=[4])
    )
    samsung = [
        hit(
            "equipment",
            0.8,
            "Samsung Repair.pdf",
            doc_id="samsung",
            page=4,
        )
    ]
    unrelated = [hit("safety", 0.9, "Doc B.pdf", page=4)]
    trace = RetrievalTrace(
        stages=(
            retrieval_trace_stage("retrieved", samsung, attempt=0),
            retrieval_trace_stage("rerank_input", unrelated, attempt=0),
            retrieval_trace_stage("reranked", unrelated, attempt=0),
            retrieval_trace_stage("final_evidence", unrelated, attempt=0),
        )
    )
    diagnostic = _diagnostic(
        case,
        trace,
        documents=[document("samsung", "Samsung Repair.pdf", "samsung-hash")],
    )

    scored = score_case_result(case, response=_response(), diagnostic=diagnostic)

    assert scored["checks"]["retrieval"]["evidence_expectations"]["retrieved"][
        "passed"
    ] is True
    assert scored["checks"]["retrieval"]["evidence_expectations"]["rerank_input"][
        "passed"
    ] is False
    assert scored["primary_failure_stage"] == "retrieval"
    assert "reranking/source_selection" not in scored["failure_stages"]


def test_loss_after_rerank_input_is_classified_as_source_selection() -> None:
    case = _evidence_case(
        EvaluationEvidenceExpectation(document_id="samsung", pages=[4])
    )
    samsung = [
        hit(
            "equipment",
            0.8,
            "Samsung Repair.pdf",
            doc_id="samsung",
            page=4,
        )
    ]
    unrelated = [hit("safety", 0.9, "Doc B.pdf", page=4)]
    trace = RetrievalTrace(
        stages=(
            retrieval_trace_stage("retrieved", samsung, attempt=0),
            retrieval_trace_stage("rerank_input", samsung, attempt=0),
            retrieval_trace_stage("reranked", unrelated, attempt=0),
            retrieval_trace_stage("final_evidence", unrelated, attempt=0),
        )
    )
    diagnostic = _diagnostic(
        case,
        trace,
        documents=[document("samsung", "Samsung Repair.pdf", "samsung-hash")],
    )

    scored = score_case_result(case, response=_response(), diagnostic=diagnostic)

    assert scored["checks"]["retrieval"]["passed"] is True
    assert scored["checks"]["reranking_source_selection"]["passed"] is False
    assert scored["checks"]["reranking_source_selection"]["message"] == (
        "Expected document-bound evidence survived retrieval but was lost before "
        "final evidence selection."
    )
    assert scored["primary_failure_stage"] == "reranking/source_selection"


def test_parent_promoted_final_evidence_is_not_false_reranker_loss() -> None:
    case = _evidence_case(
        EvaluationEvidenceExpectation(
            document_id="samsung",
            pages=[4],
            anchors=["Safety Goggles", "Heating Bag"],
        )
    )
    complete = [
        hit(
            "equipment-parent",
            0.9,
            "Samsung Repair.pdf",
            doc_id="samsung",
            page=4,
            text="Safety Goggles and Heating Bag",
        )
    ]
    child_only = [
        hit(
            "equipment-child",
            0.8,
            "Samsung Repair.pdf",
            doc_id="samsung",
            page=4,
            text="Safety Goggles",
        )
    ]
    trace = RetrievalTrace(
        stages=(
            retrieval_trace_stage("retrieved", complete, attempt=0),
            retrieval_trace_stage("rerank_input", complete, attempt=0),
            retrieval_trace_stage("reranked", child_only, attempt=0),
            retrieval_trace_stage("final_evidence", complete, attempt=0),
        )
    )
    diagnostic = _diagnostic(
        case,
        trace,
        documents=[document("samsung", "Samsung Repair.pdf", "samsung-hash")],
    )

    scored = score_case_result(case, response=_response(), diagnostic=diagnostic)

    stages = diagnostic["evidence_expectations"]["stages"]
    assert stages["reranked"]["passed"] is False
    assert stages["final_evidence"]["passed"] is True
    assert scored["checks"]["reranking_source_selection"]["passed"] is True
    assert "reranking/source_selection" not in scored["failure_stages"]


def test_legacy_pages_fail_closed_for_wrong_document_and_ambiguous_binding() -> None:
    wrong_document_case = EvaluationCase(
        id="legacy-wrong-document",
        question="Where is the evidence?",
        expected_source_docs=["Doc A.pdf"],
        acceptable_source_pages=[4],
    )
    wrong_document_diagnostic = _diagnostic(
        wrong_document_case,
        _single_wave_trace([hit("b", 0.9, "Doc B.pdf", page=4)]),
    )
    ambiguous_case = EvaluationCase(
        id="legacy-ambiguous",
        question="Where is the evidence?",
        expected_source_docs=["Doc A.pdf", "Doc B.pdf"],
        acceptable_source_pages=[4],
    )
    ambiguous_diagnostic = _diagnostic(
        ambiguous_case,
        _single_wave_trace([hit("a", 0.9, "Doc A.pdf", page=4)]),
    )

    assert wrong_document_diagnostic["legacy_page_expectation"]["passed"] is False
    assert wrong_document_diagnostic["legacy_page_expectation"][
        "resolved_document_id"
    ] == "doc-a"
    assert ambiguous_diagnostic["legacy_page_expectation"]["passed"] is False
    assert ambiguous_diagnostic["legacy_page_expectation"]["ambiguous"] is True
    assert ambiguous_diagnostic["legacy_page_expectation"][
        "resolution_status"
    ] == "ambiguous"


def _evidence_case(expectation: EvaluationEvidenceExpectation) -> EvaluationCase:
    return EvaluationCase(
        id="case",
        question="What evidence is relevant?",
        evidence_expectations=[expectation],
    )


def _single_wave_trace(candidates: list[SearchHit]) -> RetrievalTrace:
    return RetrievalTrace(
        stages=tuple(
            retrieval_trace_stage(stage_name, candidates, attempt=0)
            for stage_name in (
                "retrieved",
                "rerank_input",
                "reranked",
                "final_evidence",
            )
        )
    )


def _diagnostic(
    case: EvaluationCase,
    trace: RetrievalTrace,
    *,
    documents: list[object] | None = None,
) -> dict[str, object]:
    executor = EvaluationCaseExecutor(
        document_repo_factory=FakeDocumentRepo,  # type: ignore[arg-type]
        rag_service_factory=lambda _config, _settings: None,  # type: ignore[arg-type,return-value]
        config=SimpleNamespace(evaluation_answer_llm_verifier_enabled=False),  # type: ignore[arg-type]
    )
    return executor._diagnostic(
        case,
        trace=trace,
        document_repo=FakeDocumentRepo(documents),  # type: ignore[arg-type]
        reranker_model=None,
    )


def _response() -> RAGResponse:
    return RAGResponse(
        trace_id="trace-1",
        answer="The grounded answer.",
        sources=[],
        artifacts=[],
        artifact_job=None,
        conflict_flag=False,
        conflict_detail=None,
        faithfulness_score=1.0,
        faithfulness_status="checked",
        unfounded_claims=[],
        intent="factual_simple",
        session_id="session-1",
        latency_ms=1,
        node_timings=[],
        degraded=False,
        degraded_reason=None,
    )


def _snapshot() -> dict[str, object]:
    return rag_config_response(
        RagConfigRecord(
            base_url="http://ollama:11434",
            chat_model="qwen3:8b",
            embed_model="nomic-embed-text:latest",
            faithfulness_model="qwen3:8b",
            chat_timeout_seconds=180,
            embed_timeout_seconds=45,
        )
    ).model_dump(mode="json")
