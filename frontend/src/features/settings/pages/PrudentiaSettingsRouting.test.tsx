import { describe, expect, it } from "vitest";

import {
  endpointsFromForm,
  providerDefaults,
  ragConfigActionsLocked,
  ragConfigSourceLabel,
  requestFromForm,
  stackTemplateFromForm,
  type RagConfigFormState,
} from "./PrudentiaSettingsPage";
import { ollamaForm } from "./settingsTestFixtures";

describe("inference settings helpers", () => {
  it("normalizes the RAG configuration source for the runtime UI", () => {
    expect(ragConfigSourceLabel("workspace")).toBe("workspace");
    expect(ragConfigSourceLabel("env")).toBe("environment");
    expect(ragConfigSourceLabel("environment")).toBe("environment");
  });

  it.each([
    ["confirmation dialog", { dialogOpen: true, resetPending: false, savePending: false, testPending: false }],
    ["reset request", { dialogOpen: false, resetPending: true, savePending: false, testPending: false }],
    ["save request", { dialogOpen: false, resetPending: false, savePending: true, testPending: false }],
    ["test request", { dialogOpen: false, resetPending: false, savePending: false, testPending: true }],
  ])("locks model routing actions during the %s", (_label, state) => {
    expect(ragConfigActionsLocked(state)).toBe(true);
  });

  it("allows model routing actions when no mutation or reset dialog is active", () => {
    expect(ragConfigActionsLocked({
      dialogOpen: false,
      resetPending: false,
      savePending: false,
      testPending: false,
    })).toBe(false);
  });

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
});
