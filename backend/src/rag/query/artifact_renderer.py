"""Render query artifact content through the shared artifact renderer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import TypeVar

from ..artifact_jobs.contracts import (
    ArtifactContentBundle,
    ContentBlock,
    ContentListItem,
    ContentSection,
    ContentTable,
    ContentTableRow,
    EvidenceBackedContent,
    EvidenceCitation as JobEvidenceCitation,
    PaginatedDocumentSpec,
    PresentationSlide,
    PresentationSpec,
)
from ..artifact_jobs.renderer import render_document
from ..schemas.query import ArtifactFormat, RAGResponse
from .artifact_models import (
    ArtifactCitation,
    ArtifactContent,
    ArtifactTable,
    CoverageReport,
    SemanticSection,
    SupportedClaim,
)


T = TypeVar("T")


@dataclass(frozen=True)
class RenderedArtifact:
    filename: str
    format: ArtifactFormat
    content_type: str
    content: bytes


def render_artifact(
    *,
    artifact_format: ArtifactFormat,
    title: str,
    prompt: str,
    generated_at: datetime,
    artifact_content: ArtifactContent | None = None,
    response: RAGResponse | None = None,
) -> RenderedArtifact:
    content = artifact_content or _legacy_content(title=title, prompt=prompt, response=response)
    rendered = render_document(
        artifact_format=artifact_format,
        bundle=_artifact_bundle(content),
        generated_at=generated_at,
        require_libreoffice=False,
    )
    return RenderedArtifact(
        filename=rendered.filename,
        format=rendered.format,
        content_type=rendered.content_type,
        content=rendered.content,
    )


def _artifact_bundle(content: ArtifactContent) -> ArtifactContentBundle:
    sections = _content_sections(content)
    return ArtifactContentBundle(
        content=EvidenceBackedContent(
            title=content.title,
            purpose=content.purpose,
            sections=sections,
            citations=_citations(content.citations),
            warnings=list(dict.fromkeys((*content.coverage.warnings, *content.warnings))),
        ),
        paginated=PaginatedDocumentSpec(
            title=content.title,
            subtitle=content.purpose,
            sections=sections,
            include_references=True,
            include_coverage_notes=True,
        ),
        presentation=PresentationSpec(
            title=content.title,
            subtitle=content.purpose,
            slides=_presentation_slides(sections),
            include_references_slide=True,
        ),
    )


def _content_sections(content: ArtifactContent) -> list[ContentSection]:
    claims = {claim.claim_id: claim for claim in content.claims}
    sections = [_content_section(section, claims) for section in content.sections]
    if sections:
        return sections
    return [
        ContentSection(
            title="Summary",
            blocks=[ContentBlock(kind="paragraph", text="No supported content was generated.", evidence_ids=[])],
        )
    ]


def _content_section(section: SemanticSection, claims: dict[str, SupportedClaim]) -> ContentSection:
    section_evidence_ids = _section_evidence_ids(section, claims)
    fallback_evidence_ids = section_evidence_ids or ["uncited"]
    blocks: list[ContentBlock] = []
    for paragraph in section.paragraphs:
        blocks.append(
            ContentBlock(
                kind="paragraph",
                text=_strip_citation_tokens(paragraph),
                evidence_ids=section_evidence_ids,
            )
        )
    if section.bullets:
        if section_evidence_ids:
            blocks.append(
                ContentBlock(
                    kind="bullet_list",
                    list_items=[
                        ContentListItem(text=_strip_citation_tokens(item), evidence_ids=section_evidence_ids)
                        for item in section.bullets
                    ],
                )
            )
        else:
            blocks.extend(
                ContentBlock(kind="paragraph", text=_strip_citation_tokens(item), evidence_ids=[])
                for item in section.bullets
            )
    for table in section.tables:
        blocks.append(_table_block(table, fallback_evidence_ids))
    if not blocks:
        blocks.append(ContentBlock(kind="paragraph", text="No supported content was generated.", evidence_ids=[]))
    return ContentSection(title=section.heading or "Summary", blocks=blocks)


def _table_block(table: ArtifactTable, fallback_evidence_ids: list[str]) -> ContentBlock:
    return ContentBlock(
        kind="table",
        table=ContentTable(
            headers=[field.label for field in table.fields],
            rows=[
                ContentTableRow(
                    values=[dict(row.values).get(field.name) or "Not stated" for field in table.fields],
                    evidence_ids=list(row.evidence_ids) or fallback_evidence_ids,
                )
                for row in table.rows
            ],
        ),
    )


def _presentation_slides(sections: list[ContentSection]) -> list[PresentationSlide]:
    slides: list[PresentationSlide] = []
    for section in sections:
        narrative_blocks: list[ContentBlock] = []
        table_blocks: list[ContentBlock] = []
        for block in section.blocks:
            if block.kind == "table":
                table_blocks.append(block)
            else:
                narrative_blocks.append(block)
        for chunk in _chunks(narrative_blocks, 8):
            slides.append(PresentationSlide(title=section.title, blocks=chunk))
        for block in table_blocks:
            slides.append(PresentationSlide(title=section.title, blocks=[block]))
    if slides:
        return slides
    return [
        PresentationSlide(
            title="Summary",
            blocks=[ContentBlock(kind="paragraph", text="No supported content was generated.", evidence_ids=[])],
        )
    ]


def _section_evidence_ids(section: SemanticSection, claims: dict[str, SupportedClaim]) -> list[str]:
    return list(
        dict.fromkeys(
            evidence_id
            for claim_id in section.claim_ids
            if claim_id in claims
            for evidence_id in claims[claim_id].evidence_ids
        )
    )


def _citations(citations: tuple[ArtifactCitation, ...]) -> list[JobEvidenceCitation]:
    return [
        JobEvidenceCitation(
            evidence_id=citation.evidence_id,
            doc_id=citation.doc_id,
            doc_title=citation.doc_title,
            chunk_id=citation.chunk_id,
            page_start=citation.page_start,
            page_end=citation.page_end,
        )
        for citation in citations
    ]


def _legacy_content(*, title: str, prompt: str, response: RAGResponse | None) -> ArtifactContent:
    if response is None:
        raise ValueError("artifact_content or response is required")
    citations = tuple(
        ArtifactCitation(
            evidence_id=f"legacy_{index}",
            doc_id=source.doc_id,
            doc_title=source.doc_title,
            chunk_id=source.chunk_id,
            page_start=source.page_start or source.page,
            page_end=source.page_end or source.page_start or source.page,
        )
        for index, source in enumerate(response.sources, start=1)
    )
    evidence_ids = tuple(citation.evidence_id for citation in citations)
    claim = SupportedClaim(claim_id="legacy_claim", text=response.answer, evidence_ids=evidence_ids)
    return ArtifactContent(
        title=title,
        purpose=prompt,
        sections=(SemanticSection(heading="Answer", paragraphs=(response.answer,), claim_ids=(claim.claim_id,)),),
        claims=(claim,),
        citations=citations,
        coverage=CoverageReport(
            status="partial" if citations else "none",
            evidence_count=len(citations),
            relevant_evidence_count=len(citations),
            documents_searched=len({citation.doc_id for citation in citations}),
            documents_expected=None,
            warnings=("Rendered through the legacy response adapter.",),
        ),
    )


def _strip_citation_tokens(text: str) -> str:
    return re.sub(r"\[[^\[\]\n]{1,200}:[^\[\]\n]{1,200}\]", "", text).strip()


def _chunks(values: list[T], size: int) -> list[list[T]]:
    return [values[offset : offset + size] for offset in range(0, len(values), size)]
