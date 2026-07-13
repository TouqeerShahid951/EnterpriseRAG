"""Markdown-driven DOCX and PDF manual generation."""

from .docx_renderer import build_docx
from .markdown_parser import parse_markdown
from .models import MANUALS, Manual
from .pdf_renderer import build_pdf

__all__ = ["MANUALS", "Manual", "build_docx", "build_pdf", "parse_markdown"]
