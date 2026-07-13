from __future__ import annotations

from rag.artifact_jobs.contracts import (
    ArtifactContentBundle,
    ContentBlock,
    ContentListItem,
    ContentSection,
    ContentTable,
    ContentTableRow,
    EvidenceBackedContent,
    PaginatedDocumentSpec,
    PresentationSlide,
    PresentationSpec,
)

from generation_optimization_support import evidence_citation


def pdf_showcase_bundle() -> ArtifactContentBundle:
    section = ContentSection(
        title="Highlights",
        blocks=[
            ContentBlock(
                kind="paragraph",
                text="Evidence fact.",
                evidence_ids=["E1"],
            ),
            ContentBlock(
                kind="bullet_list",
                list_items=[
                    ContentListItem(
                        text="First cited point.",
                        evidence_ids=["E1"],
                    ),
                    ContentListItem(
                        text="Second cited point.",
                        evidence_ids=["E1"],
                    ),
                ],
            ),
            ContentBlock(
                kind="callout",
                text="Prioritize cited conclusions over unsupported details.",
                evidence_ids=["E1"],
            ),
            ContentBlock(
                kind="table",
                table=ContentTable(
                    headers=["Document", "Topic", "Outcome", "Status", "Owner"],
                    rows=[
                        ContentTableRow(
                            values=[
                                "FIR_02_kidnapping.pdf",
                                "Kidnapping",
                                "Evidence reviewed",
                                "Open",
                                "Investigator",
                            ],
                            evidence_ids=["E1"],
                        )
                    ],
                ),
            ),
        ],
    )
    return ArtifactContentBundle(
        content=EvidenceBackedContent(
            title="PDF layout showcase",
            purpose="Exercise PDF layout primitives.",
            sections=[section],
            citations=[evidence_citation()],
        ),
        paginated=PaginatedDocumentSpec(
            title="PDF layout showcase",
            subtitle="Evidence-backed output",
            sections=[section],
            include_references=True,
        ),
        presentation=PresentationSpec(
            title="PDF layout showcase",
            slides=[PresentationSlide(title="Highlights", blocks=section.blocks)],
        ),
    )


def timeline_bundle() -> ArtifactContentBundle:
    section = ContentSection(
        title="Timeline",
        blocks=[
            ContentBlock(
                kind="numbered_list",
                list_items=[
                    ContentListItem(
                        text="Complaint registered at 21:30.",
                        evidence_ids=["E1"],
                    ),
                    ContentListItem(
                        text="Recovered property logged after midnight.",
                        evidence_ids=["E1"],
                    ),
                ],
            ),
            ContentBlock(
                kind="table",
                table=ContentTable(
                    headers=["Time", "Event"],
                    rows=[
                        ContentTableRow(
                            values=["21:30", "Complaint registered."],
                            evidence_ids=["E1"],
                        ),
                        ContentTableRow(
                            values=["00:25", "Medical note completed."],
                            evidence_ids=["E1"],
                        ),
                    ],
                ),
            ),
        ],
    )
    return ArtifactContentBundle(
        content=EvidenceBackedContent(
            title="Incident timeline",
            purpose="Build a chronological timeline of events.",
            sections=[section],
            citations=[evidence_citation()],
        ),
        paginated=PaginatedDocumentSpec(
            title="Incident timeline",
            sections=[section],
        ),
        presentation=PresentationSpec(
            title="Incident timeline",
            slides=[PresentationSlide(title="Timeline", blocks=section.blocks)],
        ),
    )


def operator_guide_bundle() -> ArtifactContentBundle:
    section = ContentSection(
        title="SOP checklist",
        blocks=[
            ContentBlock(
                kind="numbered_list",
                list_items=[
                    ContentListItem(
                        text="Review authorized source records.",
                        evidence_ids=["E1"],
                    ),
                    ContentListItem(
                        text="Confirm each generated claim has a citation.",
                        evidence_ids=["E1"],
                    ),
                ],
            )
        ],
    )
    return ArtifactContentBundle(
        content=EvidenceBackedContent(
            title="Artifact generation SOP",
            purpose="Provide a workflow checklist for artifact review.",
            sections=[section],
            citations=[evidence_citation()],
        ),
        paginated=PaginatedDocumentSpec(
            title="Artifact generation SOP",
            sections=[section],
        ),
        presentation=PresentationSpec(
            title="Artifact generation SOP",
            slides=[PresentationSlide(title="SOP checklist", blocks=section.blocks)],
        ),
    )


