"""Environment configuration for the RAG ingestion worker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

TRUE_VALUES = {"1", "true", "yes", "on", "y"}
FALSE_VALUES = {"0", "false", "no", "off", "n"}
SUPPORTED_MODEL_PROVIDERS = {"mock", "ollama", "vllm"}
DEFAULT_OLLAMA_BASE_URL = "http://host.docker.internal:11434"
DEFAULT_TOPIC_TAXONOMY = (
    "procurement",
    "contracts",
    "hr_policy",
    "leave",
    "finance",
    "audit",
    "security",
    "it_policy",
    "operations",
    "logistics",
    "compliance",
    "legal",
    "training",
    "performance",
    "health_safety",
)


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
class ModelProviderConfig:
    provider: str
    ollama_base_url: str
    ollama_chat_model: str
    ollama_embed_model: str
    ollama_chat_timeout_seconds: float
    ollama_embed_timeout_seconds: float
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
    http_timeout_seconds: float
    heartbeat_interval_seconds: float
    ollama_retry_base_seconds: float
    ollama_num_ctx: int
    embedding_batch_size: int
    worker_boot_concurrency: int
    weak_page_threshold: int
    full_doc_weak_page_ratio: float
    layered_docling_max_pages: int
    layered_docling_batch_pages: int
    ocr_review_confidence_threshold: float
    native_text_min_chars_per_page: int
    chunk_target_tokens: int
    chunk_overlap_tokens: int
    parent_max_tokens: int
    metadata_use_gliner: bool
    topic_taxonomy: tuple[str, ...]
    mock: MockSwitches
    model_provider: ModelProviderConfig
    backend: BackendConfig
    minio: MinioConfig
    qdrant: QdrantConfig
    vision: VisionConfig

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        provider = os.getenv("RAG_MODEL_PROVIDER", "ollama").strip().lower()
        if provider not in SUPPORTED_MODEL_PROVIDERS:
            allowed = ", ".join(sorted(SUPPORTED_MODEL_PROVIDERS))
            raise ValueError(f"RAG_MODEL_PROVIDER must be one of {allowed}")

        global_enabled = parse_bool(os.getenv("ENABLE_MOCK_MODELS"), provider == "mock")
        http_timeout = float(os.getenv("RAG_HTTP_TIMEOUT_SECONDS", "45"))
        return cls(
            redis_url=os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://redis:6379/0")),
            ingest_queue_name=os.getenv("INGEST_QUEUE_NAME", "ingest:jobs"),
            http_timeout_seconds=http_timeout,
            heartbeat_interval_seconds=float(os.getenv("INGEST_HEARTBEAT_INTERVAL_SECONDS", "30")),
            ollama_retry_base_seconds=float(os.getenv("OLLAMA_RETRY_BASE_SECONDS", "2")),
            ollama_num_ctx=_bounded_int("OLLAMA_NUM_CTX", 16384, minimum=1024, maximum=262144),
            embedding_batch_size=max(1, int(os.getenv("OLLAMA_EMBED_BATCH_SIZE", "16"))),
            worker_boot_concurrency=max(1, min(10, int(os.getenv("INGEST_WORKER_BOOT_CONCURRENCY", "1")))),
            weak_page_threshold=int(os.getenv("PDF_WEAK_PAGE_THRESHOLD", "5")),
            full_doc_weak_page_ratio=float(os.getenv("PDF_FULL_DOC_WEAK_PAGE_RATIO", "0.25")),
            layered_docling_max_pages=max(1, int(os.getenv("LAYERED_DOCLING_MAX_PAGES", "40"))),
            layered_docling_batch_pages=max(1, int(os.getenv("LAYERED_DOCLING_BATCH_PAGES", "4"))),
            ocr_review_confidence_threshold=float(os.getenv("OCR_REVIEW_CONFIDENCE_THRESHOLD", "0.9")),
            native_text_min_chars_per_page=int(os.getenv("NATIVE_TEXT_MIN_CHARS_PER_PAGE", "10")),
            chunk_target_tokens=_token_setting("RAG_CHUNK_TARGET_TOKENS", "RAG_CHUNK_MAX_CHARS", 512),
            chunk_overlap_tokens=_token_setting("RAG_CHUNK_OVERLAP_TOKENS", "RAG_CHUNK_OVERLAP_CHARS", 64),
            parent_max_tokens=int(os.getenv("RAG_PARENT_MAX_TOKENS", "2048")),
            metadata_use_gliner=parse_bool(os.getenv("METADATA_USE_GLINER"), False),
            topic_taxonomy=_topic_taxonomy(os.getenv("METADATA_TOPIC_TAXONOMY")),
            mock=MockSwitches(
                global_enabled=global_enabled,
                llm=parse_bool(os.getenv("MOCK_LLM"), global_enabled),
                embeddings=parse_bool(os.getenv("MOCK_EMBEDDINGS"), global_enabled),
                ocr=parse_bool(os.getenv("MOCK_OCR"), global_enabled),
            ),
            model_provider=ModelProviderConfig(
                provider=provider,
                ollama_base_url=os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
                ollama_chat_model=os.getenv("OLLAMA_CHAT_MODEL", "llama3.1:8b"),
                ollama_embed_model=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest"),
                ollama_chat_timeout_seconds=float(os.getenv("RAG_OLLAMA_CHAT_TIMEOUT_SECONDS", "180")),
                ollama_embed_timeout_seconds=float(os.getenv("RAG_OLLAMA_EMBED_TIMEOUT_SECONDS", str(http_timeout))),
                sparse_model=os.getenv("RAG_SPARSE_MODEL", "Qdrant/bm25"),
                sparse_cache_dir=os.getenv("RAG_SPARSE_CACHE_DIR", "/models/fastembed"),
            ),
            backend=BackendConfig(
                internal_url=os.getenv("BACKEND_INTERNAL_URL", "http://api:8000"),
                service_token=os.getenv("SERVICE_TOKEN", os.getenv("BACKEND_SERVICE_TOKEN", "")),
            ),
            minio=MinioConfig(
                endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000"),
                access_key=os.getenv("MINIO_ACCESS_KEY", "agenticrag"),
                secret_key=os.getenv("MINIO_SECRET_KEY", "agenticrag-local-minio-password"),
                bucket=os.getenv("MINIO_BUCKET", "agenticrag-uploads"),
                secure=parse_bool(os.getenv("MINIO_SECURE"), False),
            ),
            qdrant=QdrantConfig(
                url=os.getenv("QDRANT_URL", "http://qdrant:6333"),
                collection=os.getenv("QDRANT_COLLECTION", "documents"),
                upsert_batch_size=max(1, int(os.getenv("QDRANT_UPSERT_BATCH_SIZE", "64"))),
            ),
            vision=VisionConfig(
                base_url=os.getenv("VLLM_VISION_BASE_URL", "").strip(),
                model=os.getenv("VLLM_VISION_MODEL_ID", os.getenv("VLLM_VISION_MODEL", "vision")).strip(),
                ollama_model=os.getenv("OLLAMA_VISION_MODEL", "").strip(),
                ollama_num_ctx=_bounded_int("OLLAMA_VISION_NUM_CTX", 8192, minimum=1024, maximum=262144),
            ),
        )


def redact_url(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value.split("?", 1)[0].split("#", 1)[0]
    netloc = parsed.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _token_setting(name: str, legacy_name: str, default: int) -> int:
    value = os.getenv(name)
    if value:
        return int(value)
    legacy = os.getenv(legacy_name)
    return max(1, int(legacy) // 4) if legacy else default


def _bounded_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    return max(minimum, min(maximum, value))


def _topic_taxonomy(value: str | None) -> tuple[str, ...]:
    if not value:
        return DEFAULT_TOPIC_TAXONOMY
    topics = tuple(topic.strip() for topic in value.split(",") if topic.strip())
    return topics or DEFAULT_TOPIC_TAXONOMY
