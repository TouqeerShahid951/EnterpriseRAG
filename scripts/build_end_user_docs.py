"""Build the Prudentia AI end-user walkthrough in DOCX and PDF formats."""

from __future__ import annotations

from pathlib import Path

from end_user_docs import build_docx, build_pdf


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
DOCX_PATH = DOCS_DIR / "Prudentia-AI-End-User-Walkthrough.docx"
PDF_PATH = DOCS_DIR / "Prudentia-AI-End-User-Walkthrough.pdf"


__all__ = ["build_docx", "build_pdf", "main"]


def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    build_docx(DOCX_PATH)
    build_pdf(PDF_PATH)
    print(f"Wrote {DOCX_PATH}")
    print(f"Wrote {PDF_PATH}")


if __name__ == "__main__":
    main()
