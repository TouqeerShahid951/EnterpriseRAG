import type { EvaluationDatasetSummary, EvaluationFailureStage, EvaluationRunStatus } from "@/types/api";

export function statusLabel(status: EvaluationRunStatus) {
  const labels: Record<EvaluationRunStatus, string> = {
    queued: "Queued",
    running: "Running",
    complete: "Complete",
    partial: "Partial",
    failed: "Failed",
    cancelled: "Cancelled",
  };
  return labels[status];
}

export function failureStageLabel(stage: EvaluationFailureStage) {
  const labels: Record<EvaluationFailureStage, string> = {
    dataset: "Dataset",
    "ingestion/indexing": "Ingestion / indexing",
    retrieval: "Retrieval",
    "reranking/source_selection": "Source selection",
    answer_content: "Answer content",
    citation: "Citation",
    faithfulness: "Faithfulness",
    degradation: "Degradation",
    runtime: "Runtime",
    latency: "Latency",
  };
  return labels[stage] ?? stage;
}

export function isRunActive(status: EvaluationRunStatus) {
  return status === "queued" || status === "running";
}

export function isRunRetryable(status: EvaluationRunStatus) {
  return status === "failed" || status === "partial" || status === "cancelled";
}

export function numberFromSummary(summary: Record<string, unknown>, key: string, fallback: number) {
  const value = summary[key];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export function failureBreakdownFromSummary(summary: Record<string, unknown> | undefined) {
  const value = summary?.failure_breakdown;
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value).filter(([, count]) => typeof count === "number")) as Record<string, number>;
}

export function ratio(value: number, total: number) {
  return total > 0 ? value / total : 0;
}

export function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function optionalPercent(summary: Record<string, unknown>, keys: string[]) {
  const value = keys.map((key) => summary[key]).find((item) => typeof item === "number" && Number.isFinite(item));
  return typeof value === "number" ? percent(value) : null;
}

export function faithfulnessResultLabel(status: string | null, score: number | null) {
  if (status === "skipped" || status === "pending") return "Not evaluated";
  if (status === "failed") return "Error";
  return score === null ? "Unavailable" : percent(score);
}

export function splitCsv(value: string) {
  return value.split(",").map((part) => part.trim()).filter(Boolean);
}

export function resolveEvaluationDatasetId(datasets: EvaluationDatasetSummary[], requestedDatasetId: string | null, currentDatasetId: string) {
  if (currentDatasetId && datasets.some((dataset) => dataset.id === currentDatasetId)) return currentDatasetId;
  if (requestedDatasetId && datasets.some((dataset) => dataset.id === requestedDatasetId)) return requestedDatasetId;
  return datasets[0]?.id ?? "";
}

export type RagEvalScreen = "overview" | "datasets" | "new-run" | "query-tracker" | "runs";
