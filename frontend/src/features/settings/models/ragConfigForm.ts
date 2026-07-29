import type { RagConfigRequest } from "@/lib/api/contracts";
import type { RagConfig } from "@/types/api";
import {
  DEFAULT_FASTEMBED_MODEL,
  DEFAULT_RERANKER_MODEL,
  LANGUAGE_ROLES,
  LOCAL_INFERENCE_HOST,
  MODEL_STATUS_ROLES,
  VLLM_LOCAL_PORTS,
  modelOptionsFromDiscovery,
  rerankerOptionsFromCatalog,
  type EndpointRole,
  type LanguageRole,
} from "@/features/settings/models/ragModelCatalog";
export {
  LANGUAGE_ROLES,
  LOCAL_INFERENCE_HOST,
  MODEL_STATUS_ROLES,
  modelOptionsFromDiscovery,
  rerankerOptionsFromCatalog,
};
export type { EndpointRole, LanguageRole };


export type RagConfigFormState = {
  provider: "ollama" | "vllm";
  embedding_provider: EmbeddingProvider;
  reasoning_provider: RuntimeProvider;
  routing_provider: RuntimeProvider;
  faithfulness_provider: RuntimeProvider;
  ingestion_provider: RuntimeProvider;
  vision_provider: RuntimeProvider;
  inference_location: InferenceLocation;
  host: string;
  port: string;
  embedding_host: string;
  embedding_port: string;
  reasoning_host: string;
  reasoning_port: string;
  routing_host: string;
  routing_port: string;
  faithfulness_host: string;
  faithfulness_port: string;
  ingestion_host: string;
  ingestion_port: string;
  vision_host: string;
  vision_port: string;
  chat_model: string;
  embed_model: string;
  reasoning_model: string;
  sql_generation_model: string;
  routing_model: string;
  faithfulness_model: string;
  ingestion_model: string;
  vision_model: string;
  reranker_model: string;
  thinking_enabled: boolean;
  query_planner_enabled: boolean;
  evidence_gate_policy: RagConfig["evidence_gate_policy"];
  faithfulness_policy: RagConfig["faithfulness_policy"];
  json_num_predict: string;
  retrieval_token_budget: string;
  chat_timeout_seconds: string;
  routing_timeout_seconds: string;
  reasoning_timeout_seconds: string;
  faithfulness_timeout_seconds: string;
  embed_timeout_seconds: string;
};

export type EndpointTarget = {
  host: string;
  port: number;
};

export type RagModelLookupTarget = {
  provider: "ollama" | "vllm";
  embedding_provider: EmbeddingProvider;
  reasoning_provider: RuntimeProvider | null;
  routing_provider: RuntimeProvider | null;
  faithfulness_provider: RuntimeProvider | null;
  ingestion_provider: RuntimeProvider | null;
  vision_provider: RuntimeProvider | null;
  host: string;
  port: number;
  embedding_host: string | null;
  embedding_port: number | null;
  reasoning_host: string | null;
  reasoning_port: number | null;
  routing_host: string | null;
  routing_port: number | null;
  faithfulness_host: string | null;
  faithfulness_port: number | null;
  ingestion_host: string | null;
  ingestion_port: number | null;
  vision_host: string | null;
  vision_port: number | null;
};

type InferenceLocation = "local" | "network";

export type RuntimeProvider = "ollama" | "vllm";

export type EmbeddingProvider = "ollama" | "openai_compatible" | "fastembed";

export const DEFAULT_RAG_FORM: RagConfigFormState = {
  provider: "ollama",
  embedding_provider: "fastembed",
  reasoning_provider: "ollama",
  routing_provider: "ollama",
  faithfulness_provider: "ollama",
  ingestion_provider: "ollama",
  vision_provider: "ollama",
  inference_location: "local",
  host: LOCAL_INFERENCE_HOST,
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
  embed_model: DEFAULT_FASTEMBED_MODEL,
  reasoning_model: "",
  sql_generation_model: "",
  routing_model: "",
  faithfulness_model: "",
  ingestion_model: "",
  vision_model: "",
  reranker_model: DEFAULT_RERANKER_MODEL,
  thinking_enabled: false,
  query_planner_enabled: true,
  evidence_gate_policy: "adaptive",
  faithfulness_policy: "adaptive",
  json_num_predict: "4096",
  retrieval_token_budget: "12000",
  chat_timeout_seconds: "180",
  routing_timeout_seconds: "5",
  reasoning_timeout_seconds: "30",
  faithfulness_timeout_seconds: "30",
  embed_timeout_seconds: "45",
};

