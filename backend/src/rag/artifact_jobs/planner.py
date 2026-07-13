"""LLM document planning from the untouched user request."""

from __future__ import annotations

import json
import logging
import re

from .contracts import DocumentPlan, DocumentPlanSection
from .generation import ArtifactGenerationError, ArtifactJsonGenerator
from .job_models import ArtifactJobRecord
from .llm_json import LlmContractError, generate_contract
from .request_text import cleaned_content_query


PLANNER_PROMPT_VERSION = "document-planner-v2.2"
_MAX_LLM_SECTIONS = 8
_MAX_SECTION_QUERIES = 4
_TOPIC_QUESTION_MARKERS = (
    "topic",
    "subject",
    "cover",
    "business question",
    "document set",
)
_EMPTY_CLARIFICATION_ANSWERS = {
    "n/a",
    "na",
    "no",
    "none",
    "not applicable",
    "not sure",
    "unknown",
    "yes",
}
_CLARIFICATION_TOPIC_PREFIXES = (
    re.compile(
        r"(?i)^(?:the\s+)?(?:artifact\s+)?(?:topic|subject|business\s+question|document\s+set)"
        r"\s*(?:is|should\s+be|will\s+be|:|-)\s*"
    ),
    re.compile(
        r"(?i)^(?:it|the\s+(?:artifact|report|presentation|document))\s+"
        r"(?:should|will)\s+(?:cover|focus\s+on|be\s+about)\s+"
    ),
)

logger = logging.getLogger("rag.artifact_jobs")


def plan_document(
    job: ArtifactJobRecord,
    *,
    inference: ArtifactJsonGenerator,
    model: str | None,
) -> DocumentPlan:
    topic = _resolve_topic(job)
    if not topic:
        return _clarification_plan()

    fallback = _deterministic_plan(job, topic=topic)
    if not _should_use_llm_plan(job, topic=topic):
        return fallback

    try:
        planned = _llm_plan(
            job, topic=topic, fallback=fallback, inference=inference, model=model
        )
    except (ArtifactGenerationError, LlmContractError, TimeoutError) as exc:
        logger.warning(
            "artifact planning fallback job_id=%s error_type=%s",
            job.id,
            type(exc).__name__,
        )
        return fallback
    return _normalize_llm_plan(planned, fallback=fallback, job=job)


def _llm_plan(
    job: ArtifactJobRecord,
    *,
    topic: str,
    fallback: DocumentPlan,
    inference: ArtifactJsonGenerator,
    model: str | None,
) -> DocumentPlan:
    return generate_contract(
        inference=inference,
        model=model,
        system="You are a strict enterprise document-generation planner.",
        prompt=_planner_prompt(job, topic=topic, fallback=fallback),
        contract=DocumentPlan,
    )


def _planner_prompt(
    job: ArtifactJobRecord, *, topic: str, fallback: DocumentPlan
) -> str:
    scope = {
        "group_path": job.group_path,
        "document_ids": list(job.document_ids),
        "requested_formats": list(job.requested_formats),
        "conversation_context": list(job.conversation_context)[-4:],
        "clarifications": job.clarifications,
        "fallback_sections": [section.title for section in fallback.sections],
    }
    return (
        "Create a retrieval-first artifact plan. Return only one JSON object. Do not answer the request.\n"
        'Required JSON keys: version="v2", title, purpose, audience, language, tone, detail_level, '
        "document_type, assumptions, clarification_questions, sections, and format_requirements. "
        "Each section needs title, objective, preferred_blocks, retrieval_queries, retrieval_mode, "
        "and coverage_requirement.\n"
        "Allowed detail_level: brief, standard, detailed. Allowed retrieval_mode: focused_search, "
        "document_scan, structured_rows, comparison, timeline. Allowed blocks: paragraph, bullet_list, "
        "numbered_list, key_value, table, quotation, callout.\n"
        "Rules: keep 2-6 sections unless the request truly needs more, never more than 8. Each section "
        "needs 1-4 standalone retrieval queries. Use document_scan for selected-document summaries or "
        "complete selected-document coverage, structured_rows for exhaustive lists or field extraction, "
        "comparison for comparisons, timeline for chronology, focused_search otherwise. Never claim "
        "complete coverage from focused_search. Ask clarification only if topic, scope, or deliverable "
        "is impossible to infer; this topic is already clear.\n\n"
        f"Topic: {topic}\n"
        f"Original request: {job.original_request}\n"
        f"Scope/context JSON: {json.dumps(scope, ensure_ascii=True, separators=(',', ':'))}\n"
    )


