"""FastEmbed Hugging Face cache layout checks."""

from __future__ import annotations

from pathlib import Path

__all__ = (
    "RERANKER_REQUIRED_SNAPSHOT_FILES",
    "has_complete_fastembed_model_cache",
    "has_fastembed_model_cache",
    "huggingface_cache_dir_names",
)

RERANKER_REQUIRED_SNAPSHOT_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "onnx/model.onnx",
)


def has_fastembed_model_cache(cache_dir: str | Path | None, model_name: str) -> bool:
    """Return whether any snapshot is present for a FastEmbed model."""
    if not cache_dir or not model_name.strip():
        return False
    root = Path(cache_dir)
    return any(
        _has_snapshot(root / cache_name)
        for cache_name in huggingface_cache_dir_names(model_name)
    )


def has_complete_fastembed_model_cache(
    cache_dir: str | Path | None,
    model_name: str,
    *,
    required_files: tuple[str, ...] = (),
) -> bool:
    """Return whether a snapshot has only non-empty files and required artifacts."""
    if not cache_dir or not model_name.strip():
        return False
    root = Path(cache_dir)
    return any(
        _has_complete_snapshot(
            root / cache_name,
            required_files=required_files,
        )
        for cache_name in huggingface_cache_dir_names(model_name)
    )


def huggingface_cache_dir_names(model_name: str) -> list[str]:
    normalized = model_name.strip()
    names = [_huggingface_cache_dir_name(normalized)]
    # FastEmbed's quantized catalog entries can map to a base Hugging Face
    # repository without the logical "-Q" suffix.
    if normalized.endswith("-Q"):
        names.append(_huggingface_cache_dir_name(normalized.removesuffix("-Q")))
    return names


def _huggingface_cache_dir_name(model_name: str) -> str:
    return "models--" + model_name.replace("/", "--")


def _has_snapshot(path: Path) -> bool:
    snapshots = path / "snapshots"
    try:
        return path.is_dir() and snapshots.is_dir() and any(snapshots.iterdir())
    except OSError:
        return False


def _has_complete_snapshot(
    path: Path,
    *,
    required_files: tuple[str, ...],
) -> bool:
    snapshots = path / "snapshots"
    if not snapshots.is_dir():
        return False
    try:
        return any(
            _snapshot_revision_is_complete(
                revision,
                required_files=required_files,
            )
            for revision in snapshots.iterdir()
            if revision.is_dir()
        )
    except OSError:
        return False


def _snapshot_revision_is_complete(
    revision: Path,
    *,
    required_files: tuple[str, ...],
) -> bool:
    try:
        artifacts = [
            path for path in revision.rglob("*") if path.is_file() or path.is_symlink()
        ]
        if not artifacts:
            return False
        if any(not path.is_file() or path.stat().st_size <= 0 for path in artifacts):
            return False
        return all(
            (revision / relative_path).is_file()
            and (revision / relative_path).stat().st_size > 0
            for relative_path in required_files
        )
    except OSError:
        return False
