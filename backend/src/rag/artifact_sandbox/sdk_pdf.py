"""PDF layout primitives for sandbox build programs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from rag.artifact_jobs.contracts import EvidenceCitation

from .sdk_shared import citation_map, item_parts, reference_line, row_parts, source_summary, validated_output_path


PDF_BRAND = "#173B3F"
PDF_ACCENT = "#C8A24A"
PDF_TEXT = "#253538"
PDF_MUTED = "#53676A"
PDF_RULE = "#D7E1E2"
PDF_ROW = "#F6FAFA"
PDF_CALLOUT = "#F8F1E3"
PDF_WIDE_TABLE_COLUMNS = 5


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
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, Spacer

        self._path = validated_output_path(path)
        self._citations = citation_map(citations)
        self._all_citations = list(citations)
        self._colors = colors
        self._portrait_width = A4[0] - 32 * mm
        self._landscape_width = A4[1] - 32 * mm
        self._wide = False
        self._width_bound_tables: list[Any] = []
        self._styles = getSampleStyleSheet()
        self._style_defaults()
        self._styles.add(ParagraphStyle(name="Meta", parent=self._styles["Normal"], alignment=TA_CENTER, textColor=colors.HexColor(PDF_MUTED), fontSize=8.5, leading=11))
        self._styles.add(ParagraphStyle(name="Callout", parent=self._styles["BodyText"], textColor=colors.HexColor(PDF_TEXT), fontSize=9.2, leading=12.5))
        self._styles.add(ParagraphStyle(name="Reference", parent=self._styles["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor(PDF_MUTED)))
        self._styles.add(ParagraphStyle(name="TableCell", parent=self._styles["BodyText"], fontSize=7.7, leading=9.5, wordWrap="CJK"))
        self._styles.add(ParagraphStyle(name="TableHeader", parent=self._styles["TableCell"], textColor=colors.white, fontName="Helvetica-Bold", leading=9.8))
        self._story: list[Any] = [Paragraph(escape(title), self._styles["Title"])]
        if subtitle:
            self._story.append(Paragraph(escape(subtitle), self._styles["Meta"]))
        self._story.extend([
            Paragraph(escape(f"Generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}"), self._styles["Meta"]),
            Spacer(1, 14),
        ])

    def add_heading(self, text: str, *, level: int = 1) -> None:
        from reportlab.platypus import Paragraph

        self._story.append(Paragraph(escape(str(text)), self._styles[f"Heading{max(1, min(level, 3))}"]))

    def add_paragraph(self, text: str, *, evidence_ids: list[str] | None = None) -> None:
        from reportlab.platypus import Paragraph, Spacer

        self._story.extend([
            Paragraph(self._with_sources_markup(str(text), evidence_ids), self._styles["BodyText"]),
            Spacer(1, 6),
        ])

    def add_bullet_list(self, items: list[Any], *, evidence_ids: list[str] | None = None) -> None:
        self._add_list(items, bullet_type="bullet", evidence_ids=evidence_ids)

    def add_numbered_list(self, items: list[Any], *, evidence_ids: list[str] | None = None) -> None:
        self._add_list(items, bullet_type="1", evidence_ids=evidence_ids)

    def add_callout(self, text: str, *, evidence_ids: list[str] | None = None) -> None:
        from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

        callout = Paragraph(f"<b>Important</b><br/>{self._with_sources_markup(str(text), evidence_ids)}", self._styles["Callout"])
        table = Table([[callout]], colWidths=[self._available_width()], hAlign="LEFT")
        self._width_bound_tables.append(table)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), self._colors.HexColor(PDF_CALLOUT)),
            ("BOX", (0, 0), (-1, -1), 0.4, self._colors.HexColor("#E3D4B3")),
            ("LINEBEFORE", (0, 0), (0, -1), 3, self._colors.HexColor(PDF_ACCENT)),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        self._story.extend([table, Spacer(1, 8)])

    def add_table(self, headers: list[str], rows: list[Any], *, evidence_ids: list[str] | None = None) -> None:
        from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

        was_wide = self._wide
        self._wide = self._wide or len(headers) >= PDF_WIDE_TABLE_COLUMNS
        if self._wide and not was_wide:
            self._resize_width_bound_tables()
        table_rows = [[Paragraph(escape(str(header)), self._styles["TableHeader"]) for header in [*headers, "Source"]]]
        for row in rows:
            values, ids = row_parts(row, evidence_ids)
            body_values = [*values[: len(headers)], *([""] * max(0, len(headers) - len(values)))]
            table_rows.append([
                Paragraph(escape(value), self._styles["TableCell"])
                for value in [*body_values, self._source_label(ids)]
            ])
        table = Table(
            table_rows,
            colWidths=self._col_widths(len(headers) + 1),
            repeatRows=1,
            hAlign="LEFT",
            splitByRow=1,
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), self._colors.HexColor(PDF_BRAND)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [self._colors.white, self._colors.HexColor(PDF_ROW)]),
            ("TEXTCOLOR", (0, 0), (-1, 0), self._colors.white),
            ("LINEBELOW", (0, 0), (-1, 0), 0.9, self._colors.HexColor(PDF_ACCENT)),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, self._colors.HexColor(PDF_RULE)),
            ("BOX", (0, 0), (-1, -1), 0.4, self._colors.HexColor("#AAB7B8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        self._story.extend([table, Spacer(1, 9)])

    def add_page_break(self) -> None:
        from reportlab.platypus import PageBreak

        self._story.append(PageBreak())

    def add_references(self, *_, **__) -> None:
        self.add_page_break()
        self.add_heading("References")
        for index, citation in enumerate(self._all_citations, start=1):
            from reportlab.platypus import Paragraph, Spacer

            self._story.extend([
                Paragraph(escape(reference_line(index, citation)), self._styles["Reference"]),
                Spacer(1, 3),
            ])

    def finalize(self) -> None:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate

        document = SimpleDocTemplate(
            str(self._path),
            pagesize=landscape(A4) if self._wide else A4,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=22 * mm,
            bottomMargin=17 * mm,
        )
        self._resize_width_bound_tables()
        document.build(self._story, onFirstPage=self._page_chrome, onLaterPages=self._page_chrome)

    def _col_widths(self, columns: int) -> list[float]:
        available_width = self._available_width()
        if columns <= 1:
            return [available_width]
        source_width = min(available_width * 0.22, 95)
        body_width = (available_width - source_width) / (columns - 1)
        return [body_width] * (columns - 1) + [source_width]

    def _style_defaults(self) -> None:
        self._styles["Normal"].fontName = "Helvetica"
        self._styles["Normal"].fontSize = 9.6
        self._styles["Normal"].leading = 13
        self._styles["Normal"].textColor = self._colors.HexColor(PDF_TEXT)
        self._styles["BodyText"].fontName = "Helvetica"
        self._styles["BodyText"].fontSize = 9.6
        self._styles["BodyText"].leading = 13
        self._styles["BodyText"].spaceAfter = 2
        self._styles["BodyText"].textColor = self._colors.HexColor(PDF_TEXT)
        self._styles["Title"].fontName = "Helvetica-Bold"
        self._styles["Title"].fontSize = 22
        self._styles["Title"].leading = 26
        self._styles["Title"].spaceAfter = 7
        self._styles["Title"].textColor = self._colors.HexColor(PDF_BRAND)
        for name, size, leading, before, after in (
            ("Heading1", 14, 17, 12, 7),
            ("Heading2", 11.5, 14, 9, 5),
            ("Heading3", 10.3, 12.5, 7, 4),
        ):
            style = self._styles[name]
            style.fontName = "Helvetica-Bold"
            style.fontSize = size
            style.leading = leading
            style.spaceBefore = before
            style.spaceAfter = after
            style.keepWithNext = 1
            style.textColor = self._colors.HexColor(PDF_BRAND)

    def _add_list(self, items: list[Any], *, bullet_type: str, evidence_ids: list[str] | None) -> None:
        from reportlab.platypus import ListFlowable, ListItem, Paragraph, Spacer

        list_items = []
        for item in items:
            text, ids = item_parts(item, evidence_ids)
            if not text:
                continue
            list_items.append(ListItem(Paragraph(self._with_sources_markup(text, ids), self._styles["BodyText"]), leftIndent=0))
        if list_items:
            self._story.extend([
                ListFlowable(list_items, bulletType=bullet_type, leftIndent=16, bulletIndent=4),
                Spacer(1, 6),
            ])

    def _with_sources_markup(self, text: str, evidence_ids: list[str] | None) -> str:
        summary = source_summary(evidence_ids, self._citations)
        if not summary:
            return escape(text)
        return f"{escape(text)} <font color=\"{PDF_MUTED}\" size=\"8\">({escape(summary)})</font>"

    def _source_label(self, evidence_ids: list[str] | None) -> str:
        return source_summary(evidence_ids, self._citations).removeprefix("Sources: ")

    def _available_width(self) -> float:
        return self._landscape_width if self._wide else self._portrait_width

    def _resize_width_bound_tables(self) -> None:
        width = self._available_width()
        for table in self._width_bound_tables:
            table._argW = [width]
            table._colWidths = [width]

    def _page_chrome(self, canvas, document) -> None:
        from reportlab.lib.units import mm

        canvas.saveState()
        width, height = document.pagesize
        left = document.leftMargin
        right = width - document.rightMargin
        canvas.setStrokeColor(self._colors.HexColor(PDF_RULE))
        canvas.setLineWidth(0.6)
        canvas.line(left, height - 16 * mm, right, height - 16 * mm)
        canvas.line(left, 12 * mm, right, 12 * mm)
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.setFillColor(self._colors.HexColor(PDF_BRAND))
        canvas.drawString(left, height - 12.4 * mm, "Faham AI")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(self._colors.HexColor(PDF_MUTED))
        canvas.drawCentredString(width / 2, 8 * mm, "Evidence-backed artifact")
        canvas.drawRightString(right, 8 * mm, f"Page {document.page}")
        canvas.restoreState()
