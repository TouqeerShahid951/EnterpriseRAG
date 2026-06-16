"""Deterministic renderers for validated v2 document specifications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile
from xml.sax.saxutils import escape

from ..schemas.query import ArtifactFormat
from .contracts import ArtifactContentBundle, ContentBlock, EvidenceCitation


CONTENT_TYPES: dict[ArtifactFormat, str] = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
}


@dataclass(frozen=True)
class RenderedV2Artifact:
    filename: str
    format: ArtifactFormat
    content_type: str
    content: bytes
    smoke_warnings: tuple[str, ...] = ()


def render_document(
    *,
    artifact_format: ArtifactFormat,
    bundle: ArtifactContentBundle,
    generated_at: datetime,
    require_libreoffice: bool,
) -> RenderedV2Artifact:
    if artifact_format == "docx":
        content = _render_docx(bundle, generated_at)
    elif artifact_format == "pdf":
        content = _render_pdf(bundle, generated_at)
    elif artifact_format == "pptx":
        content = _render_pptx(bundle, generated_at)
    else:
        raise ValueError(f"unsupported artifact format: {artifact_format}")
    _validate_package(artifact_format, content)
    warnings = _office_smoke_check(
        artifact_format=artifact_format,
        content=content,
        require_libreoffice=require_libreoffice,
    )
    return RenderedV2Artifact(
        filename=f"{_safe_filename(bundle.content.title)}.{artifact_format}",
        format=artifact_format,
        content_type=CONTENT_TYPES[artifact_format],
        content=content,
        smoke_warnings=warnings,
    )


def _render_docx(bundle: ArtifactContentBundle, generated_at: datetime) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt

    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.75)
    section.bottom_margin = Inches(0.75)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)
    document.styles["Normal"].font.name = "Aptos"
    document.styles["Normal"].font.size = Pt(10.5)
    title = document.add_heading(bundle.paginated.title, level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if bundle.paginated.subtitle:
        subtitle = document.add_paragraph(bundle.paginated.subtitle, style="Subtitle")
        subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta = document.add_paragraph(f"Generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}")
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER

    citations = {item.evidence_id: item for item in bundle.content.citations}
    if bundle.paginated.include_coverage_notes and bundle.content.warnings:
        document.add_heading("Coverage Notes", level=1)
        for warning in bundle.content.warnings:
            document.add_paragraph(warning, style="List Bullet")
    for semantic_section in bundle.paginated.sections:
        document.add_heading(semantic_section.title, level=1)
        for block in semantic_section.blocks:
            _append_docx_block(document, block, citations)
    if bundle.paginated.include_references:
        document.add_page_break()
        document.add_heading("References", level=1)
        for index, citation in enumerate(bundle.content.citations, start=1):
            document.add_paragraph(_reference_line(index, citation))
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _append_docx_block(document, block: ContentBlock, citations: dict[str, EvidenceCitation]) -> None:
    if block.kind == "heading":
        document.add_heading(block.text or "", level=block.level)
        return
    if block.kind in {"page_break", "section_break"}:
        document.add_page_break()
        return
    if block.kind == "paragraph":
        document.add_paragraph(_with_sources(block.text or "", block.evidence_ids, citations))
        return
    if block.kind in {"bullet_list", "numbered_list"}:
        style = "List Bullet" if block.kind == "bullet_list" else "List Number"
        for item_text, evidence_ids in _list_items(block):
            document.add_paragraph(_with_sources(item_text, evidence_ids, citations), style=style)
        return
    if block.kind == "quotation":
        document.add_paragraph(_with_sources(block.text or "", block.evidence_ids, citations), style="Quote")
        return
    if block.kind == "callout":
        paragraph = document.add_paragraph()
        run = paragraph.add_run(_with_sources(block.text or "", block.evidence_ids, citations))
        run.bold = True
        return
    if block.kind == "key_value":
        table = document.add_table(rows=0, cols=3)
        table.style = "Table Grid"
        for entry in block.entries:
            cells = table.add_row().cells
            cells[0].text = entry.key
            cells[1].text = entry.value
            cells[2].text = _source_summary(entry.evidence_ids, citations)
        return
    if block.kind == "table" and block.table is not None:
        table = document.add_table(rows=1, cols=len(block.table.headers) + 1)
        table.style = "Table Grid"
        for index, header in enumerate(block.table.headers):
            table.rows[0].cells[index].text = header
        table.rows[0].cells[-1].text = "Source"
        for row in block.table.rows:
            cells = table.add_row().cells
            for index, value in enumerate(row.values):
                cells[index].text = value
            cells[-1].text = _source_summary(row.evidence_ids, citations)


def _render_pdf(bundle: ArtifactContentBundle, generated_at: datetime) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    wide = any(
        block.table is not None and len(block.table.headers) > 5
        for section in bundle.paginated.sections
        for block in section.blocks
    )
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4) if wide else A4,
        title=bundle.paginated.title,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=15 * mm,
        bottomMargin=16 * mm,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CenteredMetaV2", parent=styles["Normal"], alignment=TA_CENTER, textColor=colors.HexColor("#53676A")))
    citations = {item.evidence_id: item for item in bundle.content.citations}
    story = [
        Paragraph(escape(bundle.paginated.title), styles["Title"]),
        Paragraph(escape(bundle.paginated.subtitle or ""), styles["CenteredMetaV2"]),
        Paragraph(escape(f"Generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}"), styles["CenteredMetaV2"]),
        Spacer(1, 12),
    ]
    if bundle.paginated.include_coverage_notes and bundle.content.warnings:
        story.append(Paragraph("Coverage Notes", styles["Heading2"]))
        for warning in bundle.content.warnings:
            story.append(Paragraph(escape(f"- {warning}"), styles["BodyText"]))
    for semantic_section in bundle.paginated.sections:
        story.append(Paragraph(escape(semantic_section.title), styles["Heading1"]))
        for block in semantic_section.blocks:
            story.extend(_pdf_block(block, citations, styles, colors, Table, TableStyle, KeepTogether, Paragraph, Spacer, PageBreak))
    if bundle.paginated.include_references:
        story.extend([PageBreak(), Paragraph("References", styles["Heading1"])])
        for index, citation in enumerate(bundle.content.citations, start=1):
            story.append(Paragraph(escape(_reference_line(index, citation)), styles["BodyText"]))
    document.build(story, onFirstPage=_pdf_footer, onLaterPages=_pdf_footer)
    return buffer.getvalue()


def _pdf_block(block, citations, styles, colors, table_cls, table_style_cls, keep_together, paragraph_cls, spacer_cls, page_break_cls):
    if block.kind in {"page_break", "section_break"}:
        return [page_break_cls()]
    if block.kind == "heading":
        return [paragraph_cls(escape(block.text or ""), styles[f"Heading{min(block.level + 1, 3)}"])]
    if block.kind in {"paragraph", "quotation", "callout"}:
        style = styles["Italic"] if block.kind == "quotation" else styles["BodyText"]
        return [
            paragraph_cls(escape(_with_sources(block.text or "", block.evidence_ids, citations)), style),
            spacer_cls(1, 5),
        ]
    if block.kind in {"bullet_list", "numbered_list"}:
        prefix = "- " if block.kind == "bullet_list" else ""
        return [
            paragraph_cls(
                escape(f"{index}. {item_text}" if block.kind == "numbered_list" else f"{prefix}{item_text}")
                + escape(f" {_source_summary(evidence_ids, citations)}"),
                styles["BodyText"],
            )
            for index, (item_text, evidence_ids) in enumerate(_list_items(block), start=1)
        ]
    if block.kind == "key_value":
        rows = [["Field", "Value", "Source"]] + [
            [entry.key, entry.value, _source_summary(entry.evidence_ids, citations)]
            for entry in block.entries
        ]
        return [keep_together(_styled_pdf_table(rows, colors, table_cls, table_style_cls))]
    if block.kind == "table" and block.table is not None:
        rows = [[*block.table.headers, "Source"]] + [
            [*row.values, _source_summary(row.evidence_ids, citations)]
            for row in block.table.rows
        ]
        return [_styled_pdf_table(rows, colors, table_cls, table_style_cls)]
    return []


def _styled_pdf_table(rows, colors, table_cls, table_style_cls):
    table = table_cls(rows, repeatRows=1, hAlign="LEFT")
    table.setStyle(table_style_cls([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173B3F")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#AAB7B8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _render_pptx(bundle: ArtifactContentBundle, generated_at: datetime) -> bytes:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    citations = {item.evidence_id: item for item in bundle.content.citations}
    title_slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    _set_slide_background(title_slide, RGBColor(23, 59, 63))
    _add_slide_text(title_slide, bundle.presentation.title, 0.8, 1.45, 11.7, 1.0, 30, "FFFFFF", bold=True)
    _add_slide_text(title_slide, bundle.presentation.subtitle or "", 0.85, 2.75, 10.8, 0.9, 17, "D6E4E5")
    _add_slide_text(title_slide, generated_at.date().isoformat(), 0.85, 6.6, 3.0, 0.25, 10, "AFC7C9")
    for slide_spec in bundle.presentation.slides:
        table_block = next((block for block in slide_spec.blocks if block.kind == "table" and block.table), None)
        if table_block is not None:
            chunks = _table_block_chunks(table_block, max_body_rows=9)
            for chunk_index, chunk in enumerate(chunks, start=1):
                title = slide_spec.title if len(chunks) == 1 else f"{slide_spec.title} ({chunk_index}/{len(chunks)})"
                slide = _add_base_content_slide(presentation, title)
                _add_slide_table(slide, chunk)
                _add_slide_sources(slide, _block_evidence_ids(chunk), citations)
            continue

        slide = _add_base_content_slide(presentation, slide_spec.title)
        _add_slide_bullets(slide, _slide_lines(slide_spec.blocks))
        evidence_ids = list(dict.fromkeys(
            evidence_id
            for block in slide_spec.blocks
            for evidence_id in _block_evidence_ids(block)
        ))
        _add_slide_sources(slide, evidence_ids, citations)
    if bundle.presentation.include_references_slide:
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        _set_slide_background(slide, RGBColor(247, 249, 248))
        _add_slide_text(slide, "References", 0.65, 0.3, 12.0, 0.55, 23, "173B3F", bold=True)
        _add_slide_bullets(
            slide,
            [_reference_line(index, citation) for index, citation in enumerate(bundle.content.citations[:18], start=1)],
        )
    buffer = BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def _add_base_content_slide(presentation, title: str):
    from pptx.dml.color import RGBColor

    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    _set_slide_background(slide, RGBColor(247, 249, 248))
    _add_slide_text(slide, title, 0.65, 0.3, 12.0, 0.55, 23, "173B3F", bold=True)
    return slide


def _add_slide_sources(slide, evidence_ids: list[str], citations: dict[str, EvidenceCitation]) -> None:
    source_text = _source_summary(list(dict.fromkeys(evidence_ids)), citations)
    if source_text:
        _add_slide_text(slide, source_text, 0.7, 6.82, 11.8, 0.25, 8, "53676A")


def _set_slide_background(slide, color) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def _add_slide_text(slide, text, left, top, width, height, size, color, *, bold=False) -> None:
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.word_wrap = True
    paragraph = frame.paragraphs[0]
    paragraph.text = text
    paragraph.font.name = "Aptos"
    paragraph.font.size = Pt(size)
    paragraph.font.bold = bold
    paragraph.font.color.rgb = RGBColor.from_string(color)


def _add_slide_bullets(slide, lines: list[str]) -> None:
    from pptx.util import Inches, Pt

    box = slide.shapes.add_textbox(Inches(0.9), Inches(1.15), Inches(11.5), Inches(5.35))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    for index, line in enumerate(lines[:12] or ["No supported content was generated."]):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = _compact(line, 420)
        paragraph.font.name = "Aptos"
        paragraph.font.size = Pt(16 if len(lines) <= 7 else 13)
        paragraph.space_after = Pt(8)


def _add_slide_table(slide, block: ContentBlock) -> None:
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    assert block.table is not None
    body_rows = block.table.rows
    rows = len(body_rows) + 1
    cols = len(block.table.headers)
    shape = slide.shapes.add_table(rows, cols, Inches(0.55), Inches(1.15), Inches(12.2), Inches(5.4))
    table = shape.table
    for column, header in enumerate(block.table.headers):
        cell = table.cell(0, column)
        cell.text = header
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor(23, 59, 63)
        run = cell.text_frame.paragraphs[0].runs[0]
        run.font.color.rgb = RGBColor(255, 255, 255)
        run.font.bold = True
        run.font.size = Pt(10)
    for row_index, row in enumerate(body_rows, start=1):
        for column, value in enumerate(row.values):
            cell = table.cell(row_index, column)
            cell.text = _compact(value, 130)
            cell.text_frame.paragraphs[0].font.size = Pt(9)


def _slide_lines(blocks: list[ContentBlock]) -> list[str]:
    lines: list[str] = []
    for block in blocks:
        if block.kind in {"paragraph", "quotation", "callout", "heading"} and block.text:
            lines.append(block.text)
        elif block.kind in {"bullet_list", "numbered_list"}:
            lines.extend(item_text for item_text, _evidence_ids in _list_items(block))
        elif block.kind == "key_value":
            lines.extend(f"{entry.key}: {entry.value}" for entry in block.entries)
    return lines


def _block_evidence_ids(block: ContentBlock) -> list[str]:
    ids = list(block.evidence_ids)
    ids.extend(evidence_id for item in block.list_items for evidence_id in item.evidence_ids)
    ids.extend(evidence_id for entry in block.entries for evidence_id in entry.evidence_ids)
    if block.table is not None:
        ids.extend(evidence_id for row in block.table.rows for evidence_id in row.evidence_ids)
    return ids


def _list_items(block: ContentBlock) -> list[tuple[str, list[str]]]:
    if block.list_items:
        return [(item.text, item.evidence_ids) for item in block.list_items]
    return [(item, block.evidence_ids) for item in block.items]


def _table_block_chunks(block: ContentBlock, *, max_body_rows: int) -> list[ContentBlock]:
    if block.table is None or max_body_rows <= 0:
        return [block]
    rows = block.table.rows
    if len(rows) <= max_body_rows:
        return [block]
    return [
        block.model_copy(update={"table": block.table.model_copy(update={"rows": rows[offset : offset + max_body_rows]})})
        for offset in range(0, len(rows), max_body_rows)
    ]


def _with_sources(text: str, evidence_ids: list[str], citations: dict[str, EvidenceCitation]) -> str:
    summary = _source_summary(evidence_ids, citations)
    return f"{text} ({summary})" if summary else text


def _source_summary(evidence_ids: list[str], citations: dict[str, EvidenceCitation]) -> str:
    labels = [
        _short_citation(citations[evidence_id])
        for evidence_id in evidence_ids
        if evidence_id in citations
    ]
    return "Sources: " + "; ".join(dict.fromkeys(labels)) if labels else ""


def _short_citation(citation: EvidenceCitation) -> str:
    return f"{citation.doc_title}, p. {citation.page_start}" if citation.page_start else citation.doc_title


def _reference_line(index: int, citation: EvidenceCitation) -> str:
    page = ""
    if citation.page_start is not None and citation.page_end not in (None, citation.page_start):
        page = f", pages {citation.page_start}-{citation.page_end}"
    elif citation.page_start is not None:
        page = f", page {citation.page_start}"
    return f"[{index}] {citation.doc_title}{page} ({citation.doc_id}:{citation.chunk_id})"


def _pdf_footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColorRGB(0.32, 0.4, 0.42)
    canvas.drawCentredString(document.pagesize[0] / 2, 28, f"Faham AI | Page {document.page}")
    canvas.restoreState()


def _validate_package(artifact_format: ArtifactFormat, content: bytes) -> None:
    if len(content) < 100:
        raise RuntimeError(f"{artifact_format} renderer returned an empty package")
    if artifact_format == "pdf":
        if not content.startswith(b"%PDF"):
            raise RuntimeError("PDF renderer returned an invalid document")
        return
    required = "word/document.xml" if artifact_format == "docx" else "ppt/presentation.xml"
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            if required not in archive.namelist():
                raise RuntimeError(f"{artifact_format} package is missing {required}")
            archive.testzip()
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"{artifact_format} renderer returned an invalid OpenXML package") from exc


def _office_smoke_check(
    *,
    artifact_format: ArtifactFormat,
    content: bytes,
    require_libreoffice: bool,
) -> tuple[str, ...]:
    if artifact_format == "pdf":
        return ()
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if executable is None:
        if require_libreoffice:
            raise RuntimeError("LibreOffice is required for generated artifact smoke checks")
        return ("LibreOffice smoke check skipped because LibreOffice is unavailable.",)
    with tempfile.TemporaryDirectory(prefix="artifact-smoke-") as temp_dir:
        source = Path(temp_dir) / f"artifact.{artifact_format}"
        source.write_bytes(content)
        result = subprocess.run(
            [executable, "--headless", "--convert-to", "pdf", "--outdir", temp_dir, str(source)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        converted = Path(temp_dir) / "artifact.pdf"
        if result.returncode != 0 or not converted.exists() or converted.stat().st_size < 500:
            raise RuntimeError(f"LibreOffice smoke check failed: {(result.stderr or result.stdout)[-500:]}")
        pdftotext = shutil.which("pdftotext")
        if pdftotext:
            text_result = subprocess.run(
                [pdftotext, "-layout", str(converted), "-"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            pages = text_result.stdout.split("\f")
            if any(not page.strip() for page in pages[:-1]):
                raise RuntimeError("LibreOffice smoke check found a blank output page")
    return ()


def _safe_filename(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-")
    return _compact(candidate or "evidence-artifact", 80).strip(".-") or "evidence-artifact"


def _compact(value: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized if len(normalized) <= limit else normalized[: max(0, limit - 3)].rstrip() + "..."
