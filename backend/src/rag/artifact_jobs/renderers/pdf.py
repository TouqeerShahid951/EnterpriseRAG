"""Render validated artifact bundles as PDF documents."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from ..contracts import ArtifactContentBundle, EvidenceCitation
from ..layout_profiles import ArtifactLayoutProfile
from .shared import _list_items, _reference_line, _source_summary


PDF_WIDE_TABLE_COLUMNS = 5


def _has_wide_pdf_table(bundle: ArtifactContentBundle) -> bool:
    return any(
        block.table is not None and len(block.table.headers) >= PDF_WIDE_TABLE_COLUMNS
        for section in bundle.paginated.sections
        for block in section.blocks
    )


def render_pdf(bundle: ArtifactContentBundle, generated_at: datetime, profile: ArtifactLayoutProfile) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    wide = _has_wide_pdf_table(bundle)
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4) if wide else A4,
        title=bundle.paginated.title,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=22 * mm,
        bottomMargin=17 * mm,
    )
    styles = getSampleStyleSheet()
    _apply_pdf_style_defaults(styles, colors, profile)
    styles.add(ParagraphStyle(name="KickerV2", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8.5, leading=10, textColor=colors.HexColor("#" + profile.accent_hex), spaceAfter=2))
    styles.add(ParagraphStyle(name="CenteredMetaV2", parent=styles["Normal"], alignment=TA_CENTER, textColor=colors.HexColor("#" + profile.muted_hex), fontSize=8.5, leading=11))
    styles.add(ParagraphStyle(name="CalloutV2", parent=styles["BodyText"], textColor=colors.HexColor("#" + profile.text_hex), fontSize=9.2, leading=12.5))
    styles.add(ParagraphStyle(name="QuoteV2", parent=styles["BodyText"], fontName="Helvetica-Oblique", textColor=colors.HexColor("#" + profile.muted_hex), leftIndent=10, rightIndent=6))
    styles.add(ParagraphStyle(name="ReferenceV2", parent=styles["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor("#" + profile.muted_hex)))
    styles.add(ParagraphStyle(name="TableCellV2", parent=styles["BodyText"], fontSize=7.7, leading=9.5, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="TableHeaderV2", parent=styles["TableCellV2"], textColor=colors.white, fontName="Helvetica-Bold", leading=9.8))
    citations = {item.evidence_id: item for item in bundle.content.citations}
    story = [Paragraph(escape(profile.kicker), styles["KickerV2"]), Paragraph(escape(bundle.paginated.title), styles["Title"])]
    if bundle.paginated.subtitle:
        story.append(Paragraph(escape(bundle.paginated.subtitle), styles["CenteredMetaV2"]))
    story.extend([
        Paragraph(escape(f"Generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}"), styles["CenteredMetaV2"]),
        Spacer(1, 14),
    ])
    if bundle.paginated.include_coverage_notes and bundle.content.warnings:
        story.append(Paragraph("Coverage Notes", styles["Heading2"]))
        story.extend(_pdf_list_flowables([(warning, []) for warning in bundle.content.warnings], citations, styles, bullet_type="bullet", profile=profile))
    for semantic_section in bundle.paginated.sections:
        story.append(Paragraph(escape(semantic_section.title), styles["Heading1"]))
        for block in semantic_section.blocks:
            story.extend(_pdf_block(block, citations, styles, colors, Table, TableStyle, Paragraph, Spacer, PageBreak, document.width, profile))
    if bundle.paginated.include_references:
        story.extend([PageBreak(), Paragraph("References", styles["Heading1"])])
        for index, citation in enumerate(bundle.content.citations, start=1):
            story.extend([
                Paragraph(escape(_reference_line(index, citation)), styles["ReferenceV2"]),
                Spacer(1, 3),
            ])
    document.build(
        story,
        onFirstPage=lambda canvas, doc: _pdf_footer(canvas, doc, profile),
        onLaterPages=lambda canvas, doc: _pdf_footer(canvas, doc, profile),
    )
    return buffer.getvalue()


def _apply_pdf_style_defaults(styles, colors, profile: ArtifactLayoutProfile) -> None:
    styles["Normal"].fontName = "Helvetica"
    styles["Normal"].fontSize = 9.6
    styles["Normal"].leading = 13
    styles["Normal"].textColor = colors.HexColor("#" + profile.text_hex)
    styles["BodyText"].fontName = "Helvetica"
    styles["BodyText"].fontSize = 9.6
    styles["BodyText"].leading = 13
    styles["BodyText"].spaceAfter = 2
    styles["BodyText"].textColor = colors.HexColor("#" + profile.text_hex)
    styles["Title"].fontName = "Helvetica-Bold"
    styles["Title"].fontSize = 22
    styles["Title"].leading = 26
    styles["Title"].spaceAfter = 7
    styles["Title"].textColor = colors.HexColor("#" + profile.brand_hex)
    for name, size, leading, before, after in (
        ("Heading1", 14, 17, 12, 7),
        ("Heading2", 11.5, 14, 9, 5),
        ("Heading3", 10.3, 12.5, 7, 4),
    ):
        style = styles[name]
        style.fontName = "Helvetica-Bold"
        style.fontSize = size
        style.leading = leading
        style.spaceBefore = before
        style.spaceAfter = after
        style.keepWithNext = 1
        style.textColor = colors.HexColor("#" + profile.brand_hex)


def _pdf_block(block, citations, styles, colors, table_cls, table_style_cls, paragraph_cls, spacer_cls, page_break_cls, available_width, profile: ArtifactLayoutProfile):
    if block.kind in {"page_break", "section_break"}:
        return [page_break_cls()]
    if block.kind == "heading":
        return [paragraph_cls(escape(block.text or ""), styles[f"Heading{min(block.level + 1, 3)}"])]
    if block.kind == "callout":
        return _pdf_callout_flowables(block.text or "", block.evidence_ids, citations, styles, colors, table_cls, table_style_cls, paragraph_cls, spacer_cls, available_width, profile)
    if block.kind in {"paragraph", "quotation"}:
        style = styles["QuoteV2"] if block.kind == "quotation" else styles["BodyText"]
        return [
            paragraph_cls(_pdf_with_sources_markup(block.text or "", block.evidence_ids, citations, profile), style),
            spacer_cls(1, 6),
        ]
    if block.kind in {"bullet_list", "numbered_list"}:
        bullet_type = "1" if block.kind == "numbered_list" else "bullet"
        return _pdf_list_flowables(_list_items(block), citations, styles, bullet_type=bullet_type, profile=profile)
    if block.kind == "key_value":
        rows = [["Field", "Value", "Source"]] + [
            [entry.key, entry.value, _source_label(entry.evidence_ids, citations)]
            for entry in block.entries
        ]
        return [_styled_pdf_table(rows, colors, table_cls, table_style_cls, styles, available_width, profile), spacer_cls(1, 9)]
    if block.kind == "table" and block.table is not None:
        rows = [[*block.table.headers, "Source"]] + [
            [*row.values, _source_label(row.evidence_ids, citations)]
            for row in block.table.rows
        ]
        return [_styled_pdf_table(rows, colors, table_cls, table_style_cls, styles, available_width, profile), spacer_cls(1, 9)]
    return []


def _pdf_callout_flowables(text, evidence_ids, citations, styles, colors, table_cls, table_style_cls, paragraph_cls, spacer_cls, available_width, profile: ArtifactLayoutProfile):
    callout = paragraph_cls(f"<b>Important</b><br/>{_pdf_with_sources_markup(text, evidence_ids, citations, profile)}", styles["CalloutV2"])
    table = table_cls([[callout]], colWidths=[available_width], hAlign="LEFT")
    table.setStyle(table_style_cls([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#" + profile.callout_hex)),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#E3D4B3")),
        ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor("#" + profile.accent_hex)),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return [table, spacer_cls(1, 8)]


def _pdf_list_flowables(items: list[tuple[str, list[str]]], citations, styles, *, bullet_type: str, profile: ArtifactLayoutProfile):
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, Spacer

    list_items = [
        ListItem(Paragraph(_pdf_with_sources_markup(item_text, evidence_ids, citations, profile), styles["BodyText"]), leftIndent=0)
        for item_text, evidence_ids in items
        if item_text
    ]
    if not list_items:
        return []
    return [
        ListFlowable(list_items, bulletType=bullet_type, leftIndent=16, bulletIndent=4),
        Spacer(1, 6),
    ]


def _pdf_with_sources_markup(
    text: str,
    evidence_ids: list[str],
    citations: dict[str, EvidenceCitation],
    profile: ArtifactLayoutProfile,
) -> str:
    summary = _source_summary(evidence_ids, citations)
    if not summary:
        return escape(text)
    return f"{escape(text)} <font color=\"#{profile.muted_hex}\" size=\"8\">({escape(summary)})</font>"


def _source_label(evidence_ids: list[str], citations: dict[str, EvidenceCitation]) -> str:
    return _source_summary(evidence_ids, citations).removeprefix("Sources: ")


def _styled_pdf_table(rows, colors, table_cls, table_style_cls, styles, available_width, profile: ArtifactLayoutProfile):
    from reportlab.platypus import Paragraph

    normalized = _normalized_table_rows(rows)
    table_rows = [
        [
            Paragraph(escape(str(cell)), styles["TableHeaderV2" if row_index == 0 else "TableCellV2"])
            for cell in row
        ]
        for row_index, row in enumerate(normalized)
    ]
    table = table_cls(
        table_rows,
        colWidths=_pdf_col_widths(normalized, available_width),
        repeatRows=1,
        hAlign="LEFT",
        splitByRow=1,
    )
    table.setStyle(table_style_cls([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + profile.brand_hex)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#" + profile.row_hex)]),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("LINEBELOW", (0, 0), (-1, 0), 0.9, colors.HexColor("#" + profile.accent_hex)),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#" + profile.rule_hex)),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#AAB7B8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _normalized_table_rows(rows) -> list[list[str]]:
    width = max((len(row) for row in rows), default=1)
    return [[str(cell) for cell in row] + [""] * (width - len(row)) for row in rows]


def _pdf_col_widths(rows: list[list[str]], available_width: float) -> list[float]:
    columns = max((len(row) for row in rows), default=1)
    if columns <= 1:
        return [available_width]
    has_source_column = rows and rows[0] and rows[0][-1].strip().lower() == "source"
    if has_source_column and columns > 2:
        source_width = min(available_width * 0.22, 95)
        body_width = (available_width - source_width) / (columns - 1)
        return [body_width] * (columns - 1) + [source_width]
    return [available_width / columns] * columns


def _pdf_footer(canvas, document, profile: ArtifactLayoutProfile) -> None:
    from reportlab.lib import colors
    from reportlab.lib.units import mm

    canvas.saveState()
    width, height = document.pagesize
    left = document.leftMargin
    right = width - document.rightMargin
    canvas.setStrokeColor(colors.HexColor("#" + profile.rule_hex))
    canvas.setLineWidth(0.6)
    canvas.line(left, height - 16 * mm, right, height - 16 * mm)
    canvas.line(left, 12 * mm, right, 12 * mm)
    canvas.setFont("Helvetica-Bold", 8.5)
    canvas.setFillColor(colors.HexColor("#" + profile.brand_hex))
    canvas.drawString(left, height - 12.4 * mm, "Prudentia AI")
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#" + profile.muted_hex))
    canvas.drawCentredString(width / 2, 8 * mm, profile.label)
    canvas.drawRightString(right, 8 * mm, f"Page {document.page}")
    canvas.restoreState()
