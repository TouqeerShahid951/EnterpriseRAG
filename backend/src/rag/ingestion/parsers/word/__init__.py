"""Public Word parsing surface."""

from .parser import DOCX_CONTENT_TYPE, parse_word_document, validated_docx_items

__all__ = ["DOCX_CONTENT_TYPE", "parse_word_document", "validated_docx_items"]