export function endpointsFromForm(form: RagConfigFormState): Record<EndpointRole, EndpointTarget> {
  const chatProvider = languageRoleProvider(form, "chat");
  const chat = {
    host: form.host.trim() || LOCAL_INFERENCE_HOST,
    port: Number(form.port) || Number(defaultPortForRole(chatProvider, "chat")),
  };
  const role = (
    name: Exclude<EndpointRole, "chat">,
    fallback: EndpointTarget,
    provider: RuntimeProvider,
    fallbackProvider: RuntimeProvider,
  ) => ({
    host: form[`${name}_host`].trim() || fallback.host,
    port:
      Number(form[`${name}_port`]) ||
      (provider === fallbackProvider ? fallback.port : Number(defaultPortForRole(provider, name))),
  });
  const reasoningProvider = languageRoleProvider(form, "reasoning");
  const routingProvider = languageRoleProvider(form, "routing");
  const faithfulnessProvider = languageRoleProvider(form, "faithfulness");
  const ingestionProvider = languageRoleProvider(form, "ingestion");
  const visionProvider = languageRoleProvider(form, "vision");
  const embeddingProvider = embeddingRuntimeProvider(form.embedding_provider);
  const reasoning = role("reasoning", chat, reasoningProvider, chatProvider);
  const ingestion = role("ingestion", chat, ingestionProvider, chatProvider);
  return {
    chat,
    reasoning,
    routing: role("routing", reasoning, routingProvider, reasoningProvider),
    faithfulness: role("faithfulness", chat, faithfulnessProvider, chatProvider),
    ingestion,
    vision: role("vision", ingestion, visionProvider, ingestionProvider),
    embedding: form.embedding_provider === "fastembed" ? chat : role("embedding", chat, embeddingProvider, chatProvider),
  };
}

