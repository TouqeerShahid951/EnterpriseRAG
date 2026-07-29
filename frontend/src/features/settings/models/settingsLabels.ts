import type { RagConfig, RagModelDiscoveryResult, RagModelDiscoveryStatus } from "@/types/api";
import {
  type EmbeddingProvider,
  type EndpointRole,
  LANGUAGE_ROLES,
  type LanguageRole,
  type RagConfigFormState,
  type RuntimeProvider,
  endpointsFromForm,
  languageRoleProvider,
} from "@/features/settings/models/ragConfigForm";

export type StackTemplate = "ollama" | "vllm" | "custom";

export function providerName(provider: string) {
  return provider === "vllm" ? "vLLM" : "Ollama";
}

export function activeStackLabel(config: RagConfig) {
  const provider = providerName(config.provider);
  const embedding = embeddingProviderName(config.embedding_provider);
  const vision = config.vision_model?.trim()
    ? `${providerName(config.vision_provider ?? config.ingestion_provider ?? config.provider)} vision`
    : "vision not configured";
  return `${provider} text, ${embedding} embeddings, ${vision}`;
}

export function ragConfigSourceLabel(source: RagConfig["source"]): string {
  const normalizedSource = source.trim().toLowerCase();
  if (normalizedSource === "workspace") return "workspace";
  if (normalizedSource === "env" || normalizedSource === "environment") return "environment";
  return normalizedSource || "environment";
}

export function ragConfigActionsLocked({
  dialogOpen,
  resetPending,
  savePending,
  testPending,
}: {
  dialogOpen: boolean;
  resetPending: boolean;
  savePending: boolean;
  testPending: boolean;
}): boolean {
  return dialogOpen || resetPending || savePending || testPending;
}

export function activeVisionStatus(config: RagConfig): { endpoint: string | null; model: string } {
  const visionModel = config.vision_model?.trim();
  if (!visionModel) return { endpoint: null, model: "Not configured" };
  return {
    endpoint: config.vision_base_url ?? config.ingestion_base_url ?? config.base_url,
    model: `${providerName(config.vision_provider ?? config.ingestion_provider ?? config.provider)}: ${visionModel}`,
  };
}

export function stackTemplateFromForm(form: RagConfigFormState): StackTemplate {
  const ollamaLanguage =
    form.provider === "ollama" &&
    form.reasoning_provider === "ollama" &&
    form.routing_provider === "ollama" &&
    form.faithfulness_provider === "ollama" &&
    form.ingestion_provider === "ollama" &&
    form.vision_provider === "ollama";
  if (ollamaLanguage) return "ollama";
  const vllmTextStack =
    form.provider === "vllm" &&
    form.reasoning_provider === "vllm" &&
    form.routing_provider === "vllm" &&
    form.faithfulness_provider === "vllm" &&
    form.ingestion_provider === "vllm" &&
    form.vision_provider === "ollama" &&
    form.embedding_provider === "fastembed";
  return vllmTextStack ? "vllm" : "custom";
}

export function stackTemplateLabel(template: StackTemplate) {
  if (template === "vllm") return "vLLM text stack";
  if (template === "ollama") return "Ollama local";
  return "Custom role mix";
}

export function roleAssignmentSummary(form: RagConfigFormState) {
  const vllmCount = LANGUAGE_ROLES.filter((role) => languageRoleProvider(form, role) === "vllm").length;
  const ollamaCount = LANGUAGE_ROLES.length - vllmCount;
  return `${vllmCount} vLLM, ${ollamaCount} Ollama, ${embeddingProviderName(form.embedding_provider)}`;
}

export function behaviorSummaryFromForm(form: RagConfigFormState) {
  return `Planner ${form.query_planner_enabled ? "on" : "off"}, gate ${form.evidence_gate_policy}, checker ${form.faithfulness_policy}`;
}

export function discoveryHealthLabel(
  result: RagModelDiscoveryResult | undefined,
  loading: boolean,
  error: Error | null,
) {
  if (loading) return "Checking services";
  if (error) return "Check failed";
  const statuses = Object.values(result?.model_statuses ?? {});
  if (statuses.length === 0) return "Not checked";
  const errors = statuses.filter((status) => status.status === "error").length;
  const empty = statuses.filter((status) => status.status === "empty").length;
  if (errors > 0) return `${errors} service${errors === 1 ? "" : "s"} need attention`;
  if (empty > 0) return `${empty} catalog${empty === 1 ? "" : "s"} empty`;
  return "All selected services responded";
}

export function statusTone(status: RagModelDiscoveryStatus | undefined): "ok" | "warning" | "error" | "neutral" {
  if (!status) return "neutral";
  if (status.status === "ok") return "ok";
  if (status.status === "empty") return "warning";
  if (status.status === "error") return "error";
  return "neutral";
}

export function modelPlaceholderForStatus(
  status: RagModelDiscoveryStatus | undefined,
  options: { canFetch: boolean; loading: boolean },
) {
  const { canFetch, loading } = options;
  if (!canFetch) return "Enter host and port";
  if (loading) return "Loading models";
  if (status?.status === "error" || status?.status === "empty") return status.message;
  return "Choose model";
}

export function endpointLabel(form: RagConfigFormState, role: EndpointRole, provider: RuntimeProvider) {
  if (role === "embedding" && form.embedding_provider === "fastembed") return "Local FastEmbed cache";
  const endpoint = endpointsFromForm(form)[role];
  const service = providerName(provider);
  return `${service} at ${endpoint.host}:${endpoint.port}`;
}

export function roleModelInheritance(role: LanguageRole, modelValue: string) {
  if (modelValue.trim()) return "Explicit model";
  if (role === "reasoning") return "Uses synthesis model";
  if (role === "routing") return "Uses reasoning model";
  if (role === "vision") return "Uses ingestion model";
  return role === "chat" ? "Required model" : "Uses synthesis model";
}

export function embeddingProviderName(provider: EmbeddingProvider) {
  if (provider === "fastembed") return "FastEmbed local";
  if (provider === "openai_compatible") return "OpenAI-compatible";
  return "Ollama";
}

export function formatLatency(value: number | null) {
  return value === null ? "Not measured" : `${value} ms`;
}

export function labelize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function safeWorkerConcurrency(value: number | null | undefined) {
  return Number.isFinite(value) ? Number(value) : 1;
}

export function isValidWorkerConcurrency(value: number) {
  return Number.isFinite(value) && value >= 1 && value <= 10;
}

export function isValidThresholdPercent(value: number) {
  return Number.isFinite(value) && value >= 0 && value <= 100;
}

export function safePdfImageReviewThreshold(value: number | null | undefined) {
  return Number.isFinite(value) ? Number(value) : 64;
}

export function isValidPdfImageReviewThreshold(value: number) {
  return Number.isInteger(value) && value >= 0 && value <= 10000;
}

export function pdfImageReviewThresholdLabel(value: number | null | undefined): string {
  const threshold = safePdfImageReviewThreshold(value);
  return threshold > 0 ? `Above ${threshold} images` : "Off";
}

export function thresholdPercentFromConfig(value: number | null | undefined): number {
  return Number.isFinite(value) ? Math.round(Number(value) * 100) : 90;
}

export function thresholdFromPercent(value: number): number {
  if (!Number.isFinite(value)) return 0.9;
  return Math.max(0, Math.min(1, Number((value / 100).toFixed(4))));
}
