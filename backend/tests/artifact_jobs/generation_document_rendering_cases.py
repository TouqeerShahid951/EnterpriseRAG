from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
import zipfile

from rag.artifact_jobs.layout_profiles import select_layout_profile
from rag.artifact_jobs.renderer import render_document

from generation_rendering_support import (
    operator_guide_bundle,
    pdf_showcase_bundle,
    standard_layout_bundle,
    timeline_bundle,
)


def test_deterministic_pdf_renders_polished_primitives() -> None:
    rendered = render_document(
        artifact_format="pdf",
        bundle=pdf_showcase_bundle(),
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        require_libreoffice=False,
    )

    assert rendered.content_type == "application/pdf"
    assert rendered.content.startswith(b"%PDF")
    assert len(rendered.content) > 2000


def test_adaptive_layout_profile_infers_document_archetypes() -> None:
    assert select_layout_profile(pdf_showcase_bundle()).key == "evidence_brief"
    assert select_layout_profile(timeline_bundle()).key == "timeline_report"
    assert select_layout_profile(operator_guide_bundle()).key == "operator_guide"
    assert select_layout_profile(standard_layout_bundle()).key == "standard_report"


def test_deterministic_docx_uses_adaptive_style_system() -> None:
    rendered = render_document(
        artifact_format="docx",
        bundle=pdf_showcase_bundle(),
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        require_libreoffice=False,
    )

    with zipfile.ZipFile(BytesIO(rendered.content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        header_xml = "\n".join(
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("word/header")
        )
        footer_xml = "\n".join(
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("word/footer")
        )

    assert "EVIDENCE BRIEF" in document_xml
    assert "w:tblGrid" in document_xml
    assert "w:tblHeader" in document_xml
    assert "Prudentia AI" in header_xml
    assert " PAGE " in footer_xml
