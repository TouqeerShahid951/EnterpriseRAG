import type { RagModelDiscoveryResult } from "@/types/api";

export type LanguageRole = "chat" | "reasoning" | "routing" | "faithfulness" | "ingestion" | "vision";

export const LOCAL_INFERENCE_HOST = "host.docker.internal";

export const VLLM_LOCAL_PORTS = { chat: "8010", embedding: "8011", vision: "8016" } as const;

export const LANGUAGE_ROLES: LanguageRole[] = ["chat", "reasoning", "routing", "faithfulness", "ingestion", "vision"];

export const MODEL_STATUS_ROLES: Array<{ key: EndpointRole; label: string }> = [
  { key: "chat", label: "Answer synthesis" },
  { key: "reasoning", label: "Reasoning" },
  { key: "routing", label: "Router" },
  { key: "faithfulness", label: "Faithfulness" },
  { key: "ingestion", label: "Ingestion metadata" },
  { key: "vision", label: "Vision" },
  { key: "embedding", label: "Embeddings" },
];

export const DEFAULT_FASTEMBED_MODEL = "nomic-ai/nomic-embed-text-v1.5-Q";

const SUPPORTED_RERANKER_MODELS = [
  "jinaai/jina-reranker-v1-turbo-en",
  "jinaai/jina-reranker-v1-tiny-en",
  "BAAI/bge-reranker-base",
  "Xenova/ms-marco-MiniLM-L-12-v2",
  "Xenova/ms-marco-MiniLM-L-6-v2",
] as const;

export const DEFAULT_RERANKER_MODEL = SUPPORTED_RERANKER_MODELS[0];

export function modelOptionsFromDiscovery(result: RagModelDiscoveryResult | undefined) {
  const chat = result?.chat_models ?? [];
  const reasoning = result?.reasoning_models ?? chat;

  return {
    chat,
    embedding: result?.embedding_models ?? [],
    reasoning,
    sqlGeneration: reasoning,
    routing: result?.routing_models ?? reasoning,
    faithfulness: result?.faithfulness_models ?? chat,
    ingestion: result?.ingestion_models ?? chat,
    vision: result?.vision_models ?? chat,
  };
}

export function rerankerOptionsFromCatalog(
  catalog: { models?: Array<{ model?: string | null }> } | undefined,
): string[] {
  const apiModels = catalog?.models?.map((option) => option.model?.trim()).filter((model): model is string => Boolean(model)) ?? [];
  return uniqueStrings(apiModels);
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values)];
}

export type EndpointRole = "chat" | "reasoning" | "routing" | "faithfulness" | "ingestion" | "vision" | "embedding";
