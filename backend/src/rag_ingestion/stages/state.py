"""State and dependency contracts for the ingestion graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from ..infrastructure.backend import BackendInternalClient
from ..infrastructure.inference import IngestionInferenceClient
from ..infrastructure.storage import DocumentImageAssetWriter, UploadObjectReader
from ..infrastructure.vision import VisionClient
from ..indexing.qdrant import QdrantClient
from ..indexing.sparse import SparseEmbedder
from ..messages import IngestJobPayload


class IngestState(TypedDict, total=False):
    payload: IngestJobPayload
    file_bytes: bytes
    parsed_items: list[Any]
    parser_provenance: dict[str, Any]
    metadata: dict[str, Any]
    chunks: list[Any]
    claims: list[dict[str, str]]
    conflicted_claim_ids: list[str]
    vectors: list[list[float]]
    sparse_vectors: list[Any]
    points: list[dict[str, Any]]
    upsert_count: int
    warnings: list[str]


@dataclass(frozen=True)
class IngestDependencies:
    backend: BackendInternalClient
    storage: UploadObjectReader
    image_asset_writer: DocumentImageAssetWriter
    ollama: IngestionInferenceClient
    vision: VisionClient
    sparse_embedder: SparseEmbedder
    qdrant: QdrantClient
    min_chars_per_page: int
    chunk_target_tokens: int
    chunk_overlap_tokens: int
    parent_max_tokens: int
    metadata_use_gliner: bool = False
    topic_taxonomy: tuple[str, ...] = ()
    weak_page_threshold: int = 5
    full_doc_weak_page_ratio: float = 0.25
    layered_docling_max_pages: int = 40
    layered_docling_batch_pages: int = 4
    ocr_review_confidence_threshold: float = 0.9

    @property
    def inference(self) -> IngestionInferenceClient:
        return self.ollama
