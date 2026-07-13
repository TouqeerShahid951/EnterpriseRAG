"""Manual source and output specifications."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Manual:
    source: str
    docx: str
    pdf: str
    running_label: str


MANUALS = [
    Manual(
        source="end-user-manual.md",
        docx="Prudentia-AI-End-User-Manual.docx",
        pdf="Prudentia-AI-End-User-Manual.pdf",
        running_label="Prudentia AI End User Manual",
    ),
    Manual(
        source="administrator-manual.md",
        docx="Prudentia-AI-Administrator-Manual.docx",
        pdf="Prudentia-AI-Administrator-Manual.pdf",
        running_label="Prudentia AI Administrator Manual",
    ),
    Manual(
        source="operator-manual.md",
        docx="Prudentia-AI-Operator-Manual.docx",
        pdf="Prudentia-AI-Operator-Manual.pdf",
        running_label="Prudentia AI Operator Manual",
    ),
]