export function formFromConfig(config: RagConfig): RagConfigFormState {
  const inference_location = config.host.toLowerCase() === LOCAL_INFERENCE_HOST ? "local" : "network";
  const reasoningHost = config.reasoning_host ?? config.host;
  const reasoningPort = config.reasoning_port ?? config.port;
  const routingHost = config.routing_host ?? reasoningHost;
  const routingPort = config.routing_port ?? reasoningPort;
  const roleOverride = (
    host: string | null | undefined,
    port: number | null | undefined,
    fallbackHost: string,
    fallbackPort: number,
  ) => ({
    host: host && host !== fallbackHost ? host : "",
    port: port && (host !== fallbackHost || port !== fallbackPort) ? String(port) : "",
  });
  const reasoningEndpoint = roleOverride(reasoningHost, reasoningPort, config.host, config.port);
  const routingEndpoint = roleOverride(routingHost, routingPort, reasoningHost, reasoningPort);
  const faithfulnessEndpoint = roleOverride(
    config.faithfulness_host ?? config.host,
    config.faithfulness_port ?? config.port,
    config.host,
    config.port,
  );
  const ingestionEndpoint = roleOverride(
    config.ingestion_host ?? config.host,
    config.ingestion_port ?? config.port,
    config.host,
    config.port,
  );
  const visionEndpoint = roleOverride(
    config.vision_host ?? config.ingestion_host ?? config.host,
    config.vision_port ?? config.ingestion_port ?? config.port,
    config.ingestion_host ?? config.host,
    config.ingestion_port ?? config.port,
  );
  return {
    provider: config.provider ?? "ollama",
    embedding_provider: config.embedding_provider ?? (config.provider === "vllm" ? "openai_compatible" : "ollama"),
    reasoning_provider: config.reasoning_provider ?? config.provider ?? "ollama",
    routing_provider: config.routing_provider ?? config.reasoning_provider ?? config.provider ?? "ollama",
    faithfulness_provider: config.faithfulness_provider ?? config.provider ?? "ollama",
    ingestion_provider: config.ingestion_provider ?? config.provider ?? "ollama",
    vision_provider: config.vision_provider ?? config.ingestion_provider ?? config.provider ?? "ollama",
    inference_location,
    host: config.host || LOCAL_INFERENCE_HOST,
    port: String(config.port || (config.provider === "vllm" ? 8000 : 11434)),
    embedding_host: config.embedding_provider === "fastembed" ? "" : config.embedding_host || "",
    embedding_port: String(config.embedding_port || (config.provider === "vllm" ? 8001 : 11434)),
    reasoning_host: reasoningEndpoint.host,
    reasoning_port: reasoningEndpoint.port,
    routing_host: routingEndpoint.host,
    routing_port: routingEndpoint.port,
    faithfulness_host: faithfulnessEndpoint.host,
    faithfulness_port: faithfulnessEndpoint.port,
    ingestion_host: ingestionEndpoint.host,
    ingestion_port: ingestionEndpoint.port,
    vision_host: visionEndpoint.host,
    vision_port: visionEndpoint.port,
    chat_model: config.chat_model || DEFAULT_RAG_FORM.chat_model,
    embed_model: config.embed_model || DEFAULT_RAG_FORM.embed_model,
    reasoning_model: config.reasoning_model ?? config.routing_model ?? "",
    sql_generation_model: config.sql_generation_model ?? "",
    routing_model: config.routing_model ?? "",
    faithfulness_model: config.faithfulness_model ?? "",
    ingestion_model: config.ingestion_model ?? "",
    vision_model: config.vision_model ?? "",
    reranker_model: config.reranker_model || DEFAULT_RERANKER_MODEL,
    thinking_enabled: Boolean(config.thinking_enabled),
    query_planner_enabled: config.query_planner_enabled ?? true,
    evidence_gate_policy: config.evidence_gate_policy ?? "adaptive",
    faithfulness_policy: config.faithfulness_policy ?? "adaptive",
    json_num_predict: String(config.json_num_predict || DEFAULT_RAG_FORM.json_num_predict),
    retrieval_token_budget: String(config.retrieval_token_budget || DEFAULT_RAG_FORM.retrieval_token_budget),
    chat_timeout_seconds: String(config.chat_timeout_seconds || DEFAULT_RAG_FORM.chat_timeout_seconds),
    routing_timeout_seconds: String(
      config.routing_timeout_seconds || DEFAULT_RAG_FORM.routing_timeout_seconds
    ),
    reasoning_timeout_seconds: String(
      config.reasoning_timeout_seconds || DEFAULT_RAG_FORM.reasoning_timeout_seconds
    ),
    faithfulness_timeout_seconds: String(
      config.faithfulness_timeout_seconds || DEFAULT_RAG_FORM.faithfulness_timeout_seconds
    ),
    embed_timeout_seconds: String(config.embed_timeout_seconds || DEFAULT_RAG_FORM.embed_timeout_seconds),
  };
}

export function requestFromForm(form: RagConfigFormState): RagConfigRequest {
  const endpoints = endpointsFromForm(form);
  const reasoningModel = form.reasoning_model.trim() || null;
  return {
    provider: form.provider,
    embedding_provider: form.embedding_provider,
    reasoning_provider: form.reasoning_provider,
    routing_provider: form.routing_provider,
    faithfulness_provider: form.faithfulness_provider,
    ingestion_provider: form.ingestion_provider,
    vision_provider: form.vision_provider,
    host: endpoints.chat.host,
    port: endpoints.chat.port,
    embedding_host: form.embedding_provider === "fastembed" ? null : endpoints.embedding.host,
    embedding_port: form.embedding_provider === "fastembed" ? null : endpoints.embedding.port,
    reasoning_host: endpoints.reasoning.host,
    reasoning_port: endpoints.reasoning.port,
    routing_host: endpoints.routing.host,
    routing_port: endpoints.routing.port,
    faithfulness_host: endpoints.faithfulness.host,
    faithfulness_port: endpoints.faithfulness.port,
    ingestion_host: endpoints.ingestion.host,
    ingestion_port: endpoints.ingestion.port,
    vision_host: endpoints.vision.host,
    vision_port: endpoints.vision.port,
    chat_model: form.chat_model.trim(),
    embed_model: form.embed_model.trim(),
    reasoning_model: reasoningModel,
    sql_generation_model: form.sql_generation_model.trim() || null,
    routing_model: form.routing_model.trim() || reasoningModel,
    faithfulness_model: form.faithfulness_model.trim() || null,
    ingestion_model: form.ingestion_model.trim() || null,
    vision_model: form.vision_model.trim() || null,
    thinking_enabled: form.thinking_enabled,
    query_planner_enabled: form.query_planner_enabled,
    evidence_gate_policy: form.evidence_gate_policy,
    faithfulness_policy: form.faithfulness_policy,
    json_num_predict: Number(form.json_num_predict),
    retrieval_token_budget: Number(form.retrieval_token_budget),
    reranker_model: form.reranker_model.trim(),
    chat_timeout_seconds: Number(form.chat_timeout_seconds),
    routing_timeout_seconds: Number(form.routing_timeout_seconds),
    reasoning_timeout_seconds: Number(form.reasoning_timeout_seconds),
    faithfulness_timeout_seconds: Number(form.faithfulness_timeout_seconds),
    embed_timeout_seconds: Number(form.embed_timeout_seconds),
  };
}

