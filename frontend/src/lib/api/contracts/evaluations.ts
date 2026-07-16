import type {
  EvaluationDatasetDetail,
  EvaluationDatasetSummary,
  EvaluationRunDetail,
  EvaluationRunSummary,
} from "@/types/api";
import { apiClient } from "./apiClient";

export interface EvaluationDatasetImportRequest {
  name?: string | null;
  content: string;
  source_format?: "auto" | "json" | "jsonl";
}

export interface EvaluationRunCreateRequest {
  dataset_id: string;
  group_path?: string | null;
  document_ids?: string[];
  case_ids?: string[];
  limit?: number | null;
}

export const ragEvaluationsApi = {
  listDatasets: () => apiClient.get<{ items: EvaluationDatasetSummary[]; total: number }>("/api/v1/rag-evaluations/datasets"),
  importDataset: (request: EvaluationDatasetImportRequest) =>
    apiClient.postJson<EvaluationDatasetDetail>("/api/v1/rag-evaluations/datasets", request),
  getDataset: (datasetId: string) =>
    apiClient.get<EvaluationDatasetDetail>(`/api/v1/rag-evaluations/datasets/${encodeURIComponent(datasetId)}`),
  listRuns: () => apiClient.get<{ items: EvaluationRunSummary[]; total: number }>("/api/v1/rag-evaluations/runs"),
  createRun: (request: EvaluationRunCreateRequest) =>
    apiClient.postJson<EvaluationRunSummary>("/api/v1/rag-evaluations/runs", request),
  getRun: (runId: string) =>
    apiClient.get<EvaluationRunDetail>(`/api/v1/rag-evaluations/runs/${encodeURIComponent(runId)}`),
  cancelRun: (runId: string) =>
    apiClient.postJson<{ run: EvaluationRunSummary }>(`/api/v1/rag-evaluations/runs/${encodeURIComponent(runId)}/cancel`, null),
  retryRun: (runId: string) =>
    apiClient.postJson<{ run: EvaluationRunSummary }>(`/api/v1/rag-evaluations/runs/${encodeURIComponent(runId)}/retry`, null),
};