def _deterministic_plan(job: ArtifactJobRecord, *, topic: str) -> DocumentPlan:
    lowered = f"{job.original_request} {topic}".lower()
    exhaustive = _requests_exhaustive_rows(lowered)
    summary_mode = "document_scan" if job.document_ids else "focused_search"
    summary_coverage = (
        "complete_selected_documents" if job.document_ids else "relevant_evidence"
    )
    detail_mode = (
        "document_scan"
        if job.document_ids
        else ("structured_rows" if exhaustive else "focused_search")
    )
    detail_coverage = (
        "complete_selected_documents"
        if job.document_ids
        else ("complete_authorized_scope" if exhaustive else "relevant_evidence")
    )
    blocks = ["paragraph", "bullet_list"]
    if exhaustive:
        blocks = ["table", "bullet_list", "paragraph"]

    request_query = cleaned_content_query(job.original_request).strip() or topic
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
            retrieval_queries=_dedupe_non_empty([f"{topic} details", request_query]),
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
    if any(
        marker in lowered
        for marker in ("timeline", "chronology", "chronological", "date")
    ):
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


def _clarification_plan() -> DocumentPlan:
    return DocumentPlan(
        title="Clarification Needed",
        purpose="Clarify the requested artifact topic before retrieval and generation.",
        clarification_questions=[
            "What topic, document set, or business question should this artifact cover?"
        ],
    )


def _should_use_llm_plan(job: ArtifactJobRecord, *, topic: str) -> bool:
    lowered = job.original_request.lower()
    padded = f" {lowered} "
    if job.clarifications or job.conversation_context:
        return True
    if len(job.requested_formats) > 1:
        return True
    if len(topic.split()) >= 14:
        return True
    if any(
        marker in padded
        for marker in (
            " all ",
            " every ",
            " each ",
            "complete",
            "comprehensive",
            "detailed",
            " full ",
            "extract",
            "fields",
            "list",
            "matrix",
            "recommendation",
            "risk",
            "rows",
            "table",
        )
    ):
        return True
    if any(
        marker in lowered
        for marker in (
            "compare",
            "comparison",
            "versus",
            " vs ",
            "timeline",
            "chronology",
            "chronological",
        )
    ):
        return True
    if "pptx" in job.requested_formats and any(
        marker in lowered
        for marker in (
            "board",
            "briefing",
            "executive",
            "slide",
        )
    ):
        return True
    return False


def _normalize_llm_plan(
    plan: DocumentPlan,
    *,
    fallback: DocumentPlan,
    job: ArtifactJobRecord,
) -> DocumentPlan:
    if plan.clarification_questions:
        return fallback
    sections: list[DocumentPlanSection] = []
    for index, section in enumerate(plan.sections[:_MAX_LLM_SECTIONS]):
        fallback_section = fallback.sections[min(index, len(fallback.sections) - 1)]
        queries = _dedupe_non_empty(section.retrieval_queries)[:_MAX_SECTION_QUERIES]
        if not queries:
            queries = list(fallback_section.retrieval_queries)
        sections.append(
            section.model_copy(
                update={
                    "title": section.title.strip() or fallback_section.title,
                    "objective": section.objective.strip()
                    or fallback_section.objective,
                    "preferred_blocks": section.preferred_blocks
                    or fallback_section.preferred_blocks,
                    "retrieval_queries": queries,
                }
            )
        )
    if not sections:
        return fallback
    return plan.model_copy(
        update={
            "title": _clean_plan_title(plan.title) or fallback.title,
            "purpose": plan.purpose.strip() or fallback.purpose,
            "document_type": plan.document_type.strip() or fallback.document_type,
            "assumptions": _dedupe_non_empty(
                [*plan.assumptions, *fallback.assumptions]
            )[:12],
            "sections": sections,
            "format_requirements": _format_requirements_for_plan(job, plan),
        }
    )


