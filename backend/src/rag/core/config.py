from functools import lru_cache

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from rag.shared.contracts.rag_defaults import (
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_EMBEDDINGS_BASE_URL,
    DEFAULT_EVIDENCE_GATE_POLICY,
    DEFAULT_FAITHFULNESS_MODEL,
    DEFAULT_FAITHFULNESS_POLICY,
    DEFAULT_FAITHFULNESS_TIMEOUT_SECONDS,
    DEFAULT_FASTEMBED_CACHE_DIR,
    DEFAULT_FASTEMBED_DENSE_MODEL,
    DEFAULT_GRAPHRAG_ENABLED,
    DEFAULT_HYBRID_DISAGREEMENT_DETECTOR_ENABLED,
    DEFAULT_JSON_NUM_PREDICT,
    DEFAULT_MODEL_PROVIDER,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_CHAT_MODEL,
    DEFAULT_OLLAMA_CHAT_TIMEOUT_SECONDS,
    DEFAULT_OLLAMA_EMBED_MODEL,
    DEFAULT_OLLAMA_EMBED_TIMEOUT_SECONDS,
    DEFAULT_OLLAMA_NUM_CTX,
    DEFAULT_QUERY_PLANNER_ENABLED,
    DEFAULT_QUERY_REWRITE_LLM_ENABLED,
    DEFAULT_RAG_HTTP_TIMEOUT_SECONDS,
    DEFAULT_RERANKER_MAX_CANDIDATES,
    DEFAULT_RERANKER_DEVICE,
    DEFAULT_RERANKER_MODEL,
    DEFAULT_RERANKER_TIMEOUT_SECONDS,
    DEFAULT_REASONING_MODEL,
    DEFAULT_REASONING_TIMEOUT_SECONDS,
    DEFAULT_RETRIEVAL_MAX_RETRIES,
    DEFAULT_RETRIEVAL_TOKEN_BUDGET,
    DEFAULT_ROUTING_MODEL,
    DEFAULT_ROUTING_TIMEOUT_SECONDS,
    DEFAULT_SPARSE_MODEL,
    DEFAULT_TOP_K,
    DEFAULT_VLLM_BASE_URL,
    DEFAULT_VLLM_CHAT_MODEL,
    DEFAULT_VLLM_VISION_MODEL_ID,
    EmbeddingProvider,
    EvidenceGatePolicy,
    FaithfulnessPolicy,
    InferenceProvider,
    RerankerDevice,
)
from rag.shared.contracts.task_names import (
    DEFAULT_ARTIFACT_TASK_NAME,
    DEFAULT_EVALUATION_TASK_NAME,
    DEFAULT_GRAPHRAG_INDEX_TASK_NAME,
    DEFAULT_GRAPHRAG_PARTITION_REBUILD_TASK_NAME,
    DEFAULT_INGEST_TASK_NAME,
    normalize_task_name,
    validate_document_pipeline_task_names,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_name: str = "AgenticRAG Backend"
    api_version: str = "0.0.0"
    public_api_prefix: str = "/api/v1"
    internal_api_prefix: str = "/internal"
    backend_internal_url: str = "http://api:8000"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    backend_cors_origins: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "http://localhost:5173,"
        "http://127.0.0.1:5173"
    )
    service_token: str = "replace-with-local-service-token"
    deployment_controller_url: str = "http://deployment-controller:8080"
    deployment_controller_token: str = "replace-with-local-deployment-controller-token"
    deployment_controller_timeout_seconds: float = Field(
        default=930.0,
        gt=0,
        le=1800,
    )
    jwt_secret_key: str = "replace-with-local-jwt-secret"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 7
    auth_idle_timeout_minutes: int = 30
    access_cookie_name: str = "agenticrag_access_token"
    refresh_cookie_name: str = "agenticrag_refresh_token"
    csrf_cookie_name: str = "csrf_token"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    bootstrap_admin_email: str = "admin@prudentia.ai"
    bootstrap_admin_name: str = "Platform Administrator"
    bootstrap_admin_password: str = Field(default="12345678", min_length=8)
    identity_repository: str = "postgres"
    document_repository: str = "postgres"
    refresh_session_store: str = "redis"
    refresh_session_prefix: str = "auth:refresh"
    database_url: str = (
        "postgresql://agenticrag:agenticrag-local-password@postgres:5432/agenticrag"
    )
    redis_url: str = "redis://:agenticrag-local-redis-password@redis:6379/0"
    celery_broker_url: str | None = None
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "documents"
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "agenticrag-local-neo4j-password"
    neo4j_database: str = "neo4j"
    graphrag_enabled: bool = DEFAULT_GRAPHRAG_ENABLED
    graphrag_community_collection: str = "graphrag_community_summaries"
    rag_model_provider: InferenceProvider = DEFAULT_MODEL_PROVIDER
    rag_embedding_provider: EmbeddingProvider = DEFAULT_EMBEDDING_PROVIDER
    rag_chat_provider: InferenceProvider | None = None
    rag_reasoning_provider: InferenceProvider | None = None
    rag_routing_provider: InferenceProvider | None = None
    rag_faithfulness_provider: InferenceProvider | None = None
    rag_ingestion_provider: InferenceProvider | None = None
    rag_vision_provider: InferenceProvider | None = None
    rag_chat_base_url: str | None = None
    rag_reasoning_base_url: str | None = None
    rag_routing_base_url: str | None = None
    rag_faithfulness_base_url: str | None = None
    rag_ingestion_base_url: str | None = None
    rag_vision_base_url: str | None = None
    rag_chat_model: str | None = None
    rag_vision_model: str | None = None
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_chat_model: str = DEFAULT_OLLAMA_CHAT_MODEL
    ollama_embed_model: str = DEFAULT_OLLAMA_EMBED_MODEL
    ollama_vision_model: str | None = None
    ollama_thinking_enabled: bool = False
    ollama_num_ctx: int = Field(default=DEFAULT_OLLAMA_NUM_CTX, ge=1024, le=262144)
    rag_http_timeout_seconds: float = Field(
        default=DEFAULT_RAG_HTTP_TIMEOUT_SECONDS, gt=0
    )
    rag_ollama_chat_timeout_seconds: float = Field(
        default=DEFAULT_OLLAMA_CHAT_TIMEOUT_SECONDS, gt=0
    )
    rag_ollama_embed_timeout_seconds: float = Field(
        default=DEFAULT_OLLAMA_EMBED_TIMEOUT_SECONDS, gt=0
    )
    rag_routing_timeout_seconds: float = Field(
        default=DEFAULT_ROUTING_TIMEOUT_SECONDS, ge=1.0, le=30.0
    )
    rag_reasoning_timeout_seconds: float = Field(
        default=DEFAULT_REASONING_TIMEOUT_SECONDS, ge=1.0, le=300.0
    )
    rag_faithfulness_timeout_seconds: float = Field(
        default=DEFAULT_FAITHFULNESS_TIMEOUT_SECONDS, ge=1.0, le=300.0
    )
    rag_json_num_predict: int = Field(
        default=DEFAULT_JSON_NUM_PREDICT, ge=256, le=32768
    )
    rag_retrieval_token_budget: int = Field(
        default=DEFAULT_RETRIEVAL_TOKEN_BUDGET, ge=1000, le=200000
    )
    vllm_base_url: str = DEFAULT_VLLM_BASE_URL
    vllm_reasoning_base_url: str | None = None
    vllm_routing_base_url: str | None = None
    vllm_faithfulness_base_url: str | None = None
    vllm_ingestion_base_url: str | None = None
    vllm_vision_base_url: str | None = None
    vllm_chat_model: str = DEFAULT_VLLM_CHAT_MODEL
    vllm_vision_model_id: str = DEFAULT_VLLM_VISION_MODEL_ID
    vllm_text_max_model_len: int = Field(default=4096, ge=256, le=262144)
    vllm_text_gpu_memory_utilization: float = Field(default=0.12, gt=0.0, le=1.0)
    vllm_text_kv_cache_memory_bytes: str = "2G"
    vllm_text_max_num_seqs: int = Field(default=1, ge=1, le=1024)
    vllm_text_max_num_batched_tokens: int = Field(default=4096, ge=256, le=262144)
    vllm_embed_max_model_len: int = Field(default=2048, ge=256, le=262144)
    vllm_embed_gpu_memory_utilization: float = Field(default=0.05, gt=0.0, le=1.0)
    vllm_embed_max_num_seqs: int = Field(default=2, ge=1, le=1024)
    vllm_embed_max_num_batched_tokens: int = Field(default=2048, ge=256, le=262144)
    vllm_vision_max_model_len: int = Field(default=2048, ge=256, le=262144)
    vllm_vision_gpu_memory_utilization: float = Field(default=0.10, gt=0.0, le=1.0)
    vllm_vision_kv_cache_memory_bytes: str = "2G"
    vllm_vision_max_num_seqs: int = Field(default=1, ge=1, le=1024)
    vllm_vision_max_num_batched_tokens: int = Field(default=2048, ge=256, le=262144)
    embeddings_base_url: str = DEFAULT_EMBEDDINGS_BASE_URL
    embedding_model_id: str = DEFAULT_EMBEDDING_MODEL_ID
    rag_fastembed_model: str = DEFAULT_FASTEMBED_DENSE_MODEL
    rag_dense_cache_dir: str | None = DEFAULT_FASTEMBED_CACHE_DIR
    rag_top_k: int = Field(default=DEFAULT_TOP_K, ge=1)
    rag_sparse_model: str = DEFAULT_SPARSE_MODEL
    rag_sparse_cache_dir: str | None = DEFAULT_FASTEMBED_CACHE_DIR
    rag_reranker_model: str = DEFAULT_RERANKER_MODEL
    rag_reranker_cache_dir: str | None = DEFAULT_FASTEMBED_CACHE_DIR
    rag_reranker_device: RerankerDevice = DEFAULT_RERANKER_DEVICE
    rag_reranker_max_candidates: int = Field(
        default=DEFAULT_RERANKER_MAX_CANDIDATES, ge=1, le=512
    )
    rag_reranker_timeout_seconds: float = Field(
        default=DEFAULT_RERANKER_TIMEOUT_SECONDS, gt=0, le=300
    )
    rag_retrieval_max_retries: int = Field(
        default=DEFAULT_RETRIEVAL_MAX_RETRIES, ge=0, le=3
    )
    rag_query_planner_enabled: bool = DEFAULT_QUERY_PLANNER_ENABLED
    rag_query_rewrite_llm_enabled: bool = DEFAULT_QUERY_REWRITE_LLM_ENABLED
    rag_evidence_gate_policy: EvidenceGatePolicy = DEFAULT_EVIDENCE_GATE_POLICY
    rag_faithfulness_model: str | None = DEFAULT_FAITHFULNESS_MODEL
    rag_faithfulness_policy: FaithfulnessPolicy = DEFAULT_FAITHFULNESS_POLICY
    rag_hybrid_disagreement_detector_enabled: bool = (
        DEFAULT_HYBRID_DISAGREEMENT_DETECTOR_ENABLED
    )
    rag_routing_model: str | None = DEFAULT_ROUTING_MODEL
    rag_reasoning_model: str | None = DEFAULT_REASONING_MODEL
    rag_ingestion_model: str | None = None
    artifact_queue_backend: str = "celery"
    artifact_queue_name: str = "artifact:jobs"
    # This is a compatibility identifier for queued messages, not an import path.
    artifact_task_name: str = DEFAULT_ARTIFACT_TASK_NAME
    artifact_retention_days: int = Field(default=30, ge=1, le=365)
    artifact_maintenance_interval_seconds: int = Field(default=300, ge=30)
    artifact_worker_timeout_seconds: float = Field(default=1800.0, ge=30.0)
    artifact_libreoffice_required: bool = False
    artifact_reranker_max_candidates: int = Field(default=8, ge=1, le=128)
    artifact_composer_timeout_seconds: float = Field(default=60.0, ge=5.0)
    evaluation_queue_backend: str = "celery"
    evaluation_queue_name: str = "evaluation:jobs"
    # This is a compatibility identifier for queued messages, not an import path.
    evaluation_task_name: str = DEFAULT_EVALUATION_TASK_NAME
    evaluation_retention_days: int = Field(default=30, ge=1, le=365)
    evaluation_worker_timeout_seconds: float = Field(default=3600.0, ge=30.0)
    evaluation_answer_llm_verifier_enabled: bool = True
    evaluation_answer_llm_verifier_model: str | None = None
    application_image_digest: str | None = None
    evaluation_host_profile: str | None = None
    rag_session_store: str = "redis"
    rag_session_prefix: str = "rag:session"
    rag_session_ttl_seconds: int = 14400
    upload_storage_backend: str = "local"
    upload_storage_dir: str = "/tmp/agenticrag/uploads"
    upload_max_bytes: int = 50 * 1024 * 1024
    workspace_timezone: str = "Asia/Karachi"
    folder_snapshot_max_files: int = 100
    folder_snapshot_max_bytes: int = 5 * 1024 * 1024 * 1024
    folder_scheduler_interval_seconds: int = 60
    folder_sources_root: str = "/folder-sources"
    ingest_queue_backend: str = "celery"
    ingest_queue_name: str = "ingest:jobs"
    # These are compatibility identifiers for queued messages, not import paths.
    ingest_task_name: str = DEFAULT_INGEST_TASK_NAME
    graphrag_queue_name: str = "graphrag:jobs"
    graphrag_index_task_name: str = DEFAULT_GRAPHRAG_INDEX_TASK_NAME
    graphrag_partition_rebuild_task_name: str = (
        DEFAULT_GRAPHRAG_PARTITION_REBUILD_TASK_NAME
    )
    ingest_worker_boot_concurrency: int = Field(default=1, ge=1, le=10)
    ocr_review_confidence_threshold: float = Field(default=0.9, ge=0.0, le=1.0)
    pdf_image_review_threshold: int = Field(default=64, ge=0, le=10000)
    ingest_maintenance_interval_seconds: int = Field(default=30, ge=5)
    ingest_stale_after_seconds: int = Field(default=120, ge=60)
    connector_secrets_key: str = "replace-with-local-connector-secrets-key"
    connector_secrets_key_ring: str = ""
    connector_include_stale_in_retrieval: bool = False
    connector_live_sql_enabled: bool = True
    connector_live_sql_max_rows: int = Field(default=100, ge=1, le=10000)
    connector_live_sql_timeout_seconds: int = Field(default=15, ge=1, le=300)
    connector_live_sql_max_scopes: int = Field(default=5, ge=1, le=50)
    connector_live_sql_max_repair_attempts: int = Field(default=2, ge=0, le=5)
    connector_live_sql_result_verifier_enabled: bool = True
    connector_live_sql_verifier_sample_rows: int = Field(default=5, ge=0, le=20)
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "agenticrag"
    minio_secret_key: str = "agenticrag-local-minio-password"
    minio_bucket: str = "agenticrag-uploads"
    minio_secure: bool = False
    clamav_scan_enabled: bool = False
    clamav_host: str = "clamav"
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 30.0

    @field_validator(
        "rag_model_provider",
        "rag_embedding_provider",
        "rag_chat_provider",
        "rag_reasoning_provider",
        "rag_routing_provider",
        "rag_faithfulness_provider",
        "rag_ingestion_provider",
        "rag_vision_provider",
        mode="before",
    )
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        return normalized or None

    @field_validator(
        "artifact_task_name",
        "evaluation_task_name",
        "ingest_task_name",
        "graphrag_index_task_name",
        "graphrag_partition_rebuild_task_name",
        mode="before",
    )
    @classmethod
    def normalize_celery_task_name(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> object:
        if not isinstance(value, str):
            return value
        return normalize_task_name(info.field_name.upper(), value)

    @model_validator(mode="after")
    def validate_document_pipeline_task_name_ownership(self) -> "Settings":
        validate_document_pipeline_task_names(
            ingest=self.ingest_task_name,
            graphrag_index=self.graphrag_index_task_name,
            graphrag_partition_rebuild=self.graphrag_partition_rebuild_task_name,
        )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        configured = [origin.strip() for origin in self.backend_cors_origins.split(",")]
        return [origin for origin in configured if origin] or self.cors_origins


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
