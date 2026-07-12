from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from rag.shared.fastembed_dense import DEFAULT_FASTEMBED_CACHE_DIR, DEFAULT_FASTEMBED_DENSE_MODEL
from rag.shared.contracts.reranker_models import DEFAULT_RERANKER_MODEL


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
    service_token_header: str = "X-Service-Token"
    service_token: str = "replace-with-local-service-token"
    deployment_controller_url: str = "http://deployment-controller:8080"
    deployment_controller_token: str = (
        "replace-with-local-deployment-controller-token"
    )
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
    database_url: str = "postgresql://agenticrag:agenticrag-local-password@postgres:5432/agenticrag"
    redis_url: str = "redis://:agenticrag-local-redis-password@redis:6379/0"
    celery_broker_url: str | None = None
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "documents"
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "agenticrag-local-neo4j-password"
    neo4j_database: str = "neo4j"
    graphrag_enabled: bool = False
    graphrag_community_collection: str = "graphrag_community_summaries"
    rag_model_provider: str = "ollama"
    rag_embedding_provider: str = "fastembed"
    rag_chat_provider: str | None = None
    rag_reasoning_provider: str | None = None
    rag_routing_provider: str | None = None
    rag_faithfulness_provider: str | None = None
    rag_ingestion_provider: str | None = None
    rag_vision_provider: str | None = None
    rag_chat_base_url: str | None = None
    rag_reasoning_base_url: str | None = None
    rag_routing_base_url: str | None = None
    rag_faithfulness_base_url: str | None = None
    rag_ingestion_base_url: str | None = None
    rag_vision_base_url: str | None = None
    rag_chat_model: str | None = None
    rag_vision_model: str | None = None
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_chat_model: str = "llama3.1:8b"
    ollama_embed_model: str = "nomic-embed-text:latest"
    ollama_vision_model: str | None = None
    ollama_thinking_enabled: bool = False
    ollama_num_ctx: int = Field(default=16384, ge=1024, le=262144)
    rag_http_timeout_seconds: float = 45.0
    rag_ollama_chat_timeout_seconds: float = 180.0
    rag_ollama_embed_timeout_seconds: float = 45.0
    rag_json_num_predict: int = Field(default=4096, ge=256, le=32768)
    rag_retrieval_token_budget: int = Field(default=12000, ge=1000, le=200000)
    vllm_base_url: str = "http://host.docker.internal:8000"
    vllm_reasoning_base_url: str | None = None
    vllm_routing_base_url: str | None = None
    vllm_faithfulness_base_url: str | None = None
    vllm_ingestion_base_url: str | None = None
    vllm_vision_base_url: str | None = None
    vllm_chat_model: str = "default"
    vllm_vision_model_id: str = "vision"
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
    embeddings_base_url: str = "http://host.docker.internal:8001"
    embedding_model_id: str = "default"
    rag_fastembed_model: str = DEFAULT_FASTEMBED_DENSE_MODEL
    rag_dense_cache_dir: str | None = DEFAULT_FASTEMBED_CACHE_DIR
    rag_top_k: int = 10
    rag_sparse_model: str = "Qdrant/bm25"
    rag_sparse_cache_dir: str | None = "/models/fastembed"
    rag_reranker_model: str = DEFAULT_RERANKER_MODEL
    rag_reranker_cache_dir: str | None = "/models/fastembed"
    rag_reranker_max_candidates: int = Field(default=40, ge=1, le=512)
    rag_retrieval_max_retries: int = Field(default=1, ge=0, le=3)
    rag_query_planner_enabled: bool = True
    rag_query_rewrite_llm_enabled: bool = False
    rag_faithfulness_model: str | None = None
    rag_faithfulness_policy: str = "high_risk"
    rag_defer_faithfulness: bool = True
    rag_faithfulness_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    rag_source_router_llm_enabled: bool = True
    rag_source_router_llm_min_confidence: float = Field(default=0.60, ge=0.0, le=1.0)
    rag_hybrid_disagreement_detector_enabled: bool = True
    rag_intent_router_version: str = "v1"
    rag_route_llm_verifier_enabled: bool = True
    rag_route_llm_verifier_model: str | None = None
    rag_reasoning_model: str | None = None
    rag_ingestion_model: str | None = None
    artifact_pipeline_version: Literal["v1", "v2"] = "v2"
    artifact_queue_backend: str = "celery"
    artifact_queue_name: str = "artifact:jobs"
    artifact_task_name: str = "rag.artifact_jobs.tasks.generate_artifact_job"
    artifact_retention_days: int = Field(default=30, ge=1, le=365)
    artifact_maintenance_interval_seconds: int = Field(default=300, ge=30)
    artifact_worker_timeout_seconds: float = Field(default=1800.0, ge=30.0)
    artifact_libreoffice_required: bool = False
    artifact_reranker_max_candidates: int = Field(default=8, ge=1, le=128)
    artifact_composer_timeout_seconds: float = Field(default=60.0, ge=5.0)
    evaluation_queue_backend: str = "celery"
    evaluation_queue_name: str = "evaluation:jobs"
    evaluation_task_name: str = "rag.evaluations.tasks.run_evaluation"
    evaluation_retention_days: int = Field(default=30, ge=1, le=365)
    evaluation_worker_timeout_seconds: float = Field(default=3600.0, ge=30.0)
    evaluation_diagnostic_top_k: int = Field(default=10, ge=1, le=100)
    evaluation_answer_llm_verifier_enabled: bool = True
    evaluation_answer_llm_verifier_model: str | None = None
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
    ingest_task_name: str = "apps.ingestion.tasks.ingest_document"
    graphrag_queue_name: str = "graphrag:jobs"
    graphrag_index_task_name: str = "apps.ingestion.tasks.index_document_graphrag"
    graphrag_partition_rebuild_task_name: str = "apps.ingestion.tasks.rebuild_graphrag_partition"
    ingest_worker_boot_concurrency: int = Field(default=1, ge=1, le=10)
    ingestion_quality_preset: str = "fast"
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
    connector_live_sql_max_schedules: int = Field(default=5, ge=1, le=50)
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

    @property
    def cors_origin_list(self) -> list[str]:
        configured = [origin.strip() for origin in self.backend_cors_origins.split(",")]
        return [origin for origin in configured if origin] or self.cors_origins


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
