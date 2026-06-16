"""LLM document planning from the untouched user request."""

from __future__ import annotations

import json
import re

from ..repositories.artifact_jobs import ArtifactJobRecord
from .contracts import DocumentPlan, DocumentPlanSection
from .llm_json import generate_contract


PLANNER_PROMPT_VERSION = "document-planner-v2.1"


def plan_document(
    job: ArtifactJobRecord,
    *,
    inference: object,
    model: str | None,
) -> DocumentPlan:
    deterministic = _deterministic_plan(job)
    if deterministic is not None:
        return deterministic

    scope = {
        "group_path": job.group_path,
        "document_ids": list(job.document_ids),
        "requested_formats": list(job.requested_formats),
        "conversation_context": list(job.conversation_context)[-6:],
        "clarifications": job.clarifications,
    }
    prompt = (
        "Create a retrieval-first document plan from the original request. Do not answer the request. "
        "The original request must remain the source of truth. Infer audience, tone, and standard detail "
        "when omitted. Ask clarification questions only when the topic, source scope, or deliverable is "
        "too ambiguous to retrieve and compose safely. Every non-clarification plan must contain dynamic "
        "sections, each with one to four standalone RAG retrieval queries. Use document_scan for selected-"
        "document summaries or exhaustive selected-document coverage, structured_rows for exhaustive lists "
        "or field extraction, comparison for comparisons, timeline for chronological work, and focused_search "
        "otherwise. Never claim exhaustive coverage from focused_search.\n\n"
        f"Original request:\n{job.original_request}\n\n"
        f"Scope and context:\n{json.dumps(scope, ensure_ascii=True)}\n\n"
        f"Return JSON matching this schema:\n{json.dumps(DocumentPlan.model_json_schema(), separators=(',', ':'))}"
    )
    return generate_contract(
        inference=inference,
        model=model,
        system="You are a strict enterprise document-generation planner.",
        prompt=prompt,
        contract=DocumentPlan,
    )


def _deterministic_plan(job: ArtifactJobRecord) -> DocumentPlan | None:
    topic = _extract_topic(job.original_request)
    if not topic:
        return DocumentPlan(
            title="Clarification Needed",
            purpose="Clarify the requested artifact topic before retrieval and generation.",
            clarification_questions=[
                "What topic, document set, or business question should this artifact cover?"
            ],
        )

    lowered = job.original_request.lower()
    exhaustive = _requests_exhaustive_rows(lowered)
    summary_mode = "document_scan" if job.document_ids else "focused_search"
    summary_coverage = "complete_selected_documents" if job.document_ids else "relevant_evidence"
    detail_mode = "document_scan" if job.document_ids else ("structured_rows" if exhaustive else "focused_search")
    detail_coverage = "complete_selected_documents" if job.document_ids else ("complete_authorized_scope" if exhaustive else "relevant_evidence")
    blocks = ["paragraph", "bullet_list"]
    if exhaustive:
        blocks = ["table", "bullet_list", "paragraph"]

    sections = [
        DocumentPlanSection(
            title="Summary",
            objective=f"Summarize the key information about {topic}.",
            preferred_blocks=["paragraph", "bullet_list"],
            retrieval_queries=[
                topic,
                f"{topic} summary",
            ],
            retrieval_mode=summary_mode,  # type: ignore[arg-type]
            coverage_requirement=summary_coverage,
        ),
        DocumentPlanSection(
            title="Details",
            objective=f"Extract supporting details and source-backed facts about {topic}.",
            preferred_blocks=blocks,  # type: ignore[arg-type]
            retrieval_queries=[
                f"{topic} details",
                job.original_request.strip(),
            ],
            retrieval_mode=detail_mode,  # type: ignore[arg-type]
            coverage_requirement=detail_coverage,
        ),
    ]
    if any(marker in lowered for marker in ("compare", "comparison", "versus", " vs ")):
        sections.append(
            DocumentPlanSection(
                title="Comparison",
                objective=f"Compare the relevant facts for {topic}.",
                preferred_blocks=["table", "bullet_list"],
                retrieval_queries=[f"{topic} comparison"],
                retrieval_mode="comparison",
                coverage_requirement="relevant_evidence",
            )
        )
    if any(marker in lowered for marker in ("timeline", "chronology", "chronological", "date")):
        sections.append(
            DocumentPlanSection(
                title="Timeline",
                objective=f"Build a chronological account for {topic}.",
                preferred_blocks=["numbered_list", "table"],
                retrieval_queries=[f"{topic} timeline dates chronology"],
                retrieval_mode="timeline",
                coverage_requirement="relevant_evidence",
            )
        )

    return DocumentPlan(
        title=_title_from_topic(topic),
        purpose=f"Create an evidence-grounded artifact about {topic}.",
        document_type=_document_type(job.requested_formats),
        assumptions=[
            "Use only retrieved evidence from authorized documents.",
            "Do not claim exhaustive coverage unless selected documents were scanned.",
        ],
        sections=sections,
        format_requirements={
            artifact_format: _format_requirements(artifact_format)
            for artifact_format in job.requested_formats
        },
    )


def _requests_exhaustive_rows(lowered_request: str) -> bool:
    return any(
        marker in lowered_request
        for marker in ("list", "all ", "table", "rows", "extract", "information")
    )


def _extract_topic(request: str) -> str:
    text = re.sub(r"\s+", " ", request).strip(" .")
    text = re.sub(
        r"(?i)^(please\s+)?(generate|create|make|prepare|draft|write|build)\s+"
        r"(an?\s+)?(pdf|docx|pptx|powerpoint|presentation|slide\s+deck|report|document|artifact)"
        r"(\s+(report|document|presentation|deck|file))?\s*",
        "",
        text,
    )
    text = re.sub(r"(?i)^(?:file\s+)?(?:summari[sz](?:e|ing)|summary\s+of|overview\s+of|explain(?:ing)?|describe|describing|analy[sz](?:e|ing)|identify(?:ing)?|list(?:ing)?)\s+", "", text).strip(" .")
    text = re.sub(r"(?i)^(on|about|for|covering|with)\s+", "", text).strip(" .")
    text = re.sub(r"(?i)^(the|this|selected)\s+", "", text).strip(" .")
    text = re.sub(r"(?i)\b(as|in)\s+(pdf|docx|pptx|powerpoint|presentation|slides?)\b", "", text).strip(" .")
    if len(text) < 4:
        return ""
    if text.lower() in {"pdf", "docx", "pptx", "presentation", "report", "document", "artifact"}:
        return ""
    return text[:240]


def _title_from_topic(topic: str) -> str:
    words = [word for word in re.split(r"\s+", topic.strip()) if word]
    titled = " ".join(word.upper() if word.isupper() else word.capitalize() for word in words[:12])
    return titled[:180] or "Generated Artifact"


def _document_type(formats: tuple[str, ...]) -> str:
    if "pptx" in formats:
        return "presentation"
    if "pdf" in formats or "docx" in formats:
        return "report"
    return "artifact"


def _format_requirements(artifact_format: str) -> list[str]:
    if artifact_format == "pptx":
        return [
            "Use concise slide titles.",
            "Prefer tables or bullet lists for extracted facts.",
            "Include a references slide when citations are available.",
        ]
    if artifact_format == "docx":
        return ["Use section headings and source-backed paragraphs."]
    if artifact_format == "pdf":
        return ["Use a printable report layout with citations."]
    return ["Use evidence-grounded content with citations."]
