from __future__ import annotations

from rag.auth.context import UserContext
from rag.core.config import Settings
from rag.query.service import LocalRagService
from rag.schemas.query import ArtifactJobSummary, QueryRequest


def test_streamed_artifact_request_enqueues_full_job_without_seeded_answer() -> None:
    artifact_jobs = _ArtifactJobService()
    service = LocalRagService(
        config=Settings(document_repository="memory", artifact_pipeline_version="v2"),
        ollama=object(),
        qdrant=object(),
        session_store=_SessionStore(),
        conflict_checker=object(),
        artifact_job_service=artifact_jobs,
    )

    events = list(service.stream_query(
        QueryRequest(query="Create a detailed presentation of all crimes in the FIRs"),
        _user(),
    ))

    assert [event.event for event in events] == ["trace", "artifact_job", "token", "done"]
    assert artifact_jobs.calls[0]["formats"] == ("pptx",)
    assert "seeded_bundle" not in artifact_jobs.calls[0]
    assert artifact_jobs.calls[0]["request"].query == "Create a detailed presentation of all crimes in the FIRs"


class _SessionStore:
    def load(self, **_kwargs):
        return []


class _ArtifactJobService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def submit(self, **kwargs) -> ArtifactJobSummary:
        self.calls.append(kwargs)
        return ArtifactJobSummary(
            id="job-1",
            status="queued",
            stage="queued",
            progress_pct=0,
            stage_label="Queued",
            stage_detail="Waiting for the document generation worker",
            stage_progress=None,
            requested_formats=list(kwargs["formats"]),
        )


def _user() -> UserContext:
    return UserContext(
        user_id="user-1",
        email="user@example.test",
        account_type="platform_admin",
        group_paths=("/",),
        permission_version=1,
    )
