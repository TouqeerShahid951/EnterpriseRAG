"""Small SDK available to constrained artifact build programs."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from rag.artifact_jobs.contracts import ArtifactContentBundle, ContentBlock, ContentSection, ContentTable, ContentTableRow, EvidenceCitation

from .sdk_docx import DocxArtifact
from .sdk_pdf import PdfArtifact
from .sdk_pptx import PptxArtifact
from .sdk_shared import citation_map, normalize_evidence_ids, source_summary


class ArtifactTableCell:
    def __init__(self, value: object) -> None:
        self.value = str(value)

    def __str__(self) -> str:
        return self.value


class ArtifactTableRow:
    def __init__(self, row: ContentTableRow) -> None:
        self.values = [ArtifactTableCell(value) for value in row.values]
        self.evidence_ids = normalize_evidence_ids(row.evidence_ids)


class ArtifactTable:
    def __init__(self, table: ContentTable) -> None:
        self.headers = list(table.headers)
        self.rows = [ArtifactTableRow(row) for row in table.rows]


class ArtifactBlock:
    def __init__(self, block: ContentBlock) -> None:
        self._block = block

    def __getattr__(self, name: str) -> Any:
        return getattr(self._block, name)

    @property
    def table(self) -> ArtifactTable | None:
        return ArtifactTable(self._block.table) if self._block.table is not None else None

    @property
    def evidence_ids(self) -> list[str]:
        return normalize_evidence_ids(self._block.evidence_ids)


class ArtifactSection:
    def __init__(self, section: ContentSection) -> None:
        self.title = section.title
        self.objective = section.title
        self.blocks = [ArtifactBlock(block) for block in section.blocks]


class ArtifactDocument:
    def __init__(self, bundle: ArtifactContentBundle, generated_at: datetime) -> None:
        self.bundle = bundle
        self.generated_at = generated_at
        self._citations = citation_map(bundle.content.citations)

    @classmethod
    def from_input(cls, path: str) -> "ArtifactDocument":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        generated_at = datetime.fromisoformat(payload["generated_at"])
        return cls(ArtifactContentBundle.model_validate(payload["bundle"]), generated_at)

    @property
    def title(self) -> str:
        return self.bundle.content.title

    @property
    def subtitle(self) -> str | None:
        return self.bundle.paginated.subtitle or self.bundle.presentation.subtitle

    @property
    def purpose(self) -> str:
        return self.bundle.content.purpose

    @property
    def sections(self) -> list[ArtifactSection]:
        return [ArtifactSection(section) for section in self.bundle.content.sections]

    @property
    def citations(self) -> list[EvidenceCitation]:
        return list(self.bundle.content.citations)

    def source_summary(self, evidence_ids: list[str]) -> str:
        return source_summary(evidence_ids, self._citations)

    def create_docx(self, path: str, *, title: str | None = None, subtitle: str | None = None) -> DocxArtifact:
        return DocxArtifact(
            path=path,
            title=title or self.title,
            subtitle=subtitle if subtitle is not None else self.subtitle,
            generated_at=self.generated_at,
            citations=self.citations,
        )

    def create_pdf(self, path: str, *, title: str | None = None, subtitle: str | None = None) -> PdfArtifact:
        return PdfArtifact(
            path=path,
            title=title or self.title,
            subtitle=subtitle if subtitle is not None else self.subtitle,
            generated_at=self.generated_at,
            citations=self.citations,
        )

    def create_pptx(self, path: str, *, title: str | None = None, subtitle: str | None = None) -> PptxArtifact:
        return PptxArtifact(
            path=path,
            title=title or self.title,
            subtitle=subtitle if subtitle is not None else self.subtitle,
            generated_at=self.generated_at,
            citations=self.citations,
        )
