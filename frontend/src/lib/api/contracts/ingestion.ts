import type {
  ClearanceLevel,
  GraphRAGCancelResponse,
  GraphRAGStatus,
  IngestJobCancelResponse,
  IngestJobListResponse,
  IngestJobOrigin,
  IngestJobRecoveryResponse,
  IngestJobSummary,
  JobStatus,
  StaleIngestJobListResponse,
  UploadResponse,
} from "@/types/api";
import { apiClient } from "./apiClient";

export interface UploadDocumentRequest {
  file: File;
  group_path: string;
  shared_group_paths?: string[];
  clearance_level?: ClearanceLevel | null;
  effective_date?: string | null;
  expiry_date?: string | null;
  doc_type?: string | null;
  description?: string | null;
  supersedes?: string[];
}

export interface IngestJobListRequest {
  status?: string;
  origin?: IngestJobOrigin | "";
  group_path?: string;
  include_descendants?: boolean;
  search?: string;
  created_from?: string;
  created_to?: string;
  uploaded_by_me?: boolean;
  limit?: number;
  offset?: number;
}

export const uploadApi = {
  document: (request: UploadDocumentRequest) => {
    const formData = new FormData();
    formData.set("file", request.file);
    formData.set("group_path", request.group_path);
    if (request.clearance_level) formData.set("clearance_level", request.clearance_level);
    if (request.effective_date) formData.set("effective_date", request.effective_date);
    if (request.expiry_date) formData.set("expiry_date", request.expiry_date);
    if (request.doc_type) formData.set("doc_type", request.doc_type);
    if (request.description) formData.set("description", request.description);

    for (const groupPath of request.shared_group_paths ?? []) {
      formData.append("shared_group_paths", groupPath);
    }

    for (const docId of request.supersedes ?? []) {
      formData.append("supersedes", docId);
    }

    return apiClient.postForm<UploadResponse>("/api/v1/upload", formData);
  },
  status: (jobId: string) => apiClient.get<JobStatus>(`/api/v1/upload/${encodeURIComponent(jobId)}/status`),
};

export const ingestJobsApi = {
  list: (request: IngestJobListRequest = {}) =>
    apiClient.get<IngestJobListResponse>(ingestJobListPath("/api/v1/ingest-jobs", request)),
  summary: (request: Pick<IngestJobListRequest, "created_from" | "created_to" | "group_path"> = {}) =>
    apiClient.get<IngestJobSummary>(ingestJobListPath("/api/v1/ingest-jobs/summary", request)),
  graphragStatus: () => apiClient.get<GraphRAGStatus>("/api/v1/ingest-jobs/graphrag-status"),
  cancelGraphEnrichment: (jobId: string, taskId: string) =>
    apiClient.postJson<GraphRAGCancelResponse>(`/api/v1/ingest-jobs/${encodeURIComponent(jobId)}/graph-enrichment/cancel`, { task_id: taskId }),
  listStale: () => apiClient.get<StaleIngestJobListResponse>("/api/v1/ingest-jobs/stale"),
  cancel: (jobId: string) =>
    apiClient.postJson<IngestJobCancelResponse>(`/api/v1/ingest-jobs/${encodeURIComponent(jobId)}/cancel`, null),
  requeueStale: (jobId: string) =>
    apiClient.postJson<IngestJobRecoveryResponse>(`/api/v1/ingest-jobs/${encodeURIComponent(jobId)}/requeue`, null),
};

function ingestJobListPath(basePath: string, request: IngestJobListRequest): string {
  const params = new URLSearchParams();
  if (request.status) params.set("status", request.status);
  if (request.origin) params.set("origin", request.origin);
  if (request.group_path) params.set("group_path", request.group_path);
  if (request.include_descendants) params.set("include_descendants", "true");
  if (request.search?.trim()) params.set("search", request.search.trim());
  if (request.created_from) params.set("created_from", request.created_from);
  if (request.created_to) params.set("created_to", request.created_to);
  if (request.uploaded_by_me) params.set("uploaded_by_me", "true");
  if (request.limit !== undefined) params.set("limit", String(request.limit));
  if (request.offset !== undefined) params.set("offset", String(request.offset));
  const query = params.toString();
  return query ? `${basePath}?${query}` : basePath;
}
