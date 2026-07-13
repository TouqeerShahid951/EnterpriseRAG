"""PDF rendering for parsed manual blocks."""

from __future__ import annotations

from pathlib import Path
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    LongTable,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    TableStyle,
)


def build_pdf(blocks: list[dict], path: Path, running_label: str) -> None:
    styles = pdf_styles()
    story = []
    title_seen = False
    for block in blocks:
        kind = block["type"]
        if kind == "heading":
            level = block["level"]
            if level == 1 and not title_seen:
                title_seen = True
                story.append(Paragraph(pdf_inline(block["text"]), styles["title"]))
            else:
                story.append(Paragraph(pdf_inline(block["text"]), styles[f"h{level}"]))
        elif kind == "paragraph":
            story.append(Paragraph(pdf_inline(block["text"]), styles["body"]))
        elif kind == "bullet":
            story.append(Paragraph(f"- {pdf_inline(block['text'])}", styles["bullet"]))
        elif kind == "number":
            story.append(Paragraph(f"{block['number']}. {pdf_inline(block['text'])}", styles["number"]))
        elif kind == "code":
            story.append(Preformatted(block["text"], styles["code"]))
            story.append(Spacer(1, 6))
        elif kind == "table":
            story.append(pdf_table(block["rows"], styles))
            story.append(Spacer(1, 8))

    frame = Frame(inch, inch, 6.5 * inch, 9 * inch, id="normal")
    doc = BaseDocTemplate(str(path), pagesize=letter, leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch)
    doc.addPageTemplates([PageTemplate(id="manual", frames=[frame], onPage=lambda canvas, document: pdf_page(canvas, document, running_label))])
    doc.build(story)


def pdf_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("ManualTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=23, leading=27, textColor=colors.HexColor("#1F4D78"), spaceAfter=14, alignment=TA_LEFT),
        "h1": ParagraphStyle("ManualH1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#2E74B5"), spaceBefore=14, spaceAfter=8),
        "h2": ParagraphStyle("ManualH2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=colors.HexColor("#2E74B5"), spaceBefore=11, spaceAfter=6),
        "h3": ParagraphStyle("ManualH3", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=colors.HexColor("#1F4D78"), spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("ManualBody", parent=base["BodyText"], fontName="Helvetica", fontSize=10.2, leading=13.2, textColor=colors.HexColor("#1C2530"), spaceAfter=6),
        "bullet": ParagraphStyle("ManualBullet", parent=base["BodyText"], fontName="Helvetica", fontSize=10.2, leading=13.2, leftIndent=16, firstLineIndent=-9, textColor=colors.HexColor("#1C2530"), spaceAfter=3),
        "number": ParagraphStyle("ManualNumber", parent=base["BodyText"], fontName="Helvetica", fontSize=10.2, leading=13.2, leftIndent=18, firstLineIndent=-14, textColor=colors.HexColor("#1C2530"), spaceAfter=3),
        "code": ParagraphStyle("ManualCode", parent=base["Code"], fontName="Courier", fontSize=8.3, leading=10.2, leftIndent=14, rightIndent=10, backColor=colors.HexColor("#F2F4F7"), textColor=colors.HexColor("#1E2D3C"), spaceBefore=3, spaceAfter=3),
        "table": ParagraphStyle("ManualTable", parent=base["BodyText"], fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor("#1C2530")),
        "table_header": ParagraphStyle("ManualTableHeader", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.HexColor("#1C2530")),
    }


def pdf_table(rows: list[list[str]], styles: dict[str, ParagraphStyle]) -> LongTable:
    col_count = len(rows[0])
    widths = pdf_widths_for_columns(col_count)
    table_data = []
    for row_index, row in enumerate(rows):
        style = styles["table_header"] if row_index == 0 else styles["table"]
        table_data.append([Paragraph(pdf_inline(cell), style) for cell in row])
    table = LongTable(table_data, colWidths=widths, repeatRows=1, splitByRow=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF5")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C2CC")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def pdf_widths_for_columns(col_count: int) -> list[float]:
    if col_count == 2:
        return [1.85 * inch, 4.65 * inch]
    if col_count == 3:
        return [1.45 * inch, 2.25 * inch, 2.8 * inch]
    if col_count == 4:
        return [1.25 * inch, 1.7 * inch, 1.7 * inch, 1.85 * inch]
    return [6.5 * inch / col_count] * col_count


def pdf_inline(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = escape(text)
    text = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return text


def pdf_page(canvas, doc, running_label: str) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#5B6770"))
    canvas.drawString(inch, 10.35 * inch, running_label)
    canvas.drawRightString(7.5 * inch, 0.55 * inch, f"Page {doc.page}")
    canvas.restoreState()
