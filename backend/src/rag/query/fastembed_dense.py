"""Query-time local dense embeddings backed by FastEmbed."""

from __future__ import annotations

from rag.shared.fastembed_dense import FastEmbedDenseError, embed_dense_texts

from .cancellation import QueryCancellationToken
from .http import ServiceRequestError


class FastEmbedDenseEmbeddingClient:
    def __init__(self, *, model_name: str, cache_dir: str | None, batch_size: int = 256) -> None:
        self.embed_model = model_name
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.batch_size = max(1, batch_size)

    def embed(self, text: str, *, cancellation_token: QueryCancellationToken | None = None) -> list[float]:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        try:
            vector = embed_dense_texts(
                [text],
                model_name=self.model_name,
                cache_dir=self.cache_dir,
                batch_size=self.batch_size,
            )[0]
        except FastEmbedDenseError as exc:
            raise ServiceRequestError("fastembed", str(exc), 502) from exc
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        return vector
