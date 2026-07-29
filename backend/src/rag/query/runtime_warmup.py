"""Process-local model warmup for the query runtime."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from time import perf_counter

from rag.core.config import Settings
from rag.shared.fastembed_dense import embed_dense_texts
from rag.shared.contracts.rag_defaults import DEFAULT_RERANKER_MAX_CANDIDATES
from rag.shared.contracts.reranker_models import reranker_passage_max_chars

from .configuration.models import RagConfigRecord
from .answering.entailment import ENTAILMENT_MODEL, score_entailment
from .reranker import rank_passages
from .sparse import embed_sparse_text

_LOG = logging.getLogger("uvicorn.error")
_PROBE_TEXT = "query runtime readiness probe"
_PROBE_PASSAGE = (
    "Representative enterprise document content for query runtime readiness. "
    "The passage includes enough text to initialize production reranker tensor shapes. "
) * 24


class QueryRuntimeWarmupError(RuntimeError):
    """Raised when a configured query-time FastEmbed model cannot run."""


def warm_query_fastembed_runtime(
    *,
    app_settings: Settings,
    rag_config: RagConfigRecord,
) -> None:
    """Load and inference-check the FastEmbed models used by this process."""

    total_started = perf_counter()
    stage_timings_ms: dict[str, int] = {}

    def warm_stage(
        stage: str,
        *,
        model_name: str,
        cache_dir: str | None,
        action: Callable[[], object],
    ) -> None:
        stage_started = perf_counter()
        try:
            action()
        except Exception as exc:
            stage_duration_ms = _duration_ms(stage_started)
            total_duration_ms = _duration_ms(total_started)
            log_payload = {
                "event": "rag.query_fastembed_warmup",
                "status": "failed",
                "failed_stage": stage,
                "failed_stage_duration_ms": stage_duration_ms,
                "stage_timings_ms": dict(stage_timings_ms),
                "total_ms": total_duration_ms,
                "model_name": model_name,
                "cache_dir": cache_dir,
                "error_type": type(exc).__name__,
            }
            _LOG.error(
                json.dumps(log_payload, sort_keys=True),
                extra={"query_fastembed_runtime_warmup": log_payload},
                exc_info=True,
            )
            cache_label = cache_dir or "<FastEmbed default cache>"
            raise QueryRuntimeWarmupError(
                "Query FastEmbed runtime warmup failed for "
                f"{stage} model {model_name!r} in cache {cache_label!r}: {exc}. "
                "Seed or repair the configured FastEmbed cache before starting "
                "the API in offline mode."
            ) from exc
        stage_timings_ms[stage] = _duration_ms(stage_started)

    if rag_config.embedding_provider == "fastembed":
        warm_stage(
            "dense",
            model_name=rag_config.embed_model,
            cache_dir=app_settings.rag_dense_cache_dir,
            action=lambda: embed_dense_texts(
                [_PROBE_TEXT],
                model_name=rag_config.embed_model,
                cache_dir=app_settings.rag_dense_cache_dir,
            ),
        )
    warm_stage(
        "sparse",
        model_name=app_settings.rag_sparse_model,
        cache_dir=app_settings.rag_sparse_cache_dir,
        action=lambda: embed_sparse_text(
            _PROBE_TEXT,
            model_name=app_settings.rag_sparse_model,
            cache_dir=app_settings.rag_sparse_cache_dir,
        ),
    )
    warm_stage(
        "reranker",
        model_name=rag_config.reranker_model,
        cache_dir=app_settings.rag_reranker_cache_dir,
        action=lambda: rank_passages(
            _PROBE_TEXT,
            _reranker_warmup_passages(
                rag_config.reranker_model,
                app_settings.rag_reranker_max_candidates,
            ),
            model_name=rag_config.reranker_model,
            cache_dir=app_settings.rag_reranker_cache_dir,
            device=app_settings.rag_reranker_device,
        ),
    )
    if rag_config.faithfulness_policy == "adaptive":
        warm_stage(
            "entailment",
            model_name=ENTAILMENT_MODEL,
            cache_dir=app_settings.rag_reranker_cache_dir,
            action=lambda: score_entailment(
                [(_PROBE_PASSAGE, _PROBE_TEXT)],
                cache_dir=app_settings.rag_reranker_cache_dir,
            ),
        )
    log_payload = {
        "event": "rag.query_fastembed_warmup",
        "status": "ready",
        "stage_timings_ms": stage_timings_ms,
        "total_ms": _duration_ms(total_started),
    }
    _LOG.info(
        json.dumps(log_payload, sort_keys=True),
        extra={"query_fastembed_runtime_warmup": log_payload},
    )


def _duration_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _reranker_warmup_passages(model_name: str, max_candidates: int) -> list[str]:
    passage = _PROBE_PASSAGE[:reranker_passage_max_chars(model_name)]
    count = min(max_candidates, DEFAULT_RERANKER_MAX_CANDIDATES)
    return [passage] * count
