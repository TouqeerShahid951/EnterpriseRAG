import { describe, expect, it } from "vitest";

import {
  endpointsFromForm,
  inferenceLocationDefaults,
  modelOptionsFromDiscovery,
  providerDefaults,
  requestFromForm,
  rerankerOptionsFromCatalog,
  SUPPORTED_RERANKER_MODELS,
  type RagConfigFormState,
} from "./FahamSettingsPage";

const ollamaForm: RagConfigFormState = {
  provider: "ollama",
  inference_location: "local",
  host: "",
  port: "11434",
  embedding_host: "",
  embedding_port: "11434",
  reasoning_host: "",
  reasoning_port: "11434",
  routing_host: "",
  routing_port: "11434",
  faithfulness_host: "",
  faithfulness_port: "11434",
  ingestion_host: "",
  ingestion_port: "11434",
  chat_model: "llama3.1:8b",
  embed_model: "nomic-embed-text:latest",
  reasoning_model: "",
  routing_model: "",
  faithfulness_model: "",
  ingestion_model: "",
  vision_model: "",
  reranker_model: "jinaai/jina-reranker-v1-turbo-en",
  thinking_enabled: true,
  json_num_predict: "4096",
  retrieval_token_budget: "12000",
  chat_timeout_seconds: "180",
  embed_timeout_seconds: "45",
};

describe("inference settings helpers", () => {
  it("uses the same endpoint for Ollama chat and embeddings", () => {
    const endpoints = endpointsFromForm(ollamaForm);
    expect(endpoints.chat).toEqual({ host: "host.docker.internal", port: 11434 });
    expect(endpoints.embedding).toEqual(endpoints.chat);
  });

  it("builds separate vLLM chat and embedding endpoints", () => {
    const form = {
      ...inferenceLocationDefaults(providerDefaults({ ...ollamaForm, provider: "vllm" }), "network"),
      host: "vllm.local",
      reasoning_host: "reasoning.local",
      routing_host: "routing.local",
      faithfulness_host: "judge.local",
      ingestion_host: "metadata.local",
      embedding_host: "embeddings.local",
      reasoning_port: "8002",
      routing_port: "8003",
      faithfulness_port: "8004",
      ingestion_port: "8005",
      chat_model: "qwen3",
      embed_model: "bge-m3",
    };
    const request = requestFromForm(form);

    expect(request).toMatchObject({
      provider: "vllm",
      host: "vllm.local",
      port: 8000,
      embedding_host: "embeddings.local",
      embedding_port: 8001,
      reasoning_host: "reasoning.local",
      reasoning_port: 8002,
      routing_host: "routing.local",
      routing_port: 8003,
      faithfulness_host: "judge.local",
      faithfulness_port: 8004,
      ingestion_host: "metadata.local",
      ingestion_port: 8005,
      thinking_enabled: false,
      json_num_predict: 4096,
      retrieval_token_budget: 12000,
      reranker_model: "jinaai/jina-reranker-v1-turbo-en",
    });
  });

  it("maps output and evidence budgets into the saved config request", () => {
    const request = requestFromForm({
      ...ollamaForm,
      json_num_predict: "8192",
      retrieval_token_budget: "24000",
      reranker_model: "BAAI/bge-reranker-base",
    });

    expect(request.json_num_predict).toBe(8192);
    expect(request.retrieval_token_budget).toBe(24000);
    expect(request.reranker_model).toBe("BAAI/bge-reranker-base");
  });

  it("uses non-conflicting local vLLM ports and inherits optional role endpoints", () => {
    const form = providerDefaults({ ...ollamaForm, provider: "vllm" });
    const endpoints = endpointsFromForm(form);

    expect(form.port).toBe("8100");
    expect(form.embedding_port).toBe("8101");
    expect(form.reasoning_port).toBe("");
    expect(form.routing_port).toBe("");
    expect(endpoints.reasoning).toEqual(endpoints.chat);
    expect(endpoints.routing).toEqual(endpoints.chat);
    expect(endpoints.faithfulness).toEqual(endpoints.chat);
    expect(endpoints.ingestion).toEqual(endpoints.chat);
    expect(endpoints.embedding).toEqual({ host: "host.docker.internal", port: 8101 });
    expect(form.chat_model).toBe("");
    expect(form.embed_model).toBe("");
    expect(form.reranker_model).toBe("jinaai/jina-reranker-v1-turbo-en");
  });

  it("uses standard vLLM ports for a network server and clears endpoint-specific models", () => {
    const localVllm = {
      ...providerDefaults({ ...ollamaForm, provider: "vllm" }),
      chat_model: "local-chat",
      embed_model: "local-embedding",
    };
    const networkVllm = inferenceLocationDefaults(localVllm, "network");

    expect(networkVllm.port).toBe("8000");
    expect(networkVllm.embedding_port).toBe("8001");
    expect(networkVllm.chat_model).toBe("");
    expect(networkVllm.embed_model).toBe("");
  });

  it("keeps discovered model options assigned to their matching roles", () => {
    const options = modelOptionsFromDiscovery({
      provider: "vllm",
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

  it("falls optional role model lists back to the documented defaults", () => {
    const options = modelOptionsFromDiscovery({
      provider: "ollama",
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

  it("keeps the full supported reranker catalog before the API response arrives", () => {
    expect(rerankerOptionsFromCatalog(undefined)).toEqual([...SUPPORTED_RERANKER_MODELS]);
  });

  it("merges API reranker models with the built-in fallback catalog", () => {
    const options = rerankerOptionsFromCatalog({
      models: [
        { model: "jinaai/jina-reranker-v1-turbo-en" },
        { model: "custom/local-reranker" },
      ],
    });

    expect(options[0]).toBe("jinaai/jina-reranker-v1-turbo-en");
    expect(options).toContain("custom/local-reranker");
    expect(options).toContain("BAAI/bge-reranker-base");
    expect(options).toContain("Xenova/ms-marco-MiniLM-L-12-v2");
  });
});
