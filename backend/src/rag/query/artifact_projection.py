"""Format-specific layout projections over shared semantic artifact content."""

from __future__ import annotations

from ..schemas.query import ArtifactFormat
from .artifact_models import ArtifactContent, FormatProjection, ProjectionUnit


def project_artifact(content: ArtifactContent, artifact_format: ArtifactFormat) -> FormatProjection:
    if artifact_format == "pptx":
        return _presentation_projection(content)
    return _paginated_projection(content, artifact_format)


def _paginated_projection(content: ArtifactContent, artifact_format: ArtifactFormat) -> FormatProjection:
    units: list[ProjectionUnit] = []
    for section in content.sections:
        if section.paragraphs or section.bullets:
            units.append(
                ProjectionUnit(
                    kind="section",
                    title=section.heading,
                    body=(*section.paragraphs, *section.bullets),
                    citation_ids=_section_citation_ids(content, section.claim_ids),
                )
            )
        for table in section.tables:
            units.append(
                ProjectionUnit(
                    kind="table",
                    title=table.title or section.heading,
                    table=table,
                    citation_ids=tuple(
                        dict.fromkeys(evidence_id for row in table.rows for evidence_id in row.evidence_ids)
                    ),
                )
            )
    return FormatProjection(
        format=artifact_format,
        title=content.title,
        units=tuple(units),
        rendering_options={"include_references": True, "include_coverage": True},
    )


def _presentation_projection(content: ArtifactContent) -> FormatProjection:
    units: list[ProjectionUnit] = [
        ProjectionUnit(kind="title", title=content.title, body=(content.purpose,))
    ]
    for section in content.sections:
        body_items = [*section.paragraphs, *section.bullets]
        for offset in range(0, len(body_items), 5):
            units.append(
                ProjectionUnit(
                    kind="slide",
                    title=section.heading,
                    body=tuple(body_items[offset : offset + 5]),
                    citation_ids=_section_citation_ids(content, section.claim_ids),
                )
            )
        for table in section.tables:
            rows_per_slide = 8
            for offset in range(0, len(table.rows), rows_per_slide):
                units.append(
                    ProjectionUnit(
                        kind="table_slide",
                        title=table.title or section.heading,
                        table=type(table)(
                            title=table.title,
                            fields=table.fields,
                            rows=table.rows[offset : offset + rows_per_slide],
                        ),
                        citation_ids=tuple(
                            dict.fromkeys(
                                evidence_id
                                for row in table.rows[offset : offset + rows_per_slide]
                                for evidence_id in row.evidence_ids
                            )
                        ),
                    )
                )
    return FormatProjection(
        format="pptx",
        title=content.title,
        units=tuple(units),
        rendering_options={"include_sources_slide": True},
    )


def _section_citation_ids(content: ArtifactContent, claim_ids: tuple[str, ...]) -> tuple[str, ...]:
    claims = {claim.claim_id: claim for claim in content.claims}
    return tuple(
        dict.fromkeys(
            evidence_id
            for claim_id in claim_ids
            if claim_id in claims
            for evidence_id in claims[claim_id].evidence_ids
        )
    )
