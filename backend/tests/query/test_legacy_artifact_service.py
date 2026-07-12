from __future__ import annotations

from pathlib import Path

from rag.artifact_jobs.adapters.generated_memory import (
    InMemoryGeneratedArtifactRepository,
)
from rag.auth.context import UserContext
from rag.query.artifact_intent import ArtifactRequest
from rag.query.artifact_renderer import RenderedArtifact
from rag.query.artifact_service import GeneratedArtifactService
from rag.schemas.query import RAGResponse
from rag.services.generated_artifact_storage import LocalGeneratedArtifactStorage


def test_legacy_artifact_audit_failure_does_not_discard_valid_file(tmp_path, monkeypatch) -> None:
    artifacts = InMemoryGeneratedArtifactRepository()
    storage = LocalGeneratedArtifactStorage(str(tmp_path))
    monkeypatch.setattr(
        "rag.query.artifact_service.render_artifact",
        lambda **_kwargs: RenderedArtifact(
            filename="report.pdf",
            format="pdf",
            content_type="application/pdf",
            content=b"%PDF-valid-content",
        ),
    )
    service = GeneratedArtifactService(
        repo_factory=lambda: artifacts,
        storage_factory=lambda: storage,
        audit_repo_factory=_FailingAuditRepository,
    )

    result = service.create_for_response(
        artifact_request=ArtifactRequest(
            original_query="Create a PDF report about quarterly risk",
            content_query="quarterly risk",
            formats=("pdf",),
        ),
        response=RAGResponse(
            trace_id="trace-1",
            answer="Grounded response.",
            conflict_flag=False,
            faithfulness_score=1.0,
            intent="conversational",
            session_id="session-1",
            latency_ms=0,
            degraded=False,
        ),
        user=UserContext(
            user_id="user-1",
            email="user@example.test",
            group_paths=("/",),
            permission_version=1,
        ),
        session_id="session-1",
        trace_id="trace-1",
    )

    assert result.failures == []
    assert len(result.artifacts) == 1
    record = artifacts.get_artifact(result.artifacts[0].id)
    assert record is not None
    assert Path(record.object_path).read_bytes() == b"%PDF-valid-content"


class _FailingAuditRepository:
    def append_audit_event(self, **_kwargs: object) -> None:
        raise RuntimeError("audit unavailable")
