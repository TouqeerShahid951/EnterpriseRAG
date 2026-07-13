from __future__ import annotations

import json

from billiard.exceptions import SoftTimeLimitExceeded

from rag.artifact_jobs.generation import ArtifactGenerationError


class CapturingSectionInference:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_json(self, *, prompt: str, **_kwargs) -> str:
        self.prompts.append(prompt)
        if "FormatSpecifications" in prompt or "formatting specifications" in prompt:
            return format_spec_json()
        return json.dumps(
            {
                "title": "Facts",
                "blocks": [
                    {
                        "kind": "paragraph",
                        "text": "Evidence fact.",
                        "evidence_ids": ["E1"],
                    }
                ],
            }
        )


class PresentationFormattingInference:
    def generate_json(self, *, prompt: str, **_kwargs) -> str:
        if "formatting specifications" in prompt:
            return format_spec_json(
                title="Policy Risk Briefing",
                subtitle="Executive overview",
                slide_titles=("Priority Risks", "Actions"),
            )
        return json.dumps(
            {
                "title": "Details",
                "blocks": [
                    {
                        "kind": "bullet_list",
                        "list_items": [
                            {
                                "text": "Privileged access without approval is open.",
                                "evidence_ids": ["E1"],
                            }
                        ],
                    }
                ],
            }
        )


class CountingPlannerInference:
    def __init__(self, response: str | None = None) -> None:
        self.response = response or "{}"
        self.calls = 0
        self.prompts: list[str] = []

    def generate_json(self, *, prompt: str, **_kwargs) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        return self.response


class FailingInference:
    def generate_json(self, **_kwargs) -> str:
        raise TimeoutError("composition call failed")


class ProviderFailureInference:
    def generate_json(self, **_kwargs) -> str:
        raise ArtifactGenerationError("vllm", 503)


class SoftTimeInference:
    def generate_json(self, **_kwargs) -> str:
        raise SoftTimeLimitExceeded()


class BuggyInference:
    def generate_json(self, **_kwargs) -> str:
        raise TypeError("invalid generator signature")


class SoftTimeFormattingInference:
    def generate_json(self, *, prompt: str, **_kwargs) -> str:
        if "formatting specifications" in prompt:
            raise SoftTimeLimitExceeded()
        return json.dumps(
            {
                "title": "Facts",
                "blocks": [
                    {
                        "kind": "paragraph",
                        "text": "Evidence fact.",
                        "evidence_ids": ["E1"],
                    }
                ],
            }
        )


def planner_plan_json() -> str:
    return json.dumps(
        {
            "title": "Vendor Policy Change Briefing",
            "purpose": "Create an evidence-grounded briefing on vendor policy changes.",
            "audience": "Executive leadership",
            "language": "English",
            "tone": "professional",
            "detail_level": "detailed",
            "document_type": "presentation",
            "assumptions": ["Use only authorized retrieved evidence."],
            "clarification_questions": [],
            "sections": [
                {
                    "title": "Timeline",
                    "objective": "Build a chronological view of vendor policy changes.",
                    "preferred_blocks": ["numbered_list", "table"],
                    "retrieval_queries": [
                        "vendor policy changes timeline",
                        "vendor policy amendments dates",
                        "vendor policy version history",
                        "vendor policy chronology",
                    ],
                    "retrieval_mode": "timeline",
                    "coverage_requirement": "relevant_evidence",
                },
                {
                    "title": "Risk Matrix",
                    "objective": "Extract policy risks and classify their status.",
                    "preferred_blocks": ["table", "bullet_list"],
                    "retrieval_queries": [
                        "vendor policy risks",
                        "vendor risk matrix",
                    ],
                    "retrieval_mode": "structured_rows",
                    "coverage_requirement": "complete_authorized_scope",
                },
            ],
            "format_requirements": {
                "pptx": ["Use executive slide titles.", "Use tables for risks."],
            },
        }
    )


def format_spec_json(
    *,
    title: str = "Formatted Artifact",
    subtitle: str = "Evidence-backed output",
    slide_titles: tuple[str, ...] = ("Facts",),
) -> str:
    block = {
        "kind": "paragraph",
        "text": "Evidence fact.",
        "evidence_ids": ["E1"],
    }
    return json.dumps(
        {
            "paginated": {
                "title": title,
                "subtitle": subtitle,
                "sections": [{"title": "Facts", "blocks": [block]}],
                "include_references": True,
                "include_coverage_notes": True,
            },
            "presentation": {
                "title": title,
                "subtitle": subtitle,
                "slides": [
                    {"title": slide_title, "blocks": [block]}
                    for slide_title in slide_titles
                ],
                "include_references_slide": True,
            },
        }
    )
