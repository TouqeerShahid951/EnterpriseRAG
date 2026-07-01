import { describe, expect, it } from "vitest";

import {
  endpointsFromForm,
  discoveryHealthLabel,
  modelPlaceholderForStatus,
  modelOptionsFromDiscovery,
  providerDefaults,
  requestFromVllmForm,
  requestFromForm,
  rerankerOptionsFromCatalog,
  SUPPORTED_RERANKER_MODELS,
  stackTemplateFromForm,
  thresholdFromPercent,
  thresholdPercentFromConfig,
  type RagConfigFormState,
} from "./PrudentiaSettingsPage";

const ollamaForm: RagConfigFormState = {
  provider: "ollama",
  embedding_provider: "ollama",
  reasoning_provider: "ollama",
  routing_provider: "ollama",
  faithfulness_provider: "ollama",
  ingestion_provider: "ollama",
  vision_provider: "ollama",
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
  vision_host: "",
  vision_port: "11434",
  chat_model: "llama3.1:8b",
  embed_model: "nomic-embed-text:latest",
  reasoning_model: "",
  routing_model: "",
  faithfulness_model: "",
  ingestion_model: "",
  vision_model: "",
  reranker_model: "jinaai/jina-reranker-v1-turbo-en",
  thinking_enabled: true,
  query_planner_enabled: true,
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
      ...providerDefaults({ ...ollamaForm, provider: "vllm" }),
      embedding_provider: "openai_compatible" as const,
      host: "vllm.local",
      port: "8000",
      reasoning_host: "reasoning.local",
      routing_host: "routing.local",
      faithfulness_host: "judge.local",
      ingestion_host: "metadata.local",
      vision_host: "vision.local",
      embedding_host: "embeddings.local",
      embedding_port: "8001",
      reasoning_port: "8002",
      routing_port: "8003",
      faithfulness_port: "8004",
      ingestion_port: "8005",
      vision_port: "8006",
      chat_model: "qwen3",
      embed_model: "bge-m3",
    };
    const request = requestFromForm(form);

    expect(request).toMatchObject({
      provider: "vllm",
      embedding_provider: "openai_compatible",
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
      vision_host: "vision.local",
      vision_port: 8006,
      thinking_enabled: false,
      query_planner_enabled: true,
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

  it("maps the query planner switch into the saved config request", () => {
    const request = requestFromForm({
      ...ollamaForm,
      query_planner_enabled: false,
    });

    expect(request.query_planner_enabled).toBe(false);
  });

  it("uses compose local vLLM ports and keeps embeddings independently configurable", () => {
    const form = providerDefaults({ ...ollamaForm, provider: "vllm" });
    const endpoints = endpointsFromForm(form);

    expect(stackTemplateFromForm(form)).toBe("vllm");
    expect(form.port).toBe("8010");
    expect(form.embedding_provider).toBe("fastembed");
    expect(form.embedding_port).toBe("");
    expect(form.vision_provider).toBe("ollama");
    expect(form.reasoning_port).toBe("");
    expect(form.routing_port).toBe("");
    expect(endpoints.reasoning).toEqual(endpoints.chat);
    expect(endpoints.routing).toEqual(endpoints.chat);
    expect(endpoints.faithfulness).toEqual(endpoints.chat);
    expect(endpoints.ingestion).toEqual(endpoints.chat);
    expect(endpoints.vision).toEqual({ host: "host.docker.internal", port: 11434 });
    expect(endpoints.embedding).toEqual(endpoints.chat);
    expect(form.chat_model).toBe("");
    expect(form.embed_model).toBe("nomic-ai/nomic-embed-text-v1.5-Q");
    expect(form.reranker_model).toBe("jinaai/jina-reranker-v1-turbo-en");
  });

  it("marks mixed provider edits as a custom stack", () => {
    const form = providerDefaults({ ...ollamaForm, provider: "vllm" });

    expect(stackTemplateFromForm({ ...form, vision_provider: "vllm" })).toBe("custom");
  });

  it("lets a network endpoint be expressed directly through host and port fields", () => {
    const form = {
      ...providerDefaults({ ...ollamaForm, provider: "vllm" }),
      host: "vllm.private",
      port: "8000",
      chat_model: "network-chat",
    };
    const endpoints = endpointsFromForm(form);
    const request = requestFromForm(form);

    expect(endpoints.chat).toEqual({ host: "vllm.private", port: 8000 });
    expect(request.host).toBe("vllm.private");
    expect(request.port).toBe(8000);
    expect(request.chat_model).toBe("network-chat");
  });

  it("defaults mixed local role providers to their own service ports", () => {
    const form: RagConfigFormState = {
      ...ollamaForm,
      provider: "ollama",
      reasoning_provider: "vllm",
      vision_provider: "vllm",
      reasoning_port: "",
      vision_port: "",
    };
    const endpoints = endpointsFromForm(form);

    expect(endpoints.chat).toEqual({ host: "host.docker.internal", port: 11434 });
    expect(endpoints.reasoning).toEqual({ host: "host.docker.internal", port: 8010 });
    expect(endpoints.vision).toEqual({ host: "host.docker.internal", port: 8016 });
  });

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

  it("converts OCR review threshold between config fraction and UI percent", () => {
    expect(thresholdPercentFromConfig(0.9)).toBe(90);
    expect(thresholdFromPercent(90)).toBe(0.9);
    expect(thresholdFromPercent(89)).toBe(0.89);
  });

  it("targets one vLLM service when applying launch limits", () => {
    const request = requestFromVllmForm({
      text: {
        max_model_len: "4096",
        gpu_memory_utilization: "0.12",
        max_num_seqs: "1",
        max_num_batched_tokens: "4096",
        kv_cache_memory_bytes: "2G",
      },
      embeddings: {
        max_model_len: "2048",
        gpu_memory_utilization: "0.05",
        max_num_seqs: "2",
        max_num_batched_tokens: "2048",
        kv_cache_memory_bytes: "",
      },
      vision: {
        max_model_len: "2048",
        gpu_memory_utilization: "0.1",
        max_num_seqs: "1",
        max_num_batched_tokens: "2048",
        kv_cache_memory_bytes: "2G",
      },
    }, ["text"]);

    expect(request.services).toEqual(["text"]);
    expect(request.text.kv_cache_memory_bytes).toBe("2G");
    expect(request.embeddings.kv_cache_memory_bytes).toBeNull();
  });
});
