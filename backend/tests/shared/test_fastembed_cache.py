from rag.shared.fastembed_dense import has_fastembed_model_cache


def test_has_fastembed_model_cache_checks_huggingface_snapshot(tmp_path) -> None:
    snapshot = tmp_path / "models--nomic-ai--nomic-embed-text-v1.5" / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}")

    assert has_fastembed_model_cache(str(tmp_path), "nomic-ai/nomic-embed-text-v1.5-Q")
    assert not has_fastembed_model_cache(str(tmp_path), "BAAI/bge-reranker-base")
