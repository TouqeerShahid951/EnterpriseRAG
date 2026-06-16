"""PDF layout primitives for sandbox build programs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from rag.artifact_jobs.contracts import EvidenceCitation

from .sdk_shared import citation_map, item_parts, reference_line, row_parts, validated_output_path, with_sources


class PdfArtifact:
    def __init__(
        self,
        *,
        path: str,
        title: str,
        subtitle: str | None,
        generated_at: datetime,
        citations: list[EvidenceCitation],
    ) -> None:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import Paragraph, Spacer

        self._path = validated_output_path(path)
        self._citations = citation_map(citations)
        self._all_citations = list(citations)
        self._colors = colors
        self._styles = getSampleStyleSheet()
        self._styles.add(ParagraphStyle(name="Meta", parent=self._styles["Normal"], alignment=TA_CENTER, textColor=colors.HexColor("#53676A")))
        self._story: list[Any] = [
            Paragraph(escape(title), self._styles["Title"]),
            Paragraph(escape(subtitle or ""), self._styles["Meta"]),
            Paragraph(escape(f"Generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}"), self._styles["Meta"]),
            Spacer(1, 12),
        ]

    def add_heading(self, text: str, *, level: int = 1) -> None:
        from reportlab.platypus import Paragraph

        self._story.append(Paragraph(escape(str(text)), self._styles[f"Heading{max(1, min(level, 3))}"]))

    def add_paragraph(self, text: str, *, evidence_ids: list[str] | None = None) -> None:
        from reportlab.platypus import Paragraph, Spacer

        self._story.extend([
            Paragraph(escape(with_sources(str(text), evidence_ids, self._citations)), self._styles["BodyText"]),
            Spacer(1, 5),
        ])

    def add_bullet_list(self, items: list[Any], *, evidence_ids: list[str] | None = None) -> None:
        for item in items:
            text, ids = item_parts(item, evidence_ids)
            self.add_paragraph("- " + text, evidence_ids=ids)

    def add_numbered_list(self, items: list[Any], *, evidence_ids: list[str] | None = None) -> None:
        for index, item in enumerate(items, start=1):
            text, ids = item_parts(item, evidence_ids)
            self.add_paragraph(f"{index}. {text}", evidence_ids=ids)

    def add_callout(self, text: str, *, evidence_ids: list[str] | None = None) -> None:
        self.add_paragraph("Important: " + str(text), evidence_ids=evidence_ids)

    def add_table(self, headers: list[str], rows: list[Any], *, evidence_ids: list[str] | None = None) -> None:
        from reportlab.platypus import Table, TableStyle

        table_rows = [[*headers, "Source"]]
        for row in rows:
            values, ids = row_parts(row, evidence_ids)
            table_rows.append([*values[: len(headers)], with_sources("", ids, self._citations).strip(" ()")])
        table = Table(table_rows, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), self._colors.HexColor("#173B3F")),
            ("TEXTCOLOR", (0, 0), (-1, 0), self._colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, self._colors.HexColor("#AAB7B8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        self._story.append(table)

    def add_page_break(self) -> None:
        from reportlab.platypus import PageBreak

        self._story.append(PageBreak())

    def add_references(self, *_, **__) -> None:
        self.add_page_break()
        self.add_heading("References")
        for index, citation in enumerate(self._all_citations, start=1):
            self.add_paragraph(reference_line(index, citation))

    def finalize(self) -> None:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate

        document = SimpleDocTemplate(
            str(self._path),
            pagesize=A4,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=15 * mm,
            bottomMargin=16 * mm,
        )
        document.build(self._story)
