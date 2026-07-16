from pathlib import Path

import pytest

from rag.shared.fastembed_cache import (
    RERANKER_REQUIRED_SNAPSHOT_FILES,
    has_complete_fastembed_model_cache,
)
from rag.shared.fastembed_dense import has_fastembed_model_cache
from rag.shared.model_cache_health import verify_fastembed_cache


def test_has_fastembed_model_cache_checks_huggingface_snapshot(tmp_path) -> None:
    snapshot = tmp_path / "models--nomic-ai--nomic-embed-text-v1.5" / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}")

    assert has_fastembed_model_cache(str(tmp_path), "nomic-ai/nomic-embed-text-v1.5-Q")
    assert not has_fastembed_model_cache(str(tmp_path), "BAAI/bge-reranker-base")


def test_complete_fastembed_cache_rejects_zero_byte_snapshot_artifact(tmp_path) -> None:
    snapshot = _snapshot(tmp_path, "Xenova/ms-marco-MiniLM-L-6-v2")
    (snapshot / "config.json").write_text("{}")
    (snapshot / "tokenizer.json").write_text("{}")
    (snapshot / "tokenizer_config.json").write_text("{}")
    (snapshot / "special_tokens_map.json").write_text("{}")
    (snapshot / "onnx").mkdir()
    (snapshot / "onnx" / "model.onnx").touch()

    assert not has_complete_fastembed_model_cache(
        tmp_path,
        "Xenova/ms-marco-MiniLM-L-6-v2",
        required_files=RERANKER_REQUIRED_SNAPSHOT_FILES,
    )


def test_complete_fastembed_cache_rejects_missing_required_artifact(tmp_path) -> None:
    snapshot = _snapshot(tmp_path, "Xenova/ms-marco-MiniLM-L-6-v2")
    (snapshot / "config.json").write_text("{}")
    (snapshot / "tokenizer.json").write_text("{}")
    (snapshot / "tokenizer_config.json").write_text("{}")
    (snapshot / "onnx").mkdir()
    (snapshot / "onnx" / "model.onnx").write_bytes(b"onnx")

    assert not has_complete_fastembed_model_cache(
        tmp_path,
        "Xenova/ms-marco-MiniLM-L-6-v2",
        required_files=RERANKER_REQUIRED_SNAPSHOT_FILES,
    )


def test_complete_fastembed_cache_does_not_merge_artifacts_across_snapshots(
    tmp_path,
) -> None:
    first = _snapshot(tmp_path, "Xenova/ms-marco-MiniLM-L-6-v2")
    (first / "config.json").write_text("{}")
    (first / "tokenizer.json").write_text("{}")
    second = first.parent / "def456"
    (second / "onnx").mkdir(parents=True)
    (second / "tokenizer_config.json").write_text("{}")
    (second / "special_tokens_map.json").write_text("{}")
    (second / "onnx" / "model.onnx").write_bytes(b"onnx")

    assert not has_complete_fastembed_model_cache(
        tmp_path,
        "Xenova/ms-marco-MiniLM-L-6-v2",
        required_files=RERANKER_REQUIRED_SNAPSHOT_FILES,
    )


def test_fastembed_health_accepts_nonempty_reranker_snapshot(tmp_path) -> None:
    _presence_snapshot(tmp_path, "dense")
    _presence_snapshot(tmp_path, "sparse")
    reranker = _snapshot(tmp_path, "reranker")
    (reranker / "config.json").write_text("{}")
    (reranker / "tokenizer.json").write_text("{}")
    (reranker / "tokenizer_config.json").write_text("{}")
    (reranker / "special_tokens_map.json").write_text("{}")
    (reranker / "onnx").mkdir()
    (reranker / "onnx" / "model.onnx").write_bytes(b"onnx")

    verify_fastembed_cache(
        tmp_path,
        dense_model="dense",
        sparse_model="sparse",
        reranker_model="reranker",
    )


def test_fastembed_health_rejects_zero_byte_reranker_snapshot(tmp_path) -> None:
    _presence_snapshot(tmp_path, "dense")
    _presence_snapshot(tmp_path, "sparse")
    reranker = _snapshot(tmp_path, "reranker")
    (reranker / "config.json").write_text("{}")
    (reranker / "tokenizer.json").write_text("{}")
    (reranker / "tokenizer_config.json").write_text("{}")
    (reranker / "special_tokens_map.json").write_text("{}")
    (reranker / "onnx").mkdir()
    (reranker / "onnx" / "model.onnx").touch()

    with pytest.raises(SystemExit, match="missing or invalid"):
        verify_fastembed_cache(
            tmp_path,
            dense_model="dense",
            sparse_model="sparse",
            reranker_model="reranker",
        )


def _presence_snapshot(root: Path, model_name: str) -> Path:
    snapshot = _snapshot(root, model_name)
    (snapshot / "config.json").write_text("{}")
    return snapshot


def _snapshot(root: Path, model_name: str) -> Path:
    snapshot = (
        root / f"models--{model_name.replace('/', '--')}" / "snapshots" / "abc123"
    )
    snapshot.mkdir(parents=True)
    return snapshot
