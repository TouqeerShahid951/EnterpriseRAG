"""Build DOCX and PDF manuals from the maintained Markdown sources."""

from __future__ import annotations

from pathlib import Path

from manual_builder import MANUALS, Manual, build_docx, build_pdf, parse_markdown


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "docs" / "manuals"
OUTPUT_DIR = SOURCE_DIR / "generated"


__all__ = [
    "MANUALS",
    "Manual",
    "build_docx",
    "build_pdf",
    "main",
    "parse_markdown",
]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for manual in MANUALS:
        blocks = parse_markdown(SOURCE_DIR / manual.source)
        build_docx(blocks, OUTPUT_DIR / manual.docx, manual.running_label)
        build_pdf(blocks, OUTPUT_DIR / manual.pdf, manual.running_label)
        print(f"Wrote {OUTPUT_DIR / manual.docx}")
        print(f"Wrote {OUTPUT_DIR / manual.pdf}")


if __name__ == "__main__":
    main()
