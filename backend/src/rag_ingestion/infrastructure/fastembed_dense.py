"""Local dense FastEmbed adapter for ingestion embeddings."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from rag.shared.fastembed_dense import FastEmbedDenseError, embed_dense_texts

from ..errors import EmbeddingUnavailable


class FastEmbedDenseClient:
    def __init__(self, *, model_name: str, cache_dir: str | None, batch_size: int = 256) -> None:
        self.embed_model = model_name
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.batch_size = max(1, batch_size)

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(
        self,
        texts: Sequence[str],
        *,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        expected_dimension: int | None = None
        all_texts = list(texts)
        for offset in range(0, len(all_texts), self.batch_size):
            batch = all_texts[offset : offset + self.batch_size]
            try:
                batch_vectors = embed_dense_texts(
                    batch,
                    model_name=self.model_name,
                    cache_dir=self.cache_dir,
                    batch_size=self.batch_size,
                )
            except FastEmbedDenseError as exc:
                raise EmbeddingUnavailable(str(exc)[:500]) from exc
            for vector in batch_vectors:
                if expected_dimension is None:
                    expected_dimension = len(vector)
                elif len(vector) != expected_dimension:
                    raise EmbeddingUnavailable("Local dense embedding dimensions changed between batches.")
            vectors.extend(batch_vectors)
            if progress is not None:
                progress(len(vectors), len(all_texts))
        return vectors
