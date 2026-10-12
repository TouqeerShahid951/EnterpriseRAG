"""Small, deterministic helpers for resumable ingestion work."""

from __future__ import annotations

from dataclasses import MISSING, asdict, fields
import hashlib
import json
from typing import Any

from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE

from ..chunking.chunker import TextChunk
from ..parsers.models import parsed_item_from_dict, parsed_item_to_dict


def logical_ranges(total: int, batch_size: int) -> list[tuple[int, int]]:
    """Return the frozen half-open work ranges for an ordered input."""
    if total < 0:
        raise ValueError("total must be non-negative")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    return [
        (start, min(start + batch_size, total))
        for start in range(0, total, batch_size)
    ]


def missing_ranges(
    total: int,
    batch_size: int,
    completed: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Return only complete, expected ranges that still need computation."""
    expected = logical_ranges(total, batch_size)
    return [work_range for work_range in expected if work_range not in completed]


def text_chunk_to_dict(chunk: TextChunk) -> dict[str, Any]:
    """Serialize every chunk field, including citation targets, without defaults."""
    payload = asdict(chunk)
    if set(payload) != {field.name for field in fields(TextChunk)}:
        raise ValueError("text chunk fields are incomplete")
    return payload


def text_chunk_from_dict(payload: dict[str, Any]) -> TextChunk:
    if not isinstance(payload, dict):
        raise ValueError("text chunk must be an object")
    required = {
        field.name
        for field in fields(TextChunk)
        if field.default is MISSING and field.default_factory is MISSING
    }
    if not required.issubset(payload):
        raise ValueError("text chunk is missing required fields")
    values = dict(payload)
    for name in ("section_path", "quality_flags", "table_column_headers", "structured_fields", "structured_field_names", "structured_field_values", "citation_targets"):
        if not isinstance(values.get(name), list):
            raise ValueError(f"text chunk {name} must be a list")
    if any(not isinstance(target, dict) or not isinstance(target.get("exact_text"), str) for target in values["citation_targets"]):
        raise ValueError("text chunk citation targets must preserve exact text")
    if not isinstance(values.get("index"), int) or values["index"] < 0:
        raise ValueError("text chunk index must be non-negative")
    return TextChunk(**values)


def restore_prepared_state(state: dict[str, Any], deps: Any, configuration_digest: str) -> bool:
    """Restore the last durable pre-embedding output, if it still matches the source."""
    checkpoint = getattr(deps, "checkpoint", None)
    if checkpoint is None:
        return False
    file_bytes = state.get("file_bytes")
    payload = state.get("payload")
    if not isinstance(file_bytes, bytes) or payload is None:
        return False
    loaded = checkpoint.load(
        job_id=payload.job_id,
        stage_key="prepared",
        upstream_sha256=hashlib.sha256(file_bytes).hexdigest(),
        configuration_digest=configuration_digest,
    )
    if loaded is None:
        return False
    descriptor, saved = loaded
    chunks = saved.get("chunks")
    texts = saved.get("embedding_texts")
    glossary = getattr(payload, "doc_type", None) == ABBREVIATION_GLOSSARY_DOC_TYPE
    if not isinstance(chunks, list) or not isinstance(texts, list) or (len(texts) != (0 if glossary else len(chunks))):
        return _discard(deps, descriptor)
    if saved.get("review_fingerprint") != checkpoint_review_fingerprint(state) or not isinstance(saved.get("claims"), list) or not isinstance(saved.get("metadata"), dict):
        return _discard(deps, descriptor)
    try:
        restored_chunks = [text_chunk_from_dict(item) for item in chunks]
    except (TypeError, ValueError):
        return _discard(deps, descriptor)
    if [chunk.index for chunk in restored_chunks] != list(range(len(restored_chunks))):
        return _discard(deps, descriptor)
    if not all(isinstance(text, str) for text in texts):
        return _discard(deps, descriptor)
    ranges = validated_ranges(saved.get("embedding_ranges"), len(texts))
    if ranges is None:
        return _discard(deps, descriptor)
    if glossary and not isinstance(saved.get("abbreviation_entries"), list):
        return _discard(deps, descriptor)
    state["embedding_ranges"] = ranges
    state["prepared_sha256"] = descriptor.body_sha256
    state["chunks"] = restored_chunks
    state["embedding_texts"] = list(texts)
    state["claims"] = list(saved["claims"])
    state["metadata"] = dict(saved["metadata"])
    state["parser_provenance"] = dict(saved.get("parser_provenance") or {})
    state["warnings"] = [str(item) for item in saved.get("warnings") or []]
    state["abbreviation_entries"] = list(saved.get("abbreviation_entries") or [])
    return True


def restore_parsed_state(state: dict[str, Any], deps: Any, configuration_digest: str) -> bool:
    loaded = _load_stage(state, deps, "parsed", configuration_digest)
    if loaded is None:
        return False
    descriptor, saved = loaded
    raw_items = saved.get("parsed_items")
    if not isinstance(raw_items, list) or saved.get("review_fingerprint") != checkpoint_review_fingerprint(state):
        return _discard(deps, descriptor)
    try:
        items = [parsed_item_from_dict(item) for item in raw_items]
    except (TypeError, ValueError):
        return _discard(deps, descriptor)
    state["parsed_items"] = items
    state["parser_provenance"] = dict(saved.get("parser_provenance") or {})
    state["warnings"] = [str(item) for item in saved.get("warnings") or []]
    return True


def restore_metadata_state(state: dict[str, Any], deps: Any, configuration_digest: str) -> bool:
    loaded = _load_stage(state, deps, "metadata", configuration_digest)
    if loaded is None:
        return False
    descriptor, saved = loaded
    raw_items = saved.get("parsed_items")
    metadata = saved.get("metadata")
    if not isinstance(raw_items, list) or not isinstance(metadata, dict) or saved.get("review_fingerprint") != checkpoint_review_fingerprint(state):
        return _discard(deps, descriptor)
    try:
        items = [parsed_item_from_dict(item) for item in raw_items]
    except (TypeError, ValueError):
        return _discard(deps, descriptor)
    state["parsed_items"] = items
    state["metadata"] = metadata
    state["parser_provenance"] = dict(saved.get("parser_provenance") or {})
    state["warnings"] = [str(item) for item in saved.get("warnings") or []]
    return True


def save_parsed_checkpoint(state: dict[str, Any], deps: Any, configuration_digest: str) -> None:
    checkpoint = getattr(deps, "checkpoint", None)
    if checkpoint is None:
        return
    checkpoint.commit(
        job_id=state["payload"].job_id,
        document_id=state["payload"].doc_id,
        stage_key="parsed",
        payload={
            "parsed_items": [parsed_item_to_dict(item) for item in state["parsed_items"]],
            "parser_provenance": state.get("parser_provenance", {}),
            "warnings": state.get("warnings", []),
            "review_fingerprint": checkpoint_review_fingerprint(state),
        },
        upstream_sha256=hashlib.sha256(state["file_bytes"]).hexdigest(),
        configuration_digest=configuration_digest,
    )


def save_metadata_checkpoint(state: dict[str, Any], deps: Any, configuration_digest: str) -> None:
    checkpoint = getattr(deps, "checkpoint", None)
    if checkpoint is None:
        return
    checkpoint.commit(
        job_id=state["payload"].job_id,
        document_id=state["payload"].doc_id,
        stage_key="metadata",
        payload={
            "parsed_items": [parsed_item_to_dict(item) for item in state["parsed_items"]],
            "metadata": state.get("metadata", {}),
            "parser_provenance": state.get("parser_provenance", {}),
            "warnings": state.get("warnings", []),
            "review_fingerprint": checkpoint_review_fingerprint(state),
        },
        upstream_sha256=hashlib.sha256(state["file_bytes"]).hexdigest(),
        configuration_digest=configuration_digest,
    )


def _load_stage(state: dict[str, Any], deps: Any, stage_key: str, configuration_digest: str):
    checkpoint = getattr(deps, "checkpoint", None)
    payload = state.get("payload")
    file_bytes = state.get("file_bytes")
    if checkpoint is None or payload is None or not isinstance(file_bytes, bytes):
        return None
    return checkpoint.load(
        job_id=payload.job_id,
        stage_key=stage_key,
        upstream_sha256=hashlib.sha256(file_bytes).hexdigest(),
        configuration_digest=configuration_digest,
    )


def _review_fingerprint(payload: Any) -> str:
    to_dict = getattr(payload, "to_dict", None)
    values = to_dict() if callable(to_dict) else {}
    # These inputs affect metadata, claims, review gates or rendered embedding text.
    selected = {key: value for key, value in values.items() if key not in {"job_id", "delivery_id"}}
    return hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def checkpoint_review_fingerprint(state: dict[str, Any]) -> str:
    base = _review_fingerprint(state["payload"])
    reviews = state.get("checkpoint_reviews")
    if not reviews:
        return base
    return hashlib.sha256(json.dumps([base, reviews], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def refresh_review_context(state: dict[str, Any], deps: Any) -> None:
    """Check current approvals through their owner before bypassing extraction."""
    if getattr(deps, "checkpoint", None) is None:
        return
    payload = state["payload"]
    reviews = {}
    if payload.review_batch_id:
        reviews["ocr"] = deps.backend.get_review_batch_parsed_items(review_batch_id=payload.review_batch_id)
    if payload.image_review_batch_id:
        reviews["image"] = deps.backend.get_image_review_resume(image_review_batch_id=payload.image_review_batch_id)
    state["checkpoint_reviews"] = reviews


def _discard(deps: Any, descriptor: Any) -> bool:
    deps.checkpoint.invalidate(descriptor)
    return False


def validated_ranges(value: Any, total: int) -> list[tuple[int, int]] | None:
    if not isinstance(value, list):
        return None
    ranges = []
    cursor = 0
    for pair in value:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            return None
        start, end = pair
        if type(start) is not int or type(end) is not int or start != cursor or not start < end <= total:
            return None
        ranges.append((start, end))
        cursor = end
    return ranges if cursor == total else None