export function canFetchModelsForEndpoint(endpoint: EndpointTarget): boolean {
  return Boolean(
    endpoint.host &&
      Number.isFinite(endpoint.port) &&
      endpoint.port >= 1 &&
      endpoint.port <= 65535,
  );
}

export function canSubmitRagConfig(form: RagConfigFormState): boolean {
  const request = requestFromForm(form);
  return Boolean(
    request.host &&
      request.chat_model &&
      request.embed_model &&
      request.reranker_model &&
      Number.isFinite(request.port) &&
      request.port >= 1 &&
      request.port <= 65535 &&
      Object.entries(endpointsFromForm(form)).every(([role, endpoint]) =>
        role === "embedding" && form.embedding_provider === "fastembed" ? true : canFetchModelsForEndpoint(endpoint),
      ) &&
      Number.isFinite(request.json_num_predict) &&
      request.json_num_predict >= 256 &&
      request.json_num_predict <= 32768 &&
      Number.isFinite(request.retrieval_token_budget) &&
      request.retrieval_token_budget >= 1000 &&
      request.retrieval_token_budget <= 200000 &&
      Number.isFinite(request.chat_timeout_seconds) &&
      request.chat_timeout_seconds > 0 &&
      Number.isFinite(request.routing_timeout_seconds) &&
      request.routing_timeout_seconds >= 1 &&
      request.routing_timeout_seconds <= 30 &&
      Number.isFinite(request.reasoning_timeout_seconds) &&
      request.reasoning_timeout_seconds >= 1 &&
      request.reasoning_timeout_seconds <= 300 &&
      Number.isFinite(request.faithfulness_timeout_seconds) &&
      request.faithfulness_timeout_seconds >= 1 &&
      request.faithfulness_timeout_seconds <= 300 &&
      Number.isFinite(request.embed_timeout_seconds) &&
      request.embed_timeout_seconds > 0,
  );
}

export function languageRoleProvider(form: RagConfigFormState, role: LanguageRole): RuntimeProvider {
  if (role === "chat") return form.provider;
  return form[`${role}_provider`];
}

export function languageRoleModel(form: RagConfigFormState, role: LanguageRole): string {
  if (role === "chat") return form.chat_model;
  return form[`${role}_model`];
}

export function withLanguageRoleProvider(
  form: RagConfigFormState,
  role: LanguageRole,
  provider: RuntimeProvider,
): RagConfigFormState {
  const next = {
    ...form,
    thinking_enabled: provider === "vllm" && role === "chat" ? false : form.thinking_enabled,
  };
  if (role === "chat") {
    return {
      ...next,
      provider,
      port: defaultPortForRole(provider, role),
      chat_model: "",
    };
  }
  return {
    ...next,
    [`${role}_provider`]: provider,
    [`${role}_host`]: "",
    [`${role}_port`]: role === "vision" && provider === "vllm" ? defaultPortForRole(provider, role) : "",
    [`${role}_model`]: "",
    sql_generation_model: role === "reasoning" ? "" : form.sql_generation_model,
  };
}

