"""Document parsing package for ingestion."""

from .document import parse_document
from .pdf import parse_pdf_document

__all__ = ["parse_document", "parse_pdf_document"]
