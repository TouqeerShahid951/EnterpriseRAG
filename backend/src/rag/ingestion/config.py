"""Environment configuration for the RAG ingestion worker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from math import isfinite

from rag.shared.contracts.rag_defaults import (
    DEFAULT_FASTEMBED_CACHE_DIR,
    DEFAULT_GRAPHRAG_ENABLED,
    DEFAULT_MODEL_PROVIDER,
    DEFAULT_OLLAMA_NUM_CTX,
    DEFAULT_OLLAMA_VISION_NUM_CTX,
    DEFAULT_RAG_HTTP_TIMEOUT_SECONDS,
    DEFAULT_SPARSE_MODEL,
    DEFAULT_VLLM_VISION_MODEL_ID,
    SUPPORTED_WORKER_MODEL_PROVIDERS,
)
from rag.shared.contracts.task_names import (
    DEFAULT_GRAPHRAG_INDEX_TASK_NAME,
    DEFAULT_GRAPHRAG_PARTITION_REBUILD_TASK_NAME,
    DEFAULT_INGEST_TASK_NAME,
    normalize_task_name,
    validate_document_pipeline_task_names,
)

from .quality import (
    DEFAULT_INGESTION_QUALITY_PRESET,
    normalize_ingestion_quality_preset,
)

TRUE_VALUES = {"1", "true", "yes", "on", "y"}
FALSE_VALUES = {"0", "false", "no", "off", "n"}
SUPPORTED_MODEL_PROVIDERS = frozenset(SUPPORTED_WORKER_MODEL_PROVIDERS)
DEFAULT_TOPIC_TAXONOMY: tuple[str, ...] = ()
DEFAULT_DOCLING_CONVERT_TIMEOUT_SECONDS = 180.0


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"Expected a boolean-like value, got {value!r}")


@dataclass(frozen=True)
class MockSwitches:
    global_enabled: bool
    llm: bool
    embeddings: bool
    ocr: bool


@dataclass(frozen=True)
class LocalEmbeddingConfig:
    dense_cache_dir: str | None
    sparse_model: str
    sparse_cache_dir: str | None


@dataclass(frozen=True)
class BackendConfig:
    internal_url: str
    service_token: str


@dataclass(frozen=True)
class MinioConfig:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool


@dataclass(frozen=True)
class QdrantConfig:
    url: str
    collection: str
    upsert_batch_size: int


@dataclass(frozen=True)
class VisionConfig:
    base_url: str
    model: str
    ollama_model: str
    ollama_num_ctx: int


@dataclass(frozen=True)
class WorkerConfig:
    redis_url: str
    ingest_queue_name: str
    graphrag_queue_name: str
    graphrag_enabled: bool
    graphrag_community_collection: str
    graphrag_extraction_concurrency: int
    graphrag_summary_concurrency: int
    graphrag_summarize_after_document: bool
    graphrag_partition_rebuild_delay_seconds: int
    graphrag_max_chunks_per_doc: int
    graphrag_min_chunk_chars: int
    graphrag_extraction_checkpoint_ttl_seconds: int
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_database: str
    http_timeout_seconds: float
    docling_convert_timeout_seconds: float
    heartbeat_interval_seconds: float
    ingest_stale_after_seconds: float
    ollama_retry_base_seconds: float
    ollama_num_ctx: int
    embedding_batch_size: int
    worker_boot_concurrency: int
    weak_page_threshold: int
    full_doc_weak_page_ratio: float
    layered_docling_max_pages: int
    layered_docling_batch_pages: int
    pdf_image_analysis_max_images: int
    pdf_image_analysis_max_full_page_fallbacks: int
    pdf_image_review_threshold: int
    scanned_visual_region_enabled: bool
    scanned_visual_min_area_ratio: float
    scanned_visual_max_regions_per_page: int
    scanned_visual_text_mask_padding_px: int
    ocr_review_confidence_threshold: float
    native_text_min_chars_per_page: int
    chunk_target_tokens: int
    chunk_overlap_tokens: int
    parent_max_tokens: int
    metadata_use_gliner: bool
    topic_taxonomy: tuple[str, ...]
    mock: MockSwitches
    local_embeddings: LocalEmbeddingConfig
    backend: BackendConfig
    minio: MinioConfig
    qdrant: QdrantConfig
    vision: VisionConfig
    ingestion_quality_preset: str = DEFAULT_INGESTION_QUALITY_PRESET
    ingest_task_name: str = DEFAULT_INGEST_TASK_NAME
    graphrag_index_task_name: str = DEFAULT_GRAPHRAG_INDEX_TASK_NAME
    graphrag_partition_rebuild_task_name: str = (
        DEFAULT_GRAPHRAG_PARTITION_REBUILD_TASK_NAME
    )

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        provider = (
            os.getenv("RAG_MODEL_PROVIDER", DEFAULT_MODEL_PROVIDER).strip().lower()
        )
        if provider not in SUPPORTED_MODEL_PROVIDERS:
            allowed = ", ".join(sorted(SUPPORTED_MODEL_PROVIDERS))
            raise ValueError(f"RAG_MODEL_PROVIDER must be one of {allowed}")

        ingest_task_name = normalize_task_name(
            "INGEST_TASK_NAME",
            os.getenv("INGEST_TASK_NAME", DEFAULT_INGEST_TASK_NAME),
        )
        graphrag_index_task_name = normalize_task_name(
            "GRAPHRAG_INDEX_TASK_NAME",
            os.getenv(
                "GRAPHRAG_INDEX_TASK_NAME",
                DEFAULT_GRAPHRAG_INDEX_TASK_NAME,
            ),
        )
        graphrag_partition_rebuild_task_name = normalize_task_name(
            "GRAPHRAG_PARTITION_REBUILD_TASK_NAME",
            os.getenv(
                "GRAPHRAG_PARTITION_REBUILD_TASK_NAME",
                DEFAULT_GRAPHRAG_PARTITION_REBUILD_TASK_NAME,
            ),
        )
        validate_document_pipeline_task_names(
            ingest=ingest_task_name,
            graphrag_index=graphrag_index_task_name,
            graphrag_partition_rebuild=graphrag_partition_rebuild_task_name,
        )

        global_enabled = parse_bool(os.getenv("ENABLE_MOCK_MODELS"), provider == "mock")
        http_timeout = _bounded_float(
            "RAG_HTTP_TIMEOUT_SECONDS",
            DEFAULT_RAG_HTTP_TIMEOUT_SECONDS,
            minimum=0.0,
            minimum_inclusive=False,
        )
        return cls(
            redis_url=os.getenv(
                "CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://redis:6379/0")
            ),
            ingest_queue_name=os.getenv("INGEST_QUEUE_NAME", "ingest:jobs"),
            graphrag_queue_name=os.getenv("GRAPHRAG_QUEUE_NAME", "graphrag:jobs"),
            ingest_task_name=ingest_task_name,
            graphrag_index_task_name=graphrag_index_task_name,
            graphrag_partition_rebuild_task_name=(
                graphrag_partition_rebuild_task_name
            ),
            graphrag_enabled=parse_bool(
                os.getenv("GRAPHRAG_ENABLED"), DEFAULT_GRAPHRAG_ENABLED
            ),
            graphrag_community_collection=os.getenv(
                "GRAPHRAG_COMMUNITY_COLLECTION", "graphrag_community_summaries"
            ),
            graphrag_extraction_concurrency=_bounded_int(
                "GRAPHRAG_EXTRACTION_CONCURRENCY",
                2,
                minimum=1,
                maximum=32,
            ),
            graphrag_summary_concurrency=_bounded_int(
                "GRAPHRAG_SUMMARY_CONCURRENCY",
                2,
                minimum=1,
                maximum=16,
            ),
            graphrag_summarize_after_document=parse_bool(
                os.getenv("GRAPHRAG_SUMMARIZE_AFTER_DOCUMENT"), False
            ),
            graphrag_partition_rebuild_delay_seconds=_bounded_int(
                "GRAPHRAG_PARTITION_REBUILD_DELAY_SECONDS",
                60,
                minimum=0,
                maximum=3600,
            ),
            graphrag_max_chunks_per_doc=_bounded_int(
                "GRAPHRAG_MAX_CHUNKS_PER_DOC",
                0,
                minimum=0,
                maximum=10000,
            ),
            graphrag_min_chunk_chars=_bounded_int(
                "GRAPHRAG_MIN_CHUNK_CHARS",
                80,
                minimum=0,
                maximum=2000,
            ),
            graphrag_extraction_checkpoint_ttl_seconds=_bounded_int(
                "GRAPHRAG_EXTRACTION_CHECKPOINT_TTL_SECONDS",
                86400,
                minimum=60,
                maximum=604800,
            ),
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv(
                "NEO4J_PASSWORD", "agenticrag-local-neo4j-password"
            ),
            neo4j_database=os.getenv("NEO4J_DATABASE", "neo4j"),
            http_timeout_seconds=http_timeout,
            docling_convert_timeout_seconds=_bounded_float(
                "DOCLING_CONVERT_TIMEOUT_SECONDS",
                DEFAULT_DOCLING_CONVERT_TIMEOUT_SECONDS,
                minimum=0.0,
            ),
            heartbeat_interval_seconds=_bounded_float(
                "INGEST_HEARTBEAT_INTERVAL_SECONDS",
                30.0,
                minimum=0.0,
                minimum_inclusive=False,
            ),
            ingest_stale_after_seconds=_bounded_float(
                "INGEST_STALE_AFTER_SECONDS",
                120.0,
                minimum=0.0,
                minimum_inclusive=False,
            ),
            ollama_retry_base_seconds=_bounded_float(
                "OLLAMA_RETRY_BASE_SECONDS",
                2.0,
                minimum=0.0,
            ),
            ollama_num_ctx=_bounded_int(
                "OLLAMA_NUM_CTX",
                DEFAULT_OLLAMA_NUM_CTX,
                minimum=1024,
                maximum=262144,
            ),
            embedding_batch_size=_bounded_int("OLLAMA_EMBED_BATCH_SIZE", 16, minimum=1),
            worker_boot_concurrency=_bounded_int(
                "INGEST_WORKER_BOOT_CONCURRENCY",
                1,
                minimum=1,
                maximum=10,
            ),
            ingestion_quality_preset=normalize_ingestion_quality_preset(
                os.getenv("INGESTION_QUALITY_PRESET", DEFAULT_INGESTION_QUALITY_PRESET)
            ),
            weak_page_threshold=_bounded_int("PDF_WEAK_PAGE_THRESHOLD", 5, minimum=0),
            full_doc_weak_page_ratio=_bounded_float(
                "PDF_FULL_DOC_WEAK_PAGE_RATIO",
                0.25,
                minimum=0.0,
                maximum=1.0,
            ),
            layered_docling_max_pages=_bounded_int(
                "LAYERED_DOCLING_MAX_PAGES", 40, minimum=1
            ),
            layered_docling_batch_pages=_bounded_int(
                "LAYERED_DOCLING_BATCH_PAGES", 4, minimum=1
            ),
            pdf_image_analysis_max_images=_bounded_int(
                "PDF_IMAGE_ANALYSIS_MAX_IMAGES", -1, minimum=-1
            ),
            pdf_image_analysis_max_full_page_fallbacks=_bounded_int(
                "PDF_IMAGE_ANALYSIS_MAX_FULL_PAGE_FALLBACKS",
                -1,
                minimum=-1,
            ),
            pdf_image_review_threshold=_bounded_int(
                "PDF_IMAGE_REVIEW_THRESHOLD",
                64,
                minimum=0,
                maximum=10000,
            ),
            scanned_visual_region_enabled=parse_bool(
                os.getenv("SCANNED_VISUAL_REGION_ENABLED"), True
            ),
            scanned_visual_min_area_ratio=_bounded_float(
                "SCANNED_VISUAL_MIN_AREA_RATIO",
                0.03,
                minimum=0.0,
                maximum=1.0,
            ),
            scanned_visual_max_regions_per_page=_bounded_int(
                "SCANNED_VISUAL_MAX_REGIONS_PER_PAGE",
                -1,
                minimum=-1,
            ),
            scanned_visual_text_mask_padding_px=_bounded_int(
                "SCANNED_VISUAL_TEXT_MASK_PADDING_PX",
                8,
                minimum=0,
            ),
            ocr_review_confidence_threshold=_bounded_float(
                "OCR_REVIEW_CONFIDENCE_THRESHOLD",
                0.9,
                minimum=0.0,
                maximum=1.0,
            ),
            native_text_min_chars_per_page=_bounded_int(
                "NATIVE_TEXT_MIN_CHARS_PER_PAGE", 10, minimum=0
            ),
            chunk_target_tokens=_token_setting(
                "RAG_CHUNK_TARGET_TOKENS",
                "RAG_CHUNK_MAX_CHARS",
                512,
                minimum=1,
            ),
            chunk_overlap_tokens=_token_setting(
                "RAG_CHUNK_OVERLAP_TOKENS",
                "RAG_CHUNK_OVERLAP_CHARS",
                64,
                minimum=0,
            ),
            parent_max_tokens=_bounded_int("RAG_PARENT_MAX_TOKENS", 2048, minimum=1),
            metadata_use_gliner=parse_bool(os.getenv("METADATA_USE_GLINER"), False),
            topic_taxonomy=_topic_taxonomy(os.getenv("METADATA_TOPIC_TAXONOMY")),
            mock=MockSwitches(
                global_enabled=global_enabled,
                llm=parse_bool(os.getenv("MOCK_LLM"), global_enabled),
                embeddings=parse_bool(os.getenv("MOCK_EMBEDDINGS"), global_enabled),
                ocr=parse_bool(os.getenv("MOCK_OCR"), global_enabled),
            ),
            local_embeddings=LocalEmbeddingConfig(
                dense_cache_dir=os.getenv(
                    "RAG_DENSE_CACHE_DIR", DEFAULT_FASTEMBED_CACHE_DIR
                ),
                sparse_model=os.getenv("RAG_SPARSE_MODEL", DEFAULT_SPARSE_MODEL),
                sparse_cache_dir=os.getenv(
                    "RAG_SPARSE_CACHE_DIR", DEFAULT_FASTEMBED_CACHE_DIR
                ),
            ),
            backend=BackendConfig(
                internal_url=os.getenv("BACKEND_INTERNAL_URL", "http://api:8000"),
                service_token=os.getenv(
                    "SERVICE_TOKEN", os.getenv("BACKEND_SERVICE_TOKEN", "")
                ),
            ),
            minio=MinioConfig(
                endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000"),
                access_key=os.getenv("MINIO_ACCESS_KEY", "agenticrag"),
                secret_key=os.getenv(
                    "MINIO_SECRET_KEY", "agenticrag-local-minio-password"
                ),
                bucket=os.getenv("MINIO_BUCKET", "agenticrag-uploads"),
                secure=parse_bool(os.getenv("MINIO_SECURE"), False),
            ),
            qdrant=QdrantConfig(
                url=os.getenv("QDRANT_URL", "http://qdrant:6333"),
                collection=os.getenv("QDRANT_COLLECTION", "documents"),
                upsert_batch_size=_bounded_int(
                    "QDRANT_UPSERT_BATCH_SIZE", 64, minimum=1
                ),
            ),
            vision=VisionConfig(
                base_url=os.getenv("VLLM_VISION_BASE_URL", "").strip(),
                model=os.getenv(
                    "VLLM_VISION_MODEL_ID",
                    os.getenv("VLLM_VISION_MODEL", DEFAULT_VLLM_VISION_MODEL_ID),
                ).strip(),
                ollama_model=os.getenv("OLLAMA_VISION_MODEL", "").strip(),
                ollama_num_ctx=_bounded_int(
                    "OLLAMA_VISION_NUM_CTX",
                    DEFAULT_OLLAMA_VISION_NUM_CTX,
                    minimum=1024,
                    maximum=262144,
                ),
            ),
        )


def _token_setting(name: str, legacy_name: str, default: int, *, minimum: int) -> int:
    value = os.getenv(name)
    if value:
        return _validate_int(name, value, minimum=minimum)
    legacy = os.getenv(legacy_name)
    if legacy:
        legacy_value = _validate_int(legacy_name, legacy, minimum=0)
        return _validate_int(name, legacy_value // 4, minimum=minimum)
    return default


def _bounded_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    return _validate_int(
        name, os.getenv(name, str(default)), minimum=minimum, maximum=maximum
    )


def _validate_int(
    name: str,
    raw_value: str | int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer, got {raw_value!r}") from exc
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}, got {value}")
    return value


def _bounded_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    minimum_inclusive: bool = True,
) -> float:
    raw_value = os.getenv(name, str(default))
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric, got {raw_value!r}") from exc
    if not isfinite(value):
        raise ValueError(f"{name} must be finite, got {raw_value!r}")
    below_minimum = minimum is not None and (
        value < minimum if minimum_inclusive else value <= minimum
    )
    if below_minimum:
        comparison = "at least" if minimum_inclusive else "greater than"
        raise ValueError(f"{name} must be {comparison} {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}, got {value}")
    return value


def _topic_taxonomy(value: str | None) -> tuple[str, ...]:
    if not value:
        return DEFAULT_TOPIC_TAXONOMY
    topics = tuple(topic.strip() for topic in value.split(",") if topic.strip())
    return topics