export function withLanguageRoleModel(form: RagConfigFormState, role: LanguageRole, model: string): RagConfigFormState {
  if (role === "chat") return { ...form, chat_model: model };
  return { ...form, [`${role}_model`]: model };
}

export function withEmbeddingProvider(form: RagConfigFormState, embedding_provider: EmbeddingProvider): RagConfigFormState {
  return embeddingProviderDefaults({ ...form, embedding_provider });
}

export function embeddingRuntimeProvider(provider: EmbeddingProvider): RuntimeProvider {
  return provider === "openai_compatible" ? "vllm" : "ollama";
}

export function defaultPortForRole(provider: RuntimeProvider, role: EndpointRole): string {
  if (provider === "ollama") return "11434";
  if (role === "embedding") return VLLM_LOCAL_PORTS.embedding;
  if (role === "vision") return VLLM_LOCAL_PORTS.vision;
  return VLLM_LOCAL_PORTS.chat;
}

export function providerDefaults(form: RagConfigFormState): RagConfigFormState {
  const port = defaultPortForRole(form.provider, "chat");
  if (form.provider === "vllm") {
    return embeddingProviderDefaults({
      ...clearModelSelections({
        ...form,
        host: LOCAL_INFERENCE_HOST,
        reasoning_provider: "vllm",
        routing_provider: "vllm",
        faithfulness_provider: "vllm",
        ingestion_provider: "vllm",
        vision_provider: "ollama",
        embedding_provider: "fastembed",
      }),
      port,
      reasoning_port: "",
      routing_port: "",
      faithfulness_port: "",
      ingestion_port: "",
      vision_port: "",
      thinking_enabled: false,
    });
  }
  return embeddingProviderDefaults({
    ...clearModelSelections({
      ...form,
      host: LOCAL_INFERENCE_HOST,
      reasoning_provider: "ollama",
      routing_provider: "ollama",
      faithfulness_provider: "ollama",
      ingestion_provider: "ollama",
      vision_provider: "ollama",
    }),
    port,
    reasoning_port: "",
    routing_port: "",
    faithfulness_port: "",
    ingestion_port: "",
    vision_port: "",
  });
}

function clearModelSelections(form: RagConfigFormState): RagConfigFormState {
  return {
    ...form,
    chat_model: "",
    embed_model: "",
    reasoning_model: "",
    sql_generation_model: "",
    routing_model: "",
    faithfulness_model: "",
    ingestion_model: "",
    vision_model: "",
  };
}

function embeddingProviderDefaults(form: RagConfigFormState): RagConfigFormState {
  if (form.embedding_provider === "fastembed") {
    return {
      ...form,
      embedding_host: "",
      embedding_port: "",
      embed_model: DEFAULT_FASTEMBED_MODEL,
    };
  }
  if (form.embedding_provider === "ollama") {
    return {
      ...form,
      embedding_host: "",
      embedding_port: defaultPortForRole("ollama", "embedding"),
      embed_model: "nomic-embed-text:latest",
    };
  }
  return {
    ...form,
    embedding_host: "",
    embedding_port: defaultPortForRole("vllm", "embedding"),
    embed_model: "",
  };
}

export function discoveryTarget(request: RagConfigRequest): RagModelLookupTarget {
  return {
    provider: request.provider ?? "ollama",
    embedding_provider: request.embedding_provider ?? "fastembed",
    reasoning_provider: request.reasoning_provider ?? null,
    routing_provider: request.routing_provider ?? null,
    faithfulness_provider: request.faithfulness_provider ?? null,
    ingestion_provider: request.ingestion_provider ?? null,
    vision_provider: request.vision_provider ?? null,
    host: request.host,
    port: request.port,
    embedding_host: request.embedding_host ?? null,
    embedding_port: request.embedding_port ?? null,
    reasoning_host: request.reasoning_host ?? null,
    reasoning_port: request.reasoning_port ?? null,
    routing_host: request.routing_host ?? null,
    routing_port: request.routing_port ?? null,
    faithfulness_host: request.faithfulness_host ?? null,
    faithfulness_port: request.faithfulness_port ?? null,
    ingestion_host: request.ingestion_host ?? null,
    ingestion_port: request.ingestion_port ?? null,
    vision_host: request.vision_host ?? null,
    vision_port: request.vision_port ?? null,
  };
}