def _format_requirements_for_plan(
    job: ArtifactJobRecord, plan: DocumentPlan
) -> dict[str, list[str]]:
    result = {
        artifact_format: _format_requirements(artifact_format)
        for artifact_format in job.requested_formats
    }
    for artifact_format in job.requested_formats:
        llm_requirements = plan.format_requirements.get(artifact_format, [])
        result[artifact_format] = _dedupe_non_empty(
            [*llm_requirements, *result[artifact_format]]
        )[:8]
    return result


def _clean_plan_title(value: str) -> str:
    title = re.sub(r"\s+", " ", value).strip(" .")
    title = re.sub(
        r"(?i)^(create|generate|make|prepare|draft|write|build)\s+(a|an|the)?\s*",
        "",
        title,
    ).strip(" .")
    return title[:180]


def _dedupe_non_empty(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _requests_exhaustive_rows(lowered_request: str) -> bool:
    return any(
        marker in lowered_request
        for marker in ("list", "all ", "table", "rows", "extract", "information")
    )


def _resolve_topic(job: ArtifactJobRecord) -> str:
    request_topic = _extract_topic(job.original_request)
    if request_topic:
        return request_topic

    prioritized_answers = sorted(
        job.clarifications.items(),
        key=lambda item: 0 if _is_topic_question(item[0]) else 1,
    )
    for _question, answer in prioritized_answers:
        normalized_answer = _normalize_clarification_answer(answer)
        if not normalized_answer:
            continue
        answer_topic = _extract_topic(normalized_answer)
        if answer_topic:
            return answer_topic
    return ""


def _is_topic_question(question: str) -> bool:
    lowered = question.lower()
    return any(marker in lowered for marker in _TOPIC_QUESTION_MARKERS)


def _normalize_clarification_answer(answer: str) -> str:
    normalized = re.sub(r"\s+", " ", answer).strip(" \t\r\n\"'.,:;-")
    for prefix in _CLARIFICATION_TOPIC_PREFIXES:
        normalized = prefix.sub("", normalized).strip(" \t\r\n\"'.,:;-")
    if normalized.lower() in _EMPTY_CLARIFICATION_ANSWERS:
        return ""
    return normalized


def _extract_topic(request: str) -> str:
    text = re.sub(r"\s+", " ", cleaned_content_query(request) or request).strip(" .")
    text = re.sub(
        r"(?i)^(please\s+)?(generate|create|make|prepare|draft|write|build)\s+"
        r"(an?\s+)?(?:(detailed|comprehensive|full|complete)\s+)?"
        r"(pdf|docx|pptx|powerpoint|presentation|slide\s+deck|report|document|artifact)"
        r"(\s+(report|document|presentation|deck|file))?\s*",
        "",
        text,
    )
    text = re.sub(
        r"(?i)^(an?\s+|the\s+)?"
        r"(pdf|docx|pptx|powerpoint|presentation|slide\s+deck|report|document|artifact)"
        r"(\s+(report|document|presentation|deck|file))?\s*",
        "",
        text,
    ).strip(" .")
    text = re.sub(
        r"(?i)^(?:file\s+)?(?:summari[sz](?:e|ing)|summary\s+of|overview\s+of|explain(?:ing)?|describe|describing|analy[sz](?:e|ing)|identify(?:ing)?|list(?:ing)?)\s+",
        "",
        text,
    ).strip(" .")
    text = re.sub(r"(?i)^(on|about|for|of|covering|with)\s+", "", text).strip(" .")
    text = re.sub(r"(?i)^(the|this|selected)\s+", "", text).strip(" .")
    text = re.sub(
        r"(?i)\b(as|in)\s+(pdf|docx|pptx|powerpoint|presentation|slides?)\b", "", text
    ).strip(" .")
    if len(text) < 4:
        return ""
    if text.lower() in {
        "pdf",
        "docx",
        "pptx",
        "presentation",
        "report",
        "document",
        "artifact",
    }:
        return ""
    return text[:240]


def _title_from_topic(topic: str) -> str:
    normalized = re.sub(r"(?i)\bcommited\b", "committed", topic.strip())
    words = [word for word in re.split(r"\s+", normalized) if word]
    titled = " ".join(_title_word(word) for word in words[:12])
    return titled[:180] or "Generated Artifact"


def _title_word(word: str) -> str:
    if word.isupper() or (len(word) <= 5 and word[:-1].isupper() and word[-1:] == "s"):
        return word
    return word.upper() if word.isupper() else word.capitalize()


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
