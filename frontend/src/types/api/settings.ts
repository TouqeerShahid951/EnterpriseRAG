import type { ISODateString } from "./common";

interface RagConfigHealth {
  status: string;
  message: string;
  embedding_dimension: number | null;
  checked_at: ISODateString | null;
  chat_latency_ms: number | null;
  embed_latency_ms: number | null;
}

interface IngestWorkerState {
  name: string;
  pool_size: number;
  active_jobs: number;
}

export type IngestionQualityPreset = "fast" | "balanced" | "high_accuracy";

export interface IngestConfig {
  worker_concurrency: number;
  quality_preset: IngestionQualityPreset;
  ocr_review_confidence_threshold: number;
  pdf_image_review_threshold: number;
  vision_layout_repair_enabled: boolean;
  graph_enrichment_enabled: boolean;
  recommended_concurrency: number;
  worker_online: boolean;
  active_jobs: number;
  observed_pool_size: number;
  apply_status: string;
  workers: IngestWorkerState[];
  hazardous: boolean;
  updated_at: ISODateString | null;
}

export interface VllmServiceDeploymentLimits {
  max_model_len: number;
  gpu_memory_utilization: number;
  max_num_seqs: number;
  max_num_batched_tokens: number;
  kv_cache_memory_bytes?: string | null;
}

export type VllmDeploymentService = "text" | "embeddings" | "vision";

export interface VllmDeploymentConfig {
  source: string;
  apply_status: string;
  message?: string | null;
  text: VllmServiceDeploymentLimits;
  embeddings: VllmServiceDeploymentLimits;
  vision: VllmServiceDeploymentLimits;
}

export interface RagConfig {
  source: "workspace" | "env" | string;
  provider: "ollama" | "vllm";
  embedding_provider: "ollama" | "openai_compatible" | "fastembed";
  reasoning_provider?: "ollama" | "vllm" | null;
  routing_provider?: "ollama" | "vllm" | null;
  faithfulness_provider?: "ollama" | "vllm" | null;
  ingestion_provider?: "ollama" | "vllm" | null;
  vision_provider?: "ollama" | "vllm" | null;
  base_url: string;
  host: string;
  port: number;
  embedding_base_url: string;
  embedding_host: string;
  embedding_port: number;
  reasoning_base_url?: string | null;
  reasoning_host?: string | null;
  reasoning_port?: number | null;
  routing_base_url?: string | null;
  routing_host?: string | null;
  routing_port?: number | null;
  faithfulness_base_url?: string | null;
  faithfulness_host?: string | null;
  faithfulness_port?: number | null;
  ingestion_base_url?: string | null;
  ingestion_host?: string | null;
  ingestion_port?: number | null;
  vision_base_url?: string | null;
  vision_host?: string | null;
  vision_port?: number | null;
  chat_model: string;
  embed_model: string;
  reasoning_model: string | null;
  routing_model: string | null;
  faithfulness_model: string | null;
  ingestion_model: string | null;
  vision_model: string | null;
  thinking_enabled: boolean;
  json_num_predict: number;
  retrieval_token_budget: number;
  query_planner_enabled: boolean;
  reranker_model: string;
  chat_timeout_seconds: number;
  embed_timeout_seconds: number;
  health: RagConfigHealth;
}

export interface RagConfigTestResult {
  provider: "ollama" | "vllm";
  embedding_provider: "ollama" | "openai_compatible" | "fastembed";
  reasoning_provider?: "ollama" | "vllm" | null;
  routing_provider?: "ollama" | "vllm" | null;
  faithfulness_provider?: "ollama" | "vllm" | null;
  ingestion_provider?: "ollama" | "vllm" | null;
  vision_provider?: "ollama" | "vllm" | null;
  base_url: string;
  embedding_base_url: string;
  reasoning_base_url?: string | null;
  routing_base_url?: string | null;
  faithfulness_base_url?: string | null;
  ingestion_base_url?: string | null;
  vision_base_url?: string | null;
  chat_models: string[];
  embedding_models: string[];
  reasoning_models?: string[];
  routing_models?: string[];
  faithfulness_models?: string[];
  ingestion_models?: string[];
  vision_models?: string[];
  thinking_enabled: boolean;
  json_num_predict: number;
  retrieval_token_budget: number;
  query_planner_enabled: boolean;
  reranker_model: string;
  health: RagConfigHealth;
}

interface RerankerModelOption {
  model: string;
  default: boolean;
}

export interface RerankerModelsResponse {
  models: RerankerModelOption[];
}

export interface RagModelDiscoveryResult {
  provider: "ollama" | "vllm";
  embedding_provider: "ollama" | "openai_compatible" | "fastembed";
  reasoning_provider?: "ollama" | "vllm" | null;
  routing_provider?: "ollama" | "vllm" | null;
  faithfulness_provider?: "ollama" | "vllm" | null;
  ingestion_provider?: "ollama" | "vllm" | null;
  vision_provider?: "ollama" | "vllm" | null;
  base_url: string;
  embedding_base_url: string;
  reasoning_base_url?: string | null;
  routing_base_url?: string | null;
  faithfulness_base_url?: string | null;
  ingestion_base_url?: string | null;
  vision_base_url?: string | null;
  chat_models: string[];
  embedding_models: string[];
  reasoning_models?: string[];
  routing_models?: string[];
  faithfulness_models?: string[];
  ingestion_models?: string[];
  vision_models?: string[];
  model_statuses?: Record<string, RagModelDiscoveryStatus>;
}

export interface RagModelDiscoveryStatus {
  status: "ok" | "empty" | "error" | string;
  provider: "ollama" | "vllm" | "fastembed" | "openai_compatible" | string;
  base_url: string;
  message: string;
  code?: string | null;
}
