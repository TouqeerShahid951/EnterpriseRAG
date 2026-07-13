"""Transport-neutral contracts for authorized corpus retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from ..auth.context import UserContext


@dataclass(frozen=True, slots=True)
class AuthorizedCorpusRequest:
    trace_id: str
    session_id: str
    query: str
    user: UserContext
    group_path: str | None
    document_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_ids", tuple(self.document_ids))


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    point_id: str
    doc_id: str
    doc_title: str
    chunk_id: str
    page_start: int | None
    page_end: int | None
    content_type: str
    text: str
    structured_fields: tuple[tuple[str, str], ...]
    retrieval_score: float
    rerank_score: float | None
    identity_keys: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "structured_fields",
            tuple(tuple(field) for field in self.structured_fields),
        )
        identity_keys = set(self.identity_keys)
        identity_keys.add(f"chunk:{self.chunk_id}")
        normalized_text = " ".join(self.text.strip().lower().split())
        if normalized_text:
            identity_keys.add(f"text:{sha256(normalized_text.encode()).hexdigest()}")
        object.__setattr__(self, "identity_keys", frozenset(identity_keys))


class AuthorizedCorpusRetriever(Protocol):
    """Return only corpus chunks visible within the supplied authorization scope."""

    def search(
        self, request: AuthorizedCorpusRequest
    ) -> tuple[RetrievedChunk, ...]: ...

    def scan_documents(
        self,
        request: AuthorizedCorpusRequest,
        *,
        structured_only: bool,
        limit: int,
    ) -> tuple[RetrievedChunk, ...]: ...
