from types import SimpleNamespace

import numpy as np

from rag.query.answering import entailment


class _Tokenizer:
    def encode_batch(self, pairs: list[tuple[str, str]]) -> list[SimpleNamespace]:
        return [SimpleNamespace(ids=[1, 2], attention_mask=[1, 1]) for _ in pairs]


class _Session:
    def run(self, *_args: object) -> list[np.ndarray]:
        return [np.asarray([[4.0, -2.0, -1.0], [-2.0, 4.0, -1.0]])]


def test_entailment_scores_preserve_contradiction_and_entailment_labels(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        entailment, "_load_runtime", lambda _cache_dir: (_Tokenizer(), _Session())
    )

    scores = entailment.score_entailment(
        [("premise", "false claim"), ("premise", "supported claim")],
        cache_dir="/models",
    )

    assert scores[0].contradiction > 0.99
    assert scores[1].entailment > 0.99