def standard_layout_bundle() -> ArtifactContentBundle:
    section = ContentSection(
        title="Overview",
        blocks=[
            ContentBlock(
                kind="paragraph",
                text=(
                    "A neutral layout showcase should remain on the standard report "
                    "profile."
                ),
                evidence_ids=["E1"],
            )
        ],
    )
    return ArtifactContentBundle(
        content=EvidenceBackedContent(
            title="Layout showcase",
            purpose="Summarize available materials in a neutral document.",
            sections=[section],
            citations=[evidence_citation()],
        ),
        paginated=PaginatedDocumentSpec(
            title="Layout showcase",
            sections=[section],
        ),
        presentation=PresentationSpec(
            title="Layout showcase",
            slides=[PresentationSlide(title="Overview", blocks=section.blocks)],
        ),
    )


def dynamic_table_bundle(*, row_count: int) -> ArtifactContentBundle:
    long_event = (
        "Event {index}: custody metadata reconciliation requires a careful comparison "
        "of intake notes, handoff records, and ledger timestamps before this row can "
        "be treated as a final conclusion. The reviewer should keep the source caveat "
        "visible, preserve the operational sequence, and avoid collapsing unresolved "
        "chain-of-custody gaps into a confirmed finding."
    )
    rows = [
        ContentTableRow(
            values=[
                f"{8 + index:02d}:15",
                (
                    long_event.format(index=index)
                    if index == 1 or row_count > 2
                    else f"Event {index}: short verified update."
                ),
                "Needs timestamp reconciliation" if index == 1 else "Verified",
            ],
            evidence_ids=["E1"],
        )
        for index in range(1, row_count + 1)
    ]
    section = ContentSection(
        title="Timeline",
        blocks=[
            ContentBlock(
                kind="table",
                table=ContentTable(
                    headers=["Time", "Event Description", "Status"],
                    rows=rows,
                ),
            )
        ],
    )
    return ArtifactContentBundle(
        content=EvidenceBackedContent(
            title="Incident timeline",
            purpose="Build a chronological timeline of events.",
            sections=[section],
            citations=[evidence_citation()],
        ),
        paginated=PaginatedDocumentSpec(
            title="Incident timeline",
            sections=[section],
        ),
        presentation=PresentationSpec(
            title="Incident timeline",
            slides=[PresentationSlide(title="Timeline", blocks=section.blocks)],
        ),
    )


def large_list_bundle(*, item_count: int) -> ArtifactContentBundle:
    section = ContentSection(
        title="Facts",
        blocks=[
            ContentBlock(
                kind="bullet_list",
                list_items=[
                    ContentListItem(
                        text=f"Item {index} evidence fact.",
                        evidence_ids=["E1"],
                    )
                    for index in range(1, item_count + 1)
                ],
            )
        ],
    )
    content = EvidenceBackedContent(
        title="FIR summary",
        purpose="Summarize alleged crimes.",
        sections=[section],
        citations=[evidence_citation()],
    )
    return ArtifactContentBundle(
        content=content,
        paginated=PaginatedDocumentSpec(title="FIR summary", sections=[section]),
        presentation=PresentationSpec(
            title="FIR summary",
            slides=[PresentationSlide(title="Facts", blocks=section.blocks)],
        ),
    )


def presentation_text(presentation) -> str:
    return "\n".join(
        shape.text
        for slide in presentation.slides
        for shape in slide.shapes
        if hasattr(shape, "text")
    )


def slide_text(slide) -> str:
    return "\n".join(shape.text for shape in slide.shapes if hasattr(shape, "text"))


def presentation_tables(presentation):
    return [
        shape.table
        for slide in presentation.slides
        for shape in slide.shapes
        if getattr(shape, "has_table", False)
    ]


def presentation_table_text(presentation) -> str:
    return "\n".join(
        cell.text
        for table in presentation_tables(presentation)
        for row in table.rows
        for cell in row.cells
    )


def slide_background_hex(slide) -> str:
    return str(slide.background.fill.fore_color.rgb)
