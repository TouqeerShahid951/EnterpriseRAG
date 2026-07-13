"""Contract tests for query-to-artifact job submissions."""

import pytest
from pydantic import ValidationError

from rag.artifact_jobs.submission import ArtifactJobSubmission


def test_artifact_job_submission_is_immutable_and_forbids_unknown_fields() -> None:
    submission = ArtifactJobSubmission(original_request="Create a report")

    with pytest.raises(ValidationError):
        submission.original_request = "Replace the report"
    with pytest.raises(ValidationError):
        ArtifactJobSubmission(
            original_request="Create a report",
            unsupported_scope="all",
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"original_request": ""},
        {"client_request_id": ""},
        {"client_request_id": "x" * 121},
        {"group_path": ""},
        {"document_ids": tuple(f"doc-{index}" for index in range(21))},
    ],
)
def test_artifact_job_submission_preserves_query_boundary_limits(
    changes: dict[str, object],
) -> None:
    payload = {"original_request": "Create a report", **changes}
    with pytest.raises(ValidationError):
        ArtifactJobSubmission(**payload)
