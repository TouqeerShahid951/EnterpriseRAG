from datetime import UTC, datetime

from rag.auth.context import UserContext
from rag.query.analytics.adapters.memory import InMemoryAnalyticsRepository
from rag.query.analytics.models import AnalyticsFilters
from rag.query.analytics.service import AnalyticsRecorder
from rag.query.qdrant import SearchHit
from rag.query.schemas import QueryRequest, RAGResponse
from rag.query.retrieval.retrieval_trace import retrieval_trace_stage
from rag.query.state import initial_state
from rag.shared.contracts.evidence import SourceAnchor


def test_recorder_persists_bounded_text_free_generation_aware_lineage() -> None:
    repository = InMemoryAnalyticsRepository()
    recorder = AnalyticsRecorder(
        repository,
        retrieval_lineage_max_candidates=1,
    )
    request = QueryRequest(query="What is the policy?", group_path="/ops")
    user = UserContext(user_id="user", email="user@example.com", group_paths=("/ops",))
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=request,
        user=user,
        started=0.0,
        capture_retrieval_trace=True,
    )
    ctx["retrieval_trace"].append(
        retrieval_trace_stage(
            "retrieved",
            [
                SearchHit(
                    point_id="point-a",
                    score=0.9,
                    payload={
                        "doc_id": "doc",
                        "chunk_id": "chunk-a",
                        "index_generation_id": "generation-7",
                        "text": "secret evidence",
                        "_rerank_error": "secret exception details",
                    },
                ),
                SearchHit(
                    point_id="point-b",
                    score=0.8,
                    payload={"doc_id": "doc", "chunk_id": "chunk-b", "text": "other"},
                ),
            ],
            attempt=0,
        )
    )
    ctx["synthesis_source_keys"] = [
        {
            "doc_id": "doc",
            "chunk_id": "chunk-a",
            "index_generation_id": "generation-7",
        }
    ]
    ctx["response_source_keys"] = list(ctx["synthesis_source_keys"])
    ctx["citation_source_keys"] = list(ctx["synthesis_source_keys"])
    ctx["synthesis_context_count"] = 1
    ctx["synthesis_estimated_prompt_tokens"] = 42

    recorder.start(
        execution_id="execution",
        trace_id="trace",
        session_id="session",
        user=user,
        request=request,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        origin="chat",
        work_kind="answer",
        cohort={
            "model_cohort": "models-test",
            "configuration_digest": "config-test",
            "application_image_digest": "sha256:image-test",
            "snapshot": {"schema_version": 1, "models": {"chat": "test-model"}},
        },
    )
    recorder.finish_response(
        execution_id="execution",
        response=RAGResponse(
            trace_id="trace",
            answer="Supported answer [doc:chunk-a]",
            conflict_flag=False,
            faithfulness_score=1.0,
            intent="factual_simple",
            session_id="session",
            latency_ms=10,
            degraded=False,
            sources=[
                SourceAnchor(
                    doc_id="doc",
                    doc_title="Manual",
                    chunk_id="chunk-a",
                    excerpt="secret evidence",
                    group_path="/ops",
                )
            ],
        ),
        ctx=ctx,
    )

    record = repository.get_execution("execution")
    assert record is not None
    assert record.retrieval_lineage_status == "truncated"
    assert record.retrieval_lineage is not None
    lineage = record.retrieval_lineage
    assert lineage["candidate_count"] == 2
    assert lineage["serialized_candidate_count"] == 1
    assert lineage["truncated"] is True
    candidate = lineage["stages"][0]["candidates"][0]
    assert candidate["index_generation_id"] == "generation-7"
    assert candidate["candidate_key"] == "generation-7:doc:chunk-a:point-a"
    assert "text" not in candidate
    assert "rerank_error" not in candidate
    assert lineage["generation"]["source_keys"][0]["index_generation_id"] == "generation-7"
    assert record.model_cohort == "models-test"
    assert record.configuration_digest == "config-test"
    assert record.cohort_snapshot == {"schema_version": 1, "models": {"chat": "test-model"}}

    diagnostics = repository.diagnose_executions(
        filters=AnalyticsFilters(
            created_from=datetime(2025, 12, 31, tzinfo=UTC),
            created_to=datetime(2026, 1, 2, tzinfo=UTC),
        )
    )
    assert diagnostics.stages[0].candidate_count == 2
    assert diagnostics.stages[0].retrieval_score.count == 1


def test_citation_lineage_keeps_only_final_counts_and_text_free_attempts():
    import json
    from rag.query.analytics.service import _quality_lineage
    from rag.query.answering.citation_claims import answer_claims
    from rag.query.evidence_validation import text_hash
    from rag.shared.contracts.evidence import CitationVerification, EvidenceQuote
    answer = "Private claim. [doc:1]"
    claim = answer_claims(answer)[0].model_copy(update={"verdict": "supported", "quotes": [EvidenceQuote(
        source_label="[doc:1]", text="Private passage.", source_start=0, source_end=16)]})
    response = RAGResponse(trace_id="trace", session_id="session", answer=answer, intent="factual_simple",
        latency_ms=0, degraded=False, conflict_flag=False, faithfulness_score=1,
        citation_verification=CitationVerification(answer_sha256=text_hash(answer), status="verified", repair_count=1, claims=[claim]))
    ctx = {"citation_diagnostics": {"repair_count": 1, "verification_calls": 2, "attempts": [{"claim_count": 2, "unsupported": 1}]}}
    quality = _quality_lineage(ctx, response)
    assert quality["citation_verification"]["applicable_claims"] == 1
    assert quality["citation_verification"]["supported_claims"] == 1
    assert quality["citation_verification"]["valid_quotes"] == 1
    assert quality["claim_ledger"]["supported_claims"] == 1
    assert quality["claim_ledger"]["cited_claims"] == 1
    assert quality["answer_replaced"] is True
    assert "Private" not in json.dumps(quality)


def test_capture_serialization_failure_never_replaces_query_completion(monkeypatch, caplog):
    import rag.query.analytics.service as analytics_service

    def broken_lineage(*args, **kwargs):
        raise ValueError("secret malformed telemetry")

    monkeypatch.setattr(analytics_service, "_retrieval_lineage", broken_lineage)
    recorder = AnalyticsRecorder(InMemoryAnalyticsRepository())
    response = RAGResponse(trace_id="trace", session_id="session", answer="Answer", intent="factual_simple",
                           latency_ms=1, degraded=False, conflict_flag=False, faithfulness_score=0)
    recorder.finish_response(execution_id="execution", response=response)
    recorder.fail(execution_id="execution", outcome="cancelled")
    assert "analytics write failed" in caplog.text
    assert "ValueError" in caplog.text
    assert "secret" not in caplog.text
