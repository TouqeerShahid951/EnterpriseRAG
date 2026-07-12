from __future__ import annotations

from dataclasses import replace

from rag.artifact_jobs.planner import plan_document
from rag.artifact_jobs.repository import InMemoryArtifactJobRepository


_TOPIC_QUESTION = (
    "What topic, document set, or business question should this artifact cover?"
)


def test_missing_topic_requests_clarification() -> None:
    plan = plan_document(
        _job(original_request="Create a PPTX"),
        inference=_FailingInference(),
        model=None,
    )

    assert plan.title == "Clarification Needed"
    assert plan.clarification_questions == [_TOPIC_QUESTION]
    assert plan.sections == []


def test_topic_clarification_resolves_the_document_plan() -> None:
    job = replace(
        _job(original_request="Create a PPTX"),
        clarifications={_TOPIC_QUESTION: "Quarterly financial results"},
    )

    plan = plan_document(job, inference=_FailingInference(), model=None)

    assert plan.clarification_questions == []
    assert plan.title == "Quarterly Financial Results"
    assert plan.sections
    assert plan.sections[0].retrieval_queries[0] == "Quarterly financial results"
    assert plan.sections[1].retrieval_queries == [
        "Quarterly financial results details",
        "Quarterly financial results",
    ]


def test_clarification_answer_prefix_and_whitespace_are_normalized() -> None:
    job = replace(
        _job(original_request="Generate a PDF"),
        clarifications={
            _TOPIC_QUESTION: "  The topic is   quarterly financial results.  ",
        },
    )

    plan = plan_document(job, inference=_FailingInference(), model=None)

    assert plan.title == "Quarterly Financial Results"
    assert plan.purpose.endswith("about quarterly financial results.")
    assert not plan.clarification_questions


def test_topic_question_is_preferred_when_multiple_answers_exist() -> None:
    job = replace(
        _job(original_request="Create a DOCX"),
        clarifications={
            "Who is the audience?": "Executive leadership",
            _TOPIC_QUESTION: "Vendor policy exceptions",
        },
    )

    plan = plan_document(job, inference=_FailingInference(), model=None)

    assert plan.title == "Vendor Policy Exceptions"


def _job(*, original_request: str):
    return InMemoryArtifactJobRepository().create_job(
        client_request_id="request-1",
        user_id="user-1",
        permission_version=1,
        user_email="user@example.test",
        account_type="platform_admin",
        group_paths=["/"],
        clearance_level="NATO_RESTRICTED",
        session_id="session-1",
        trace_id="trace-1",
        original_request=original_request,
        requested_formats=["pptx"],
        group_path=None,
        document_ids=[],
        conversation_context=[],
        retention_days=1,
    )


class _FailingInference:
    def generate_json(self, **_kwargs) -> str:
        raise TimeoutError("planner unavailable")
