"""Reusable PDF styling and layout components for the walkthrough."""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import BaseDocTemplate, Paragraph, Table, TableStyle


class NumberedPdf(BaseDocTemplate):
    pass


def draw_pdf_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#5B6770"))
    canvas.drawString(doc.leftMargin, 0.45 * inch, "Prudentia AI End User Walkthrough")
    canvas.drawRightString(letter[0] - doc.rightMargin, 0.45 * inch, f"Page {doc.page}")
    canvas.restoreState()


def pdf_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("GuideTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=27, leading=32, textColor=colors.HexColor("#1F4D78"), alignment=TA_LEFT, spaceAfter=8),
        "subtitle": ParagraphStyle("GuideSubtitle", parent=base["Normal"], fontName="Helvetica", fontSize=12.5, leading=16, textColor=colors.HexColor("#5B6770"), spaceAfter=18),
        "h1": ParagraphStyle("GuideH1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#2E74B5"), spaceBefore=14, spaceAfter=7),
        "h2": ParagraphStyle("GuideH2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=colors.HexColor("#2E74B5"), spaceBefore=10, spaceAfter=5),
        "body": ParagraphStyle("GuideBody", parent=base["BodyText"], fontName="Helvetica", fontSize=10, leading=13, textColor=colors.HexColor("#1C2530"), spaceAfter=6),
        "small": ParagraphStyle("GuideSmall", parent=base["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#5B6770"), spaceAfter=3),
        "bullet": ParagraphStyle("GuideBullet", parent=base["BodyText"], fontName="Helvetica", fontSize=10, leading=13, leftIndent=16, firstLineIndent=-9, textColor=colors.HexColor("#1C2530"), spaceAfter=4),
        "note": ParagraphStyle("GuideNote", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=9.8, leading=12.5, textColor=colors.HexColor("#1C2530"), spaceAfter=0),
        "table": ParagraphStyle("GuideTable", parent=base["BodyText"], fontName="Helvetica", fontSize=8.5, leading=10.5, textColor=colors.HexColor("#1C2530")),
        "table_header": ParagraphStyle("GuideTableHeader", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=8.5, leading=10.5, textColor=colors.HexColor("#1C2530")),
    }

def pdf_bullets(styles: dict[str, ParagraphStyle], items: list[str]) -> list:
    return [Paragraph(f"- {escape_pdf_text(item)}", styles["bullet"]) for item in items]


def pdf_numbered_items(styles: dict[str, ParagraphStyle], items: list[str]) -> list:
    return [Paragraph(f"{idx}. {escape_pdf_text(item)}", styles["bullet"]) for idx, item in enumerate(items, start=1)]


def pdf_note(styles: dict[str, ParagraphStyle], text: str) -> Table:
    table = Table([[Paragraph(escape_pdf_text(text), styles["note"])]], colWidths=[6.5 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F6F9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DADFE6")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def pdf_table(styles: dict[str, ParagraphStyle], headers: list[str], rows: list[tuple[str, ...]], widths: list[float]) -> Table:
    data = [[Paragraph(escape_pdf_text(cell), styles["table_header"]) for cell in headers]]
    data.extend([[Paragraph(escape_pdf_text(cell), styles["table"]) for cell in row] for row in rows])
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF5")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B9C4D1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def escape_pdf_text(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
