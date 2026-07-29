"""Dependency-free defaults for RAG runtime configuration."""

from __future__ import annotations

from typing import Literal

InferenceProvider = Literal["ollama", "vllm"]
EmbeddingProvider = Literal["ollama", "openai_compatible", "fastembed"]
EvidenceGatePolicy = Literal["adaptive", "always", "never"]
FaithfulnessPolicy = Literal["adaptive", "always", "never"]
RerankerDevice = Literal["auto", "cpu", "cuda"]

SUPPORTED_INFERENCE_PROVIDERS: tuple[InferenceProvider, ...] = ("ollama", "vllm")
SUPPORTED_EMBEDDING_PROVIDERS: tuple[EmbeddingProvider, ...] = (
    "ollama",
    "openai_compatible",
    "fastembed",
)
SUPPORTED_WORKER_MODEL_PROVIDERS = (*SUPPORTED_INFERENCE_PROVIDERS, "mock")

DEFAULT_MODEL_PROVIDER: InferenceProvider = "ollama"
DEFAULT_EMBEDDING_PROVIDER: EmbeddingProvider = "fastembed"

DEFAULT_OLLAMA_BASE_URL = "http://host.docker.internal:11434"
DEFAULT_OLLAMA_CHAT_MODEL = "llama3.1:8b"
DEFAULT_OLLAMA_EMBED_MODEL = "nomic-embed-text:latest"
DEFAULT_OLLAMA_NUM_CTX = 16384
DEFAULT_OLLAMA_VISION_NUM_CTX = 8192

DEFAULT_VLLM_BASE_URL = "http://host.docker.internal:8000"
DEFAULT_VLLM_CHAT_MODEL = "Qwen/Qwen3-8B-AWQ"
DEFAULT_VLLM_VISION_MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"
DEFAULT_EMBEDDINGS_BASE_URL = "http://host.docker.internal:8001"
DEFAULT_EMBEDDING_MODEL_ID = "nomic-ai/nomic-embed-text-v1.5"

DEFAULT_FASTEMBED_DENSE_MODEL = "nomic-ai/nomic-embed-text-v1.5-Q"
DEFAULT_FASTEMBED_CACHE_DIR = "/models/fastembed"
DEFAULT_SPARSE_MODEL = "Qdrant/bm25"
DEFAULT_RERANKER_MODEL = "jinaai/jina-reranker-v1-turbo-en"
DEFAULT_RERANKER_DEVICE: RerankerDevice = "auto"

DEFAULT_RAG_HTTP_TIMEOUT_SECONDS = 180.0
DEFAULT_OLLAMA_CHAT_TIMEOUT_SECONDS = 180.0
DEFAULT_OLLAMA_EMBED_TIMEOUT_SECONDS = 45.0
DEFAULT_REASONING_TIMEOUT_SECONDS = 30.0
DEFAULT_ROUTING_TIMEOUT_SECONDS = 5.0
DEFAULT_FAITHFULNESS_TIMEOUT_SECONDS = 30.0
DEFAULT_REASONING_MODEL = DEFAULT_OLLAMA_CHAT_MODEL
DEFAULT_ROUTING_MODEL = DEFAULT_OLLAMA_CHAT_MODEL
DEFAULT_FAITHFULNESS_MODEL = DEFAULT_OLLAMA_CHAT_MODEL
DEFAULT_JSON_NUM_PREDICT = 4096
DEFAULT_RETRIEVAL_TOKEN_BUDGET = 12000
DEFAULT_TOP_K = 10
DEFAULT_RERANKER_MAX_CANDIDATES = 24
DEFAULT_RERANKER_TIMEOUT_SECONDS = 30.0
DEFAULT_RETRIEVAL_MAX_RETRIES = 1
DEFAULT_QUERY_PLANNER_ENABLED = True
DEFAULT_QUERY_REWRITE_LLM_ENABLED = False
DEFAULT_EVIDENCE_GATE_POLICY: EvidenceGatePolicy = "adaptive"
DEFAULT_FAITHFULNESS_POLICY: FaithfulnessPolicy = "adaptive"
DEFAULT_HYBRID_DISAGREEMENT_DETECTOR_ENABLED = True
DEFAULT_GRAPHRAG_ENABLED = True
