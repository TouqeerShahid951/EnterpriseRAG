"""Two-stage LLM metadata extraction helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

METADATA_VERSION = 2
METADATA_EXTRACTION_WARNING = "metadata_extraction_unavailable"
METADATA_CONSOLIDATION_WARNING = "metadata_consolidation_unavailable"
METADATA_EXCEPTION_WARNING = "metadata_extraction_exception"


def generate_metadata_v2(
    parsed_items: list[Any],
    generate_metadata: Callable[[str], dict[str, Any]],
    *,
    max_windows: int = 4,
    max_window_chars: int = 4000,
) -> dict[str, Any]:
    windows = _metadata_windows(parsed_items, max_windows=max_windows, max_window_chars=max_window_chars)
    warnings: list[str] = []
    metadata_errors: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for window in windows:
        candidate = _safe_generate(generate_metadata, window)
        warnings.extend(_pop_warnings(candidate))
        metadata_errors.extend(_pop_metadata_errors(candidate))
        if _has_metadata_signal(candidate):
            candidates.append(candidate)
    if not candidates:
        return _fallback(warnings, window_count=len(windows), metadata_errors=metadata_errors)

    final = _safe_generate(generate_metadata, _consolidation_prompt(candidates, windows))
    warnings.extend(_pop_warnings(final))
    metadata_errors.extend(_pop_metadata_errors(final))
    if _has_metadata_signal(final):
        metadata = _fill_missing(final, _merge_candidates(candidates))
        mode = "llm_consolidated"
    else:
        metadata = _merge_candidates(candidates)
        warnings.append(METADATA_CONSOLIDATION_WARNING)
        mode = "candidate_merge"
    metadata["_warnings"] = _unique(warnings)
    if metadata_errors:
        metadata["_metadata_errors"] = metadata_errors[:5]
    metadata["_metadata_extraction"] = {
        "version": METADATA_VERSION,
        "mode": mode,
        "window_count": len(windows),
        "candidate_count": len(candidates),
    }
    return metadata


def _metadata_windows(parsed_items: list[Any], *, max_windows: int, max_window_chars: int) -> list[str]:
    texts = [str(getattr(item, "text", "")).strip() for item in parsed_items]
    chunks: list[str] = []
    current = ""
    for text in texts:
        if not text:
            continue
        candidate = f"{current}\n\n{text}".strip()
        if current and len(candidate) > max_window_chars:
            chunks.append(current)
            current = text[:max_window_chars]
        else:
            current = candidate[:max_window_chars]
    if current:
        chunks.append(current)
    if len(chunks) <= max_windows:
        return chunks or [""]
    indexes = {0, len(chunks) - 1}
    if max_windows > 2:
        indexes.update(round((len(chunks) - 1) * i / (max_windows - 1)) for i in range(1, max_windows - 1))
    return [chunks[index] for index in sorted(indexes)[:max_windows]]


def _safe_generate(generate_metadata: Callable[[str], dict[str, Any]], text: str) -> dict[str, Any]:
    try:
        metadata = generate_metadata(text)
    except Exception:
        return {
            "_warnings": [METADATA_EXCEPTION_WARNING],
            "_metadata_errors": [
                {
                    "warning": METADATA_EXCEPTION_WARNING,
                    "service": "metadata",
                    "message": "metadata extraction raised an unexpected exception",
                }
            ],
        }
    return dict(metadata) if isinstance(metadata, dict) else {"_warnings": [METADATA_EXTRACTION_WARNING]}


def _pop_warnings(metadata: dict[str, Any]) -> list[str]:
    raw = metadata.pop("_warnings", [])
    return [str(item) for item in raw] if isinstance(raw, list) else []


def _pop_metadata_errors(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    raw = metadata.pop("_metadata_errors", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _has_metadata_signal(metadata: dict[str, Any]) -> bool:
    return bool(
        str(metadata.get("summary", "")).strip()
        or _strings(metadata.get("llm_topics"))
        or _strings(metadata.get("topics"))
        or bool(str(metadata.get("doc_type", "")).strip())
        or _claims(metadata.get("claims"))
    )


def _consolidation_prompt(candidates: list[dict[str, Any]], windows: list[str]) -> str:
    return (
        "Consolidate these section-level metadata candidates into one document-level metadata object. "
        "Prefer repeated facts, remove duplicates, keep the summary to exactly two factual sentences, "
        "infer a concise freeform doc_type from the content, and return summary, llm_topics, doc_type, and claims.\n\n"
        f"Candidates:\n{json.dumps(candidates, ensure_ascii=True)[:4200]}\n\n"
        f"Representative text:\n{chr(10).join(windows[:2])[:1600]}"
    )


def _merge_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "summary": next((str(item.get("summary", "")).strip() for item in candidates if str(item.get("summary", "")).strip()), ""),
        "llm_topics": _unique([topic for item in candidates for topic in _strings(item.get("llm_topics") or item.get("topics"))])[:8],
        "topics": _unique([topic for item in candidates for topic in _strings(item.get("topics"))])[:8],
        "doc_type": _best_doc_type(candidates),
        "claims": _unique_claims([claim for item in candidates for claim in _claims(item.get("claims"))])[:20],
    }


def _fill_missing(final: dict[str, Any], merged: dict[str, Any]) -> dict[str, Any]:
    result = dict(final)
    if not str(result.get("summary", "")).strip():
        result["summary"] = merged["summary"]
    if not _strings(result.get("llm_topics") or result.get("topics")):
        result["llm_topics"] = merged["llm_topics"]
    if not str(result.get("doc_type", "")).strip():
        result["doc_type"] = merged["doc_type"]
    if not _claims(result.get("claims")):
        result["claims"] = merged["claims"]
    return result


def _best_doc_type(candidates: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for item in candidates:
        value = str(item.get("doc_type", "")).strip().lower()
        if value:
            counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0] if counts else ""


def _fallback(
    warnings: list[str],
    *,
    window_count: int,
    metadata_errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "summary": "",
        "topics": [],
        "llm_topics": [],
        "doc_type": "",
        "claims": [],
        "_warnings": _unique([*warnings, METADATA_EXTRACTION_WARNING]),
        "_metadata_errors": list(metadata_errors or [])[:5],
        "_metadata_extraction": {
            "version": METADATA_VERSION,
            "mode": "deterministic_fallback",
            "window_count": window_count,
            "candidate_count": 0,
        },
    }


def _strings(value: Any) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []


def _claims(value: Any) -> list[dict[str, str]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _unique_claims(claims: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, str]] = []
    for claim in claims:
        key = tuple(str(claim.get(field, "")).strip().lower() for field in ("entity", "attribute", "value"))
        if all(key) and key not in seen:
            seen.add(key)
            unique.append({field: str(claim.get(field, "")).strip() for field in ("entity", "attribute", "value")})
    return unique
