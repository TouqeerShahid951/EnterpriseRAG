import { describe, expect, it } from "vitest";

import type { RagConfig } from "@/types/api";
import {
  activeStackLabel,
  activeVisionStatus,
  discoveryHealthLabel,
  modelOptionsFromDiscovery,
  modelPlaceholderForStatus,
  requestFromForm,
  rerankerOptionsFromCatalog,
} from "./PrudentiaSettingsPage";
import { ollamaForm } from "./settingsTestFixtures";

describe("inference settings helpers", () => {
  it("keeps discovered model options assigned to their matching roles", () => {
    const options = modelOptionsFromDiscovery({
      provider: "vllm",
      embedding_provider: "openai_compatible",
      base_url: "http://chat:8000",
      embedding_base_url: "http://embedding:8001",
      chat_models: ["answer-model"],
      embedding_models: ["embedding-model"],
      reasoning_models: ["reasoning-model"],
      routing_models: ["routing-model"],
      faithfulness_models: ["faithfulness-model"],
      ingestion_models: ["ingestion-model"],
      vision_models: ["vision-model"],
    });

    expect(options).toEqual({
      chat: ["answer-model"],
      embedding: ["embedding-model"],
      reasoning: ["reasoning-model"],
      routing: ["routing-model"],
      faithfulness: ["faithfulness-model"],
      ingestion: ["ingestion-model"],
      vision: ["vision-model"],
    });
  });

  it("summarizes partial model discovery without hiding healthy role models", () => {
    const discovery = {
      provider: "vllm" as const,
      embedding_provider: "fastembed" as const,
      base_url: "http://host.docker.internal:8010",
      embedding_base_url: "local FastEmbed cache",
      chat_models: ["Qwen/Qwen3-14B-AWQ"],
      embedding_models: ["nomic-ai/nomic-embed-text-v1.5-Q"],
      reasoning_models: ["Qwen/Qwen3-14B-AWQ"],
      routing_models: ["Qwen/Qwen3-14B-AWQ"],
      faithfulness_models: ["Qwen/Qwen3-14B-AWQ"],
      ingestion_models: ["Qwen/Qwen3-14B-AWQ"],
      vision_models: [],
      model_statuses: {
        chat: {
          status: "ok",
          provider: "vllm",
          base_url: "http://host.docker.internal:8010",
          message: "vLLM chat returned 1 model.",
        },
        vision: {
          status: "error",
          provider: "vllm",
          base_url: "http://host.docker.internal:8016",
          message: "No models returned from vLLM vision at host.docker.internal:8016.",
          code: "vllm_vision_unavailable",
        },
      },
    };

    const options = modelOptionsFromDiscovery(discovery);

    expect(options.chat).toEqual(["Qwen/Qwen3-14B-AWQ"]);
    expect(options.vision).toEqual([]);
    expect(discoveryHealthLabel(discovery, false, null)).toBe("1 service need attention");
    expect(modelPlaceholderForStatus(discovery.model_statuses.vision, { canFetch: true, loading: false })).toContain(
      "No models returned from vLLM vision",
    );
  });

  it("falls optional role model lists back to the documented defaults", () => {
    const options = modelOptionsFromDiscovery({
      provider: "ollama",
      embedding_provider: "ollama",
      base_url: "http://ollama:11434",
      embedding_base_url: "http://ollama:11434",
      chat_models: ["answer-model"],
      embedding_models: ["embedding-model"],
    });

    expect(options.reasoning).toEqual(["answer-model"]);
    expect(options.routing).toEqual(["answer-model"]);
    expect(options.faithfulness).toEqual(["answer-model"]);
    expect(options.ingestion).toEqual(["answer-model"]);
    expect(options.vision).toEqual(["answer-model"]);
  });

  it("saves an explicit Ollama vision model", () => {
    const request = requestFromForm({
      ...ollamaForm,
      ingestion_model: "qwen3:8b",
      vision_model: "llava:latest",
    });

    expect(request.ingestion_model).toBe("qwen3:8b");
    expect(request.vision_model).toBe("llava:latest");
  });

  it("does not present a fallback text model as an active vision model", () => {
    const config = {
      provider: "ollama",
      embedding_provider: "ollama",
      vision_provider: "ollama",
      ingestion_provider: "ollama",
      base_url: "http://ollama:11434",
      ingestion_base_url: "http://ollama:11434",
      vision_base_url: "http://ollama:11434",
      chat_model: "llama3.1:8b",
      ingestion_model: "llama3.1:8b",
      vision_model: null,
    } as RagConfig;

    expect(activeVisionStatus(config)).toEqual({ endpoint: null, model: "Not configured" });
    expect(activeStackLabel(config)).toBe("Ollama text, Ollama embeddings, vision not configured");
  });

  it("shows a vision endpoint only when an explicit vision model is active", () => {
    const config = {
      provider: "vllm",
      embedding_provider: "fastembed",
      vision_provider: "ollama",
      ingestion_provider: "vllm",
      base_url: "http://vllm:8000",
      ingestion_base_url: "http://vllm:8005",
      vision_base_url: "http://ollama:11434",
      vision_model: "llava:latest",
    } as RagConfig;

    expect(activeVisionStatus(config)).toEqual({
      endpoint: "http://ollama:11434",
      model: "Ollama: llava:latest",
    });
    expect(activeStackLabel(config)).toBe("vLLM text, FastEmbed local embeddings, Ollama vision");
  });

  it("does not show reranker options before the cached catalog arrives", () => {
    expect(rerankerOptionsFromCatalog(undefined)).toEqual([]);
  });

  it("uses the cached reranker models returned by the API", () => {
    const options = rerankerOptionsFromCatalog({
      models: [
        { model: "jinaai/jina-reranker-v1-turbo-en" },
        { model: "custom/local-reranker" },
      ],
    });

    expect(options[0]).toBe("jinaai/jina-reranker-v1-turbo-en");
    expect(options).toContain("custom/local-reranker");
    expect(options).not.toContain("BAAI/bge-reranker-base");
    expect(options).not.toContain("Xenova/ms-marco-MiniLM-L-12-v2");
  });
});
