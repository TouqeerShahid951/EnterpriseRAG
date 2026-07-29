from pathlib import Path

from rag.ops import prewarm_fastembed


def test_prewarm_uses_portable_regular_snapshot_files(monkeypatch) -> None:
    calls: list[tuple[str, str, Path]] = []
    monkeypatch.delenv("HF_HUB_DISABLE_SYMLINKS", raising=False)
    monkeypatch.setattr(
        prewarm_fastembed,
        "_load_dense_model",
        lambda model, cache: calls.append(("dense", model, cache)),
    )
    monkeypatch.setattr(
        prewarm_fastembed,
        "_load_sparse_model",
        lambda model, cache: calls.append(("sparse", model, cache)),
    )
    monkeypatch.setattr(
        prewarm_fastembed,
        "_load_reranker_model",
        lambda model, cache: calls.append(("reranker", model, cache)),
    )
    monkeypatch.setattr(
        prewarm_fastembed,
        "prewarm_entailment_model",
        lambda cache: calls.append(("entailment", "nli", cache)),
    )

    cache = Path("/models/fastembed")
    prewarm_fastembed.prewarm_fastembed_models(
        dense_model="dense-model",
        sparse_model="sparse-model",
        reranker_models=["reranker-model"],
        dense_cache_dir=cache,
        sparse_cache_dir=cache,
        reranker_cache_dir=cache,
    )

    assert prewarm_fastembed.os.environ["HF_HUB_DISABLE_SYMLINKS"] == "1"
    assert calls == [
        ("dense", "dense-model", cache),
        ("sparse", "sparse-model", cache),
        ("reranker", "reranker-model", cache),
        ("entailment", "nli", cache),
    ]
