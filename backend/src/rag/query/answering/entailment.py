"""Local natural-language inference for adaptive claim verification."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from rag.shared.runtime_offline import apply_runtime_offline_defaults

ENTAILMENT_MODEL = "Xenova/nli-deberta-v3-xsmall"
ENTAILMENT_MODEL_FILE = "onnx/model_int8.onnx"
ENTAILMENT_THRESHOLD = 0.9
_MODEL_FILES = (
    "added_tokens.json",
    "config.json",
    ENTAILMENT_MODEL_FILE,
    "special_tokens_map.json",
    "spm.model",
    "tokenizer.json",
    "tokenizer_config.json",
)
_MAX_TOKENS = 512


@dataclass(frozen=True)
class EntailmentScore:
    contradiction: float
    entailment: float
    neutral: float


def score_entailment(
    pairs: list[tuple[str, str]], *, cache_dir: str | None
) -> list[EntailmentScore]:
    """Score (evidence premise, answer claim) pairs without downloading at runtime."""
    if not pairs:
        return []
    tokenizer, session = _load_runtime(cache_dir)
    encodings = tokenizer.encode_batch(pairs)

    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("local entailment requires the FastEmbed runtime") from exc

    inputs = {
        "input_ids": np.asarray([item.ids for item in encodings], dtype=np.int64),
        "attention_mask": np.asarray(
            [item.attention_mask for item in encodings], dtype=np.int64
        ),
    }
    logits = np.asarray(session.run(None, inputs)[0], dtype=np.float64)
    if logits.shape != (len(pairs), 3):
        raise RuntimeError("entailment model returned an unexpected output shape")
    probabilities = np.exp(logits - logits.max(axis=1, keepdims=True))
    probabilities /= probabilities.sum(axis=1, keepdims=True)
    return [
        EntailmentScore(
            contradiction=float(row[0]),
            entailment=float(row[1]),
            neutral=float(row[2]),
        )
        for row in probabilities
    ]


def prewarm_entailment_model(cache_dir: Path) -> None:
    """Download and inference-check the model while preparing an offline cache."""
    _snapshot_path(str(cache_dir), local_files_only=False)
    score_entailment(
        [("The policy permits remote work.", "Remote work is permitted.")],
        cache_dir=str(cache_dir),
    )


@lru_cache(maxsize=4)
def _load_runtime(cache_dir: str | None) -> tuple[Any, Any]:
    apply_runtime_offline_defaults()
    try:
        import onnxruntime
        from tokenizers import Tokenizer
    except ImportError as exc:
        raise RuntimeError("local entailment requires the FastEmbed runtime") from exc

    snapshot = _snapshot_path(cache_dir, local_files_only=True)
    tokenizer = Tokenizer.from_file(str(snapshot / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=_MAX_TOKENS)
    tokenizer.enable_padding()
    session = onnxruntime.InferenceSession(
        str(snapshot / ENTAILMENT_MODEL_FILE),
        providers=["CPUExecutionProvider"],
    )
    return tokenizer, session


def _snapshot_path(cache_dir: str | None, *, local_files_only: bool) -> Path:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("local entailment requires the FastEmbed runtime") from exc
    try:
        path = snapshot_download(
            repo_id=ENTAILMENT_MODEL,
            cache_dir=cache_dir,
            allow_patterns=list(_MODEL_FILES),
            local_files_only=local_files_only,
        )
    except Exception as exc:
        raise RuntimeError(
            f"entailment model {ENTAILMENT_MODEL!r} is unavailable in cache "
            f"{cache_dir or '<default>'!r}"
        ) from exc
    return Path(path)
