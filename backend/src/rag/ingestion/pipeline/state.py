"""State and dependency contracts for the ingestion graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from ..adapters.backend import BackendInternalClient
from ..adapters.inference import IngestionInferenceClient
from ..adapters.storage import DocumentImageAssetWriter, UploadObjectReader
from ..adapters.vision import VisionClient
from ..indexing.qdrant import QdrantClient
from ..indexing.sparse import SparseEmbedder
from ..contracts import IngestJobPayload


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
    ingestion_quality_preset: str = "fast"
    weak_page_threshold: int = 5
    full_doc_weak_page_ratio: float = 0.25
    layered_docling_max_pages: int = 40
    layered_docling_max_page_ratio: float | None = None
    prefer_full_document_docling: bool = False
    layered_docling_batch_pages: int = 4
    pdf_image_analysis_max_images: int = -1
    pdf_image_analysis_max_full_page_fallbacks: int = -1
    pdf_image_review_threshold: int = 64
    scanned_visual_region_enabled: bool = True
    scanned_visual_min_area_ratio: float = 0.03
    scanned_visual_max_regions_per_page: int = -1
    scanned_visual_text_mask_padding_px: int = 8
    ocr_review_confidence_threshold: float = 0.9
    vision_layout_repair_enabled: bool = False

    @property
    def inference(self) -> IngestionInferenceClient:
        return self.ollama
