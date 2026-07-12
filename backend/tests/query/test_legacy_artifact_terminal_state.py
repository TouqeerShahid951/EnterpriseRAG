from __future__ import annotations

from time import perf_counter

from rag.auth.context import UserContext
from rag.query.artifact_intent import ArtifactRequest
from rag.query.artifact_models import (
    ArtifactContent,
    ArtifactValidation,
    CoverageReport,
    SemanticSection,
)
from rag.query.artifact_service import ArtifactGenerationResult
from rag.query.nodes import QueryNodes
from rag.query.state import initial_state
from rag.schemas.query import QueryRequest, RAGResponse


class _FailingArtifactService:
    def create_for_response(self, **_kwargs: object) -> ArtifactGenerationResult:
        return ArtifactGenerationResult(artifacts=[], failures=["pdf"])


def test_legacy_generator_does_not_report_success_when_every_format_fails() -> None:
    request = QueryRequest(query="Create a PDF report about quarterly risk")
    user = UserContext(user_id="user-1", email="user@example.test", group_paths=("/",))
    ctx = initial_state(
        trace_id="trace-1",
        session_id="session-1",
        request=request,
        user=user,
        started=perf_counter(),
    )
    ctx["artifact_request"] = ArtifactRequest(
        original_query=request.query,
        content_query="quarterly risk",
        formats=("pdf",),
    )
    ctx["artifact_content"] = ArtifactContent(
        title="Quarterly risk",
        purpose="Summarize quarterly risk.",
        sections=(SemanticSection(heading="Summary", paragraphs=("Supported summary.",)),),
        claims=(),
        citations=(),
        coverage=CoverageReport(
            status="high_confidence",
            evidence_count=1,
            relevant_evidence_count=1,
            documents_searched=1,
            documents_expected=None,
        ),
    )
    ctx["artifact_validation"] = ArtifactValidation(
        passed=True,
        support_score=1.0,
        errors=(),
        warnings=(),
    )
    ctx["response"] = RAGResponse(
        trace_id="trace-1",
        answer="Prepared an evidence-backed PDF artifact.",
        conflict_flag=False,
        faithfulness_score=1.0,
        intent="conversational",
        session_id="session-1",
        latency_ms=0,
        degraded=False,
    )
    nodes = object.__new__(QueryNodes)
    nodes.artifact_service = _FailingArtifactService()

    result = nodes.artifact_generator(ctx)

    assert result["response"].artifacts == []
    assert result["response"].answer == "Artifact generation failed; no requested files were created."
    assert result["response"].degraded is True
    assert result["response"].degraded_reason == "artifact_generation_failed"
