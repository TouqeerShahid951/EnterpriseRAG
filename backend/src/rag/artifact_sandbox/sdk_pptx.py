"""PPTX layout primitives for sandbox build programs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rag.artifact_jobs.contracts import EvidenceCitation

from .sdk_shared import citation_map, compact, item_parts, normalize_evidence_ids, reference_line, row_parts, short_citation, validated_output_path


class PptxArtifact:
    def __init__(
        self,
        *,
        path: str,
        title: str,
        subtitle: str | None,
        generated_at: datetime,
        citations: list[EvidenceCitation],
    ) -> None:
        from pptx import Presentation
        from pptx.util import Inches

        self._path = validated_output_path(path)
        self._citations = citation_map(citations)
        self._all_citations = list(citations)
        self._presentation = Presentation()
        self._presentation.slide_width = Inches(13.333)
        self._presentation.slide_height = Inches(7.5)
        self._slide = None
        self._frame = None
        self._slide_source_ids: list[str] = []
        self._source_footer_shape = None
        self.add_title_slide(title, subtitle or "", footer=generated_at.date().isoformat())

    def add_title_slide(self, title: str, subtitle: str = "", *, footer: str = "") -> None:
        slide = self._presentation.slides.add_slide(self._presentation.slide_layouts[6])
        self._set_background(slide, "173B3F")
        self._add_text(slide, title, 0.8, 1.55, 11.7, 0.8, 30, "FFFFFF", bold=True)
        self._add_text(slide, subtitle, 0.85, 2.65, 10.8, 0.7, 17, "D6E4E5")
        self._add_text(slide, footer, 0.85, 6.6, 3.0, 0.25, 10, "AFC7C9")

    def add_slide(self, title: str, **_layout_hints: Any) -> None:
        slide = self._presentation.slides.add_slide(self._presentation.slide_layouts[6])
        self._set_background(slide, "F7F9F8")
        self._add_text(slide, title, 0.65, 0.3, 12.0, 0.55, 23, "173B3F", bold=True)
        self._slide = slide
        self._frame = None
        self._slide_source_ids = []
        self._source_footer_shape = None

    def add_heading(self, text: str, *, level: int = 1) -> None:
        self.add_slide(str(text))

    def add_paragraph(self, text: str, *, evidence_ids: list[str] | None = None) -> None:
        paragraph = self._text_frame().add_paragraph()
        paragraph.text = compact(text, 360)
        paragraph.font.size = self._pt(14)
        paragraph.space_after = self._pt(7)
        self._update_source_footer(evidence_ids)

    def add_bullet_list(self, items: list[Any], *, evidence_ids: list[str] | None = None) -> None:
        for item in items[:10]:
            text, ids = item_parts(item, evidence_ids)
            self.add_paragraph("- " + text, evidence_ids=ids)

    def add_numbered_list(self, items: list[Any], *, evidence_ids: list[str] | None = None) -> None:
        for index, item in enumerate(items[:10], start=1):
            text, ids = item_parts(item, evidence_ids)
            self.add_paragraph(f"{index}. {text}", evidence_ids=ids)

    def add_callout(self, text: str, *, evidence_ids: list[str] | None = None) -> None:
        self.add_paragraph("Key point: " + str(text), evidence_ids=evidence_ids)

    def add_table(self, headers: list[str], rows: list[Any], *, evidence_ids: list[str] | None = None) -> None:
        from pptx.dml.color import RGBColor
        from pptx.util import Inches

        self._ensure_slide()
        body = rows[:8]
        shape = self._slide.shapes.add_table(len(body) + 1, len(headers), Inches(0.55), Inches(1.15), Inches(12.2), Inches(5.4))
        table = shape.table
        for column, header in enumerate(headers):
            cell = table.cell(0, column)
            cell.text = str(header)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(23, 59, 63)
        for row_index, row in enumerate(body, start=1):
            values, _ids = row_parts(row, evidence_ids)
            for column, value in enumerate(values[: len(headers)]):
                table.cell(row_index, column).text = compact(value, 120)

    def add_page_break(self) -> None:
        self._slide = None
        self._frame = None
        self._slide_source_ids = []
        self._source_footer_shape = None

    def add_section_break(self) -> None:
        self.add_page_break()

    def add_references_slide(self, *_, **__) -> None:
        self.add_slide("References")
        self.add_bullet_list([reference_line(index, citation) for index, citation in enumerate(self._all_citations[:18], start=1)])

    def finalize(self) -> None:
        self._presentation.save(str(self._path))

    def _ensure_slide(self) -> None:
        if self._slide is None:
            self.add_slide("Details")

    def _text_frame(self):
        from pptx.util import Inches

        self._ensure_slide()
        if self._frame is None:
            box = self._slide.shapes.add_textbox(Inches(0.85), Inches(1.15), Inches(11.7), Inches(5.35))
            self._frame = box.text_frame
            self._frame.clear()
            self._frame.word_wrap = True
        return self._frame

    def _set_background(self, slide, color: str) -> None:
        from pptx.dml.color import RGBColor

        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string(color)

    def _add_text(self, slide, text: str, left: float, top: float, width: float, height: float, size: int, color: str, *, bold: bool = False) -> None:
        from pptx.dml.color import RGBColor
        from pptx.util import Inches

        box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
        paragraph = box.text_frame.paragraphs[0]
        paragraph.text = compact(text, 260)
        paragraph.font.name = "Aptos"
        paragraph.font.size = self._pt(size)
        paragraph.font.bold = bold
        paragraph.font.color.rgb = RGBColor.from_string(color)

    def _update_source_footer(self, evidence_ids: list[str] | None) -> None:
        from pptx.dml.color import RGBColor
        from pptx.util import Inches

        self._ensure_slide()
        for evidence_id in normalize_evidence_ids(evidence_ids):
            if evidence_id in self._citations and evidence_id not in self._slide_source_ids:
                self._slide_source_ids.append(evidence_id)
        if not self._slide_source_ids:
            return

        labels = [short_citation(self._citations[evidence_id]) for evidence_id in self._slide_source_ids]
        summary = compact("Sources: " + "; ".join(labels), 190)
        if self._source_footer_shape is None:
            self._source_footer_shape = self._slide.shapes.add_textbox(
                Inches(0.85),
                Inches(6.72),
                Inches(11.7),
                Inches(0.35),
            )
            self._source_footer_shape.text_frame.word_wrap = True

        text_frame = self._source_footer_shape.text_frame
        text_frame.clear()
        paragraph = text_frame.paragraphs[0]
        paragraph.text = summary
        paragraph.font.name = "Aptos"
        paragraph.font.size = self._pt(8)
        paragraph.font.color.rgb = RGBColor.from_string("53676A")

    def _pt(self, value: int):
        from pptx.util import Pt

        return Pt(value)
