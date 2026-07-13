"""LLM-backed and deterministic artifact format adaptation."""

from __future__ import annotations

import json
import logging
import re

from .composition_deadline import _section_deadline
from .contracts import (
    ContentSection,
    DocumentPlan,
    EvidenceBackedContent,
    FormatSpecifications,
    PaginatedDocumentSpec,
    PresentationSlide,
    PresentationSpec,
)
from .generation import ArtifactGenerationError, ArtifactJsonGenerator
from .job_models import ArtifactJobRecord
from .llm_json import LlmContractError, generate_contract


FORMATTER_PROMPT_VERSION = "document-formatter-llm-v3.0"
MAX_BLOCKS_PER_SLIDE = 4
MAX_PRESENTATION_SLIDES = 80
REFERENCE_SLIDE_TITLES = {
    "reference",
    "references",
    "source",
    "sources",
    "citation",
    "citations",
    "bibliography",
}

logger = logging.getLogger("rag.artifact_jobs")


def _adapt_formats(
    job: ArtifactJobRecord,
    plan: DocumentPlan,
    content: EvidenceBackedContent,
    *,
    inference: ArtifactJsonGenerator,
    model: str | None,
    timeout_seconds: float | None,
) -> FormatSpecifications:
    try:
        with _section_deadline(timeout_seconds):
            return _adapt_formats_with_llm(
                job, plan, content, inference=inference, model=model
            )
    except (ArtifactGenerationError, LlmContractError, TimeoutError) as exc:
        logger.warning(
            "artifact format adaptation fallback job_id=%s error_type=%s",
            job.id,
            type(exc).__name__,
        )
        return _adapt_formats_deterministic(plan, content)


def _adapt_formats_with_llm(
    job: ArtifactJobRecord,
    plan: DocumentPlan,
    content: EvidenceBackedContent,
    *,
    inference: ArtifactJsonGenerator,
    model: str | None,
) -> FormatSpecifications:
    prompt = (
        "Create final DOCX/PDF and presentation formatting specifications from the composed evidence-backed content. "
        "You decide the artifact title, subtitle, number of presentation slides, slide titles, and which content blocks "
        "belong on each slide. You may choose paragraphs, bullets, key-value blocks, or tables when the existing content "
        "supports them. Preserve citations and use only the existing evidence IDs. Do not invent facts. Keep slides "
        "usable: prefer 1-3 blocks per slide, concise titles, and split dense content across multiple slides. The renderer "
        "may still add continuation slides if physical layout requires it. Do not include a slide titled References, "
        "Sources, Citations, or Bibliography; the renderer appends that slide from citations. Return only JSON matching "
        "the schema.\n\n"
        f"Original request:\n{job.original_request}\n\n"
        f"Plan:\n{plan.model_dump_json()}\n\n"
        f"Composed content:\n{content.model_dump_json()}\n\n"
        f"Schema:\n{json.dumps(FormatSpecifications.model_json_schema(), separators=(',', ':'))}"
    )
    formats = generate_contract(
        inference=inference,
        model=model,
        system="You are a presentation and document formatter for evidence-backed enterprise artifacts.",
        prompt=prompt,
        contract=FormatSpecifications,
    )
    return _normalized_formats(formats, content)


def _normalized_formats(
    formats: FormatSpecifications, content: EvidenceBackedContent
) -> FormatSpecifications:
    paginated = formats.paginated.model_copy(
        update={
            "title": formats.paginated.title or content.title,
            "sections": formats.paginated.sections or content.sections,
            "include_references": True,
            "include_coverage_notes": True,
        }
    )
    slides = _without_generated_references_slides(
        formats.presentation.slides or _presentation_slides(content.sections)
    )
    if not slides:
        slides = _presentation_slides(content.sections)
    presentation = formats.presentation.model_copy(
        update={
            "title": formats.presentation.title or content.title,
            "slides": slides[:MAX_PRESENTATION_SLIDES],
            "include_references_slide": True,
        }
    )
    return FormatSpecifications(paginated=paginated, presentation=presentation)


def _adapt_formats_deterministic(
    plan: DocumentPlan,
    content: EvidenceBackedContent,
) -> FormatSpecifications:
    subtitle = _subtitle(plan)
    return FormatSpecifications(
        paginated=PaginatedDocumentSpec(
            title=content.title,
            subtitle=subtitle,
            sections=content.sections,
            include_references=True,
            include_coverage_notes=True,
        ),
        presentation=PresentationSpec(
            title=content.title,
            subtitle=subtitle,
            slides=_presentation_slides(content.sections),
            include_references_slide=True,
        ),
    )


def _subtitle(plan: DocumentPlan) -> str:
    return f"{plan.document_type.title()} for {plan.audience}"


def _presentation_slides(sections: list[ContentSection]) -> list[PresentationSlide]:
    slides: list[PresentationSlide] = []
    for section in sections:
        for index, blocks in enumerate(
            _chunks(section.blocks, MAX_BLOCKS_PER_SLIDE), start=1
        ):
            title = section.title if index == 1 else f"{section.title} ({index})"
            slides.append(PresentationSlide(title=title, blocks=blocks))
            if len(slides) >= MAX_PRESENTATION_SLIDES:
                return slides
    return slides


def _without_generated_references_slides(
    slides: list[PresentationSlide],
) -> list[PresentationSlide]:
    return [slide for slide in slides if not _is_generated_references_slide(slide)]


def _is_generated_references_slide(slide: PresentationSlide) -> bool:
    return _normalized_reference_title(slide.title) in REFERENCE_SLIDE_TITLES


def _normalized_reference_title(value: str) -> str:
    return re.sub(r"[^a-z]+", " ", value.lower()).strip()


def _chunks(blocks: list, size: int) -> list[list]:
    return [blocks[offset : offset + size] for offset in range(0, len(blocks), size)]
