from __future__ import annotations

from billiard.exceptions import SoftTimeLimitExceeded
import pytest

from rag.artifact_jobs.generation.planner import plan_document

from generation_inference_support import (
    BuggyInference,
    CountingPlannerInference,
    FailingInference,
    ProviderFailureInference,
    SoftTimeInference,
    planner_plan_json,
)
from generation_optimization_support import artifact_job


def test_planner_extracts_topic_from_detailed_presentation_request() -> None:
    plan = plan_document(
        artifact_job(
            original_request=(
                "Create a detailed presentation of all crimes committed in the FIRs"
            ),
            requested_formats=("pptx",),
        ),
        inference=FailingInference(),
        model=None,
    )

    assert plan.title == "All Crimes Committed In The FIRs"
    assert "Create a detailed presentation" not in plan.purpose


def test_planner_keeps_simple_request_on_fast_path() -> None:
    inference = CountingPlannerInference()

    plan = plan_document(
        artifact_job(
            original_request="Create a report about vendor policy",
            requested_formats=("pdf",),
        ),
        inference=inference,
        model=None,
    )

    assert inference.calls == 0
    assert plan.title == "Vendor Policy"
    assert [section.title for section in plan.sections] == ["Summary", "Details"]


def test_planner_uses_single_llm_call_for_complex_artifact_request() -> None:
    inference = CountingPlannerInference(planner_plan_json())

    plan = plan_document(
        artifact_job(
            original_request=(
                "Create a comprehensive executive briefing with a timeline and risk "
                "matrix for vendor policy changes"
            ),
            requested_formats=("pptx",),
        ),
        inference=inference,
        model="planner-model",
    )

    assert inference.calls == 1
    assert plan.title == "Vendor Policy Change Briefing"
    assert [section.retrieval_mode for section in plan.sections] == [
        "timeline",
        "structured_rows",
    ]
    assert all(len(section.retrieval_queries) <= 4 for section in plan.sections)
    assert "pptx" in plan.format_requirements


def test_planner_falls_back_when_complex_llm_plan_fails() -> None:
    plan = plan_document(
        artifact_job(
            original_request=(
                "Create a comprehensive timeline of all vendor policy changes"
            ),
            requested_formats=("pptx",),
        ),
        inference=FailingInference(),
        model=None,
    )

    assert plan.title == "Timeline Of All Vendor Policy Changes"
    assert [section.title for section in plan.sections] == [
        "Summary",
        "Details",
        "Timeline",
    ]


def test_planner_falls_back_when_generation_provider_is_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger="rag.artifact_jobs")

    plan = plan_document(
        artifact_job(
            original_request=(
                "Create a comprehensive timeline of all vendor policy changes"
            ),
            requested_formats=("pptx",),
        ),
        inference=ProviderFailureInference(),
        model=None,
    )

    assert plan.title == "Timeline Of All Vendor Policy Changes"
    assert [section.title for section in plan.sections] == [
        "Summary",
        "Details",
        "Timeline",
    ]
    assert "artifact planning fallback" in caplog.text
    assert "ArtifactGenerationError" in caplog.text


def test_planner_propagates_soft_time_limit() -> None:
    with pytest.raises(SoftTimeLimitExceeded):
        plan_document(
            artifact_job(
                original_request=(
                    "Create a comprehensive timeline of all vendor policy changes"
                ),
                requested_formats=("pptx",),
            ),
            inference=SoftTimeInference(),
            model=None,
        )


def test_planner_does_not_hide_generator_programming_errors() -> None:
    with pytest.raises(TypeError, match="invalid generator signature"):
        plan_document(
            artifact_job(
                original_request=(
                    "Create a comprehensive timeline of all vendor policy changes"
                ),
                requested_formats=("pptx",),
            ),
            inference=BuggyInference(),
            model=None,
        )
