"""Group path helpers used for ABAC payload contracts."""

from __future__ import annotations


def normalize_group_path(group_path: str) -> str:
    """Normalize a group path without broadening its authorization scope."""
    if not isinstance(group_path, str):
        raise TypeError("group_path must be a string")

    candidate = group_path.strip()
    if not candidate:
        raise ValueError("group_path must not be empty")
    if candidate == "/":
        return "/"
    if "//" in candidate:
        raise ValueError("group_path must not contain empty path segments")

    parts = [part for part in candidate.strip("/").split("/") if part]
    if not parts:
        raise ValueError("group_path must contain at least one segment")
    if any(part in {".", ".."} for part in parts):
        raise ValueError("group_path must not contain relative path segments")

    return "/" + "/".join(parts)


def is_flat_group_path(group_path: str) -> bool:
    parts = normalize_group_path(group_path).strip("/").split("/")
    return len(parts) == 1 and bool(parts[0])


def require_flat_group_path(group_path: str) -> str:
    normalized = normalize_group_path(group_path)
    if not is_flat_group_path(normalized):
        raise ValueError("group path must be a single flat Knowledge Space segment")
    return normalized
