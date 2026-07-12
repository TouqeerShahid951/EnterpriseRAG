"""Metadata-enriched retrieval text without changing source excerpts."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from ..chunking import TextChunk

_TERM_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,}")


def build_embedding_texts(*, file_path: str, chunks: list[TextChunk], metadata: dict[str, Any]) -> list[str]:
    title = title_from_path(file_path)
    return [embedding_text_for_chunk(title=title, chunk=chunk, metadata=metadata) for chunk in chunks]


def embedding_text_for_chunk(*, title: str, chunk: TextChunk, metadata: dict[str, Any]) -> str:
    prefix = metadata_prefix(title=title, chunk=chunk, metadata=metadata)
    return f"{prefix}\n\n{chunk.text}" if prefix else chunk.text


def metadata_prefix(*, title: str, chunk: TextChunk, metadata: dict[str, Any]) -> str:
    lines: list[str] = []
    doc_type = _doc_type(metadata)
    entities = _entity_texts(metadata.get("named_entities"))[:8]
    summary = compact_summary(metadata.get("summary"))
    section = " / ".join([*chunk.section_path, chunk.section_title or ""]).strip(" /")
    if title:
        lines.append(f"Document title: {title}")
    if doc_type:
        lines.append(f"Document type: {doc_type}")
    if entities:
        lines.append(f"Key entities: {', '.join(entities)}")
    if section:
        lines.append(f"Section: {section}")
    if summary:
        lines.append(f"Summary: {summary}")
    return "\n".join(lines)


def metadata_terms_for_chunk(*, title: str, chunk: TextChunk, metadata: dict[str, Any]) -> list[str]:
    values: list[str] = [
        title,
        _doc_type(metadata),
        str(metadata.get("auto_doc_type") or ""),
        compact_summary(metadata.get("summary")),
        chunk.section_title or "",
        chunk.table_title,
        chunk.table_caption,
        chunk.table_row_label,
        *chunk.section_path,
        *chunk.structured_field_names,
        *_entity_texts(metadata.get("named_entities")),
    ]
    return _unique([term for value in values for term in _terms(value)])[:96]


def compact_summary(value: Any, *, limit: int = 500) -> str:
    summary = str(value or "").strip()
    return summary[:limit].rstrip()


def metadata_version(metadata: dict[str, Any]) -> int:
    try:
        return int(metadata.get("metadata_version") or 1)
    except (TypeError, ValueError):
        return 1


def title_from_path(file_path: str) -> str:
    if file_path.startswith("minio://"):
        suffix = file_path.split("/", 3)[-1]
        return _original_filename(PurePosixPath(suffix).name)
    return _original_filename(PurePosixPath(file_path).name)


def _doc_type(metadata: dict[str, Any]) -> str:
    for key in ("doc_type", "auto_doc_type"):
        value = str(metadata.get(key) or "").strip().lower()
        if value:
            return value
    return ""


def _entity_texts(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    texts: list[str] = []
    for item in value:
        if isinstance(item, dict) and str(item.get("text", "")).strip():
            texts.append(str(item["text"]).strip())
    return _unique(texts)


def _terms(value: str) -> list[str]:
    return _TERM_RE.findall(value.lower())


def _original_filename(stored_name: str) -> str:
    if len(stored_name) > 37 and stored_name[36] == "-":
        try:
            UUID(stored_name[:36])
        except ValueError:
            pass
        else:
            return stored_name[37:] or "Uploaded PDF"
    return stored_name or "Uploaded PDF"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
