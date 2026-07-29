from __future__ import annotations

import logging

import pytest

from rag.core.config import Settings
from rag.query import runtime_warmup
from rag.query.configuration.models import RagConfigRecord
from rag.query.runtime_warmup import QueryRuntimeWarmupError


def _settings() -> Settings:
    return Settings(
        rag_dense_cache_dir="/cache/dense",
        rag_sparse_model="Qdrant/bm25",
        rag_sparse_cache_dir="/cache/sparse",
        rag_reranker_cache_dir="/cache/reranker",
    )


def _rag_config(
    *, embedding_provider: str = "fastembed", faithfulness_policy: str = "adaptive"
) -> RagConfigRecord:
    return RagConfigRecord(
        base_url="http://models.test",
        chat_model="chat-model",
        embed_model="nomic-ai/nomic-embed-text-v1.5-Q",
        embedding_provider=embedding_provider,
        faithfulness_model=None,
        chat_timeout_seconds=2,
        embed_timeout_seconds=2,
        reranker_model="jinaai/jina-reranker-v1-turbo-en",
        faithfulness_policy=faithfulness_policy,
    )


def test_warmup_runs_actual_cached_query_inference_paths(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        runtime_warmup,
        "embed_dense_texts",
        lambda texts, **kwargs: calls.append(("dense", texts, kwargs)) or [[0.1]],
    )
    monkeypatch.setattr(
        runtime_warmup,
        "embed_sparse_text",
        lambda text, **kwargs: calls.append(("sparse", text, kwargs)) or object(),
    )
    monkeypatch.setattr(
        runtime_warmup,
        "rank_passages",
        lambda query, passages, **kwargs: (
            calls.append(("reranker", query, passages, kwargs)) or [(0, 1.0)]
        ),
    )
    monkeypatch.setattr(
        runtime_warmup,
        "score_entailment",
        lambda pairs, **kwargs: calls.append(("entailment", pairs, kwargs))
        or [object()],
    )
    caplog.set_level(logging.INFO, logger=runtime_warmup._LOG.name)

    runtime_warmup.warm_query_fastembed_runtime(
        app_settings=_settings(),
        rag_config=_rag_config(),
    )

    assert calls[:2] == [
        (
            "dense",
            ["query runtime readiness probe"],
            {
                "model_name": "nomic-ai/nomic-embed-text-v1.5-Q",
                "cache_dir": "/cache/dense",
            },
        ),
        (
            "sparse",
            "query runtime readiness probe",
            {"model_name": "Qdrant/bm25", "cache_dir": "/cache/sparse"},
        ),
    ]
    stage, query, passages, kwargs = calls[2]
    assert stage == "reranker"
    assert query == "query runtime readiness probe"
    assert isinstance(passages, list)
    assert len(passages) == 24
    assert all(len(passage) > len(query) for passage in passages)
    assert kwargs == {
        "model_name": "jinaai/jina-reranker-v1-turbo-en",
        "cache_dir": "/cache/reranker",
        "device": "auto",
    }
    assert calls[3] == (
        "entailment",
        [(runtime_warmup._PROBE_PASSAGE, "query runtime readiness probe")],
        {"cache_dir": "/cache/reranker"},
    )
    payload = caplog.records[-1].query_fastembed_runtime_warmup
    assert payload["status"] == "ready"
    assert set(payload["stage_timings_ms"]) == {
        "dense",
        "sparse",
        "reranker",
        "entailment",
    }
    assert payload["total_ms"] >= 0


def test_warmup_skips_dense_model_for_remote_embedding_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_warmup,
        "embed_dense_texts",
        lambda *_args, **_kwargs: pytest.fail("dense FastEmbed must be skipped"),
    )
    monkeypatch.setattr(
        runtime_warmup, "embed_sparse_text", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(
        runtime_warmup, "rank_passages", lambda *_args, **_kwargs: [(0, 1.0)]
    )
    monkeypatch.setattr(
        runtime_warmup, "score_entailment", lambda *_args, **_kwargs: [object()]
    )

    runtime_warmup.warm_query_fastembed_runtime(
        app_settings=_settings(),
        rag_config=_rag_config(embedding_provider="ollama"),
    )


def test_warmup_skips_entailment_when_adaptive_faithfulness_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_warmup, "embed_dense_texts", lambda *_a, **_k: [[0.1]])
    monkeypatch.setattr(runtime_warmup, "embed_sparse_text", lambda *_a, **_k: object())
    monkeypatch.setattr(runtime_warmup, "rank_passages", lambda *_a, **_k: [(0, 1.0)])
    monkeypatch.setattr(
        runtime_warmup,
        "score_entailment",
        lambda *_a, **_k: pytest.fail("entailment must be skipped"),
    )

    runtime_warmup.warm_query_fastembed_runtime(
        app_settings=_settings(),
        rag_config=_rag_config(faithfulness_policy="always"),
    )


def test_warmup_fails_clearly_when_offline_model_is_corrupt(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        runtime_warmup, "embed_dense_texts", lambda *_args, **_kwargs: [[0.1]]
    )

    def fail_sparse(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("ModelProto does not have a graph")

    monkeypatch.setattr(runtime_warmup, "embed_sparse_text", fail_sparse)
    monkeypatch.setattr(
        runtime_warmup,
        "rank_passages",
        lambda *_args, **_kwargs: pytest.fail("reranker must not run after failure"),
    )
    caplog.set_level(logging.ERROR, logger=runtime_warmup._LOG.name)

    with pytest.raises(
        QueryRuntimeWarmupError,
        match=r"sparse model 'Qdrant/bm25'.*'/cache/sparse'.*Seed or repair",
    ) as captured:
        runtime_warmup.warm_query_fastembed_runtime(
            app_settings=_settings(),
            rag_config=_rag_config(),
        )

    assert isinstance(captured.value.__cause__, RuntimeError)
    payload = caplog.records[-1].query_fastembed_runtime_warmup
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "sparse"
    assert payload["error_type"] == "RuntimeError"
    assert payload["total_ms"] >= 0
