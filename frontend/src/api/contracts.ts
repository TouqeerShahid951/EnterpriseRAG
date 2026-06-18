import { ApiClient } from "./client";
import { getConfiguredBaseUrl, normalizeBaseUrl } from "./url";
import type {
  Document,
  DeleteDocumentResponse,
  DocumentIngestStatus,
  DocumentReingestResponse,
  AuditEventListResponse,
  Group,
  FolderRun,
  FolderRunItem,
  FolderSchedule,
  FolderScheduleType,
  JobStatus,
  IngestJobListResponse,
  IngestJobOrigin,
  IngestJobCancelResponse,
  IngestJobRecoveryResponse,
  IngestJobSummary,
  StaleIngestJobListResponse,
  ArtifactJobDetail,
  ArtifactJobSummary,
  EvaluationDatasetDetail,
  EvaluationDatasetSummary,
  EvaluationRunDetail,
  EvaluationRunSummary,
  GeneratedArtifact,
  LoginResponse,
  AccountType,
  ClearanceLevel,
  QueryRequest,
  RagConfig,
  IngestConfig,
  RagModelDiscoveryResult,
  RagConfigTestResult,
  RerankerModelsResponse,
  RagSseEvent,
  RAGResponse,
  ReviewItem,
  ReviewDecisionResponse,
  RecurrenceWindow,
  SourceAnchor,
  UploadResponse,
  User,
  UserAdmin,
  VersionChainResponse,
  VllmDeploymentConfig,
  VllmServiceDeploymentLimits,
} from "../types/api";
import type { ChatTurn, SavedChatSession, SavedChatSessionPage, SavedChatSessionSummary } from "../types/chat";

export interface LoginRequest {
  email: string;
  password: string;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface UploadDocumentRequest {
  file: File;
  group_path: string;
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
  limit?: number;
  offset?: number;
}

export interface AuditEventListRequest {
  search?: string;
  category?: string;
  event_type?: string;
  actor_id?: string;
  target_type?: string;
  target_id?: string;
  group_path?: string;
  created_from?: string;
  created_to?: string;
  limit?: number;
  offset?: number;
}

export interface CreateSnapshotScheduleRequest {
  files: File[];
  relative_paths: string[];
  name: string;
  group_path: string;
  clearance_level?: ClearanceLevel | null;
  effective_date?: string | null;
  expiry_date?: string | null;
  doc_type?: string | null;
  description?: string | null;
  schedule_type: FolderScheduleType;
  timezone: string;
  scheduled_at?: string | null;
  recurrence?: RecurrenceWindow | null;
}

export interface CreateMinioPrefixScheduleRequest {
  name: string;
  bucket: string;
  prefix: string;
  group_path: string;
  clearance_level?: ClearanceLevel | null;
  effective_date?: string | null;
  expiry_date?: string | null;
  doc_type?: string | null;
  description?: string | null;
  schedule_type: FolderScheduleType;
  timezone: string;
  scheduled_at?: string | null;
  recurrence?: RecurrenceWindow | null;
}

export interface UpdateFolderScheduleRequest {
  schedule_type: FolderScheduleType;
  timezone: string;
  scheduled_at?: string | null;
  recurrence?: RecurrenceWindow | null;
}

export interface CreateGroupRequest {
  path: string;
  name: string;
}

export interface UpdateGroupRequest {
  path: string;
  name: string;
}

export interface DeleteGroupRequest {
  path: string;
}

export interface DocumentListRequest {
  state?: "active" | "deleted";
  group_path?: string | null;
  include_descendants?: boolean;
}

export interface UpdateDocumentClearanceRequest {
  clearance_level: ClearanceLevel;
}

export interface CreateUserRequest {
  email: string;
  name: string;
  account_type: AccountType;
  initial_password: string;
  group_paths: string[];
  clearance_level?: ClearanceLevel | null;
  is_active?: boolean;
}

export interface UpdateUserRequest {
  name?: string | null;
  account_type?: AccountType | null;
  group_paths?: string[] | null;
  clearance_level?: ClearanceLevel | null;
  is_active?: boolean | null;
}

export interface UserGroupRequest {
  group_path: string;
}

export interface RagConfigRequest {
  provider?: "ollama" | "vllm";
  host: string;
  port: number;
  embedding_host?: string | null;
  embedding_port?: number | null;
  reasoning_host?: string | null;
  reasoning_port?: number | null;
  routing_host?: string | null;
  routing_port?: number | null;
  faithfulness_host?: string | null;
  faithfulness_port?: number | null;
  ingestion_host?: string | null;
  ingestion_port?: number | null;
  chat_model: string;
  embed_model: string;
  reasoning_model?: string | null;
  routing_model?: string | null;
  faithfulness_model?: string | null;
  ingestion_model?: string | null;
  vision_model?: string | null;
  thinking_enabled: boolean;
  json_num_predict: number;
  retrieval_token_budget: number;
  reranker_model: string;
  chat_timeout_seconds: number;
  embed_timeout_seconds: number;
}

export interface IngestConfigRequest {
  worker_concurrency: number;
  ocr_review_confidence_threshold: number;
}

export interface VllmDeploymentConfigRequest {
  text: VllmServiceDeploymentLimits;
  embeddings: VllmServiceDeploymentLimits;
  vision: VllmServiceDeploymentLimits;
}

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

export interface RagModelDiscoveryRequest {
  provider?: "ollama" | "vllm";
  host: string;
  port: number;
  embedding_host?: string | null;
  embedding_port?: number | null;
  reasoning_host?: string | null;
  reasoning_port?: number | null;
  routing_host?: string | null;
  routing_port?: number | null;
  faithfulness_host?: string | null;
  faithfulness_port?: number | null;
  ingestion_host?: string | null;
  ingestion_port?: number | null;
  timeout_seconds?: number;
}

interface ChatSessionResponse {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  turns: unknown[];
}

interface ChatSessionSummaryResponse {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  question_count?: number;
  turns?: unknown[];
}

interface ChatSessionListResponse {
  items: ChatSessionSummaryResponse[];
  total: number;
  limit?: number;
  offset?: number;
}

export interface ChatSessionListRequest {
  limit?: number;
  offset?: number;
}

export const apiClient = new ApiClient();

export const authApi = {
  login: (request: LoginRequest) => apiClient.postJson<LoginResponse>("/api/v1/auth/login", request),
  currentUser: () => apiClient.get<User>("/api/v1/auth/me"),
  refresh: () => apiClient.postJson<LoginResponse>("/api/v1/auth/refresh", null),
  logout: () => apiClient.postJson<void>("/api/v1/auth/logout", null),
  changePassword: (request: ChangePasswordRequest) => apiClient.postJson<User>("/api/v1/auth/change-password", request),
};

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
  listStale: () => apiClient.get<StaleIngestJobListResponse>("/api/v1/ingest-jobs/stale"),
  cancel: (jobId: string) =>
    apiClient.postJson<IngestJobCancelResponse>(`/api/v1/ingest-jobs/${encodeURIComponent(jobId)}/cancel`, null),
  requeueStale: (jobId: string) =>
    apiClient.postJson<IngestJobRecoveryResponse>(`/api/v1/ingest-jobs/${encodeURIComponent(jobId)}/requeue`, null),
};

export const folderIngestApi = {
  listSchedules: () => apiClient.get<{ items: FolderSchedule[]; total: number }>("/api/v1/folder-ingest/schedules"),
  createSnapshot: (request: CreateSnapshotScheduleRequest) => {
    const formData = new FormData();
    request.files.forEach((file) => formData.append("files", file));
    request.relative_paths.forEach((relativePath) => formData.append("relative_paths", relativePath));
    formData.set("name", request.name);
    formData.set("group_path", request.group_path);
    if (request.clearance_level) formData.set("clearance_level", request.clearance_level);
    if (request.effective_date) formData.set("effective_date", request.effective_date);
    if (request.expiry_date) formData.set("expiry_date", request.expiry_date);
    if (request.doc_type) formData.set("doc_type", request.doc_type);
    if (request.description) formData.set("description", request.description);
    formData.set("schedule_type", request.schedule_type);
    formData.set("timezone", request.timezone);
    if (request.scheduled_at) formData.set("scheduled_at", request.scheduled_at);
    formData.set("recurrence_json", JSON.stringify(request.recurrence ?? {}));
    return apiClient.postForm<FolderSchedule>("/api/v1/folder-ingest/schedules/snapshot", formData);
  },
  createMinioPrefix: (request: CreateMinioPrefixScheduleRequest) =>
    apiClient.postJson<FolderSchedule>("/api/v1/folder-ingest/schedules/minio-prefix", request),
  updateSchedule: (scheduleId: string, request: UpdateFolderScheduleRequest) =>
    apiClient.request<FolderSchedule>(`/api/v1/folder-ingest/schedules/${encodeURIComponent(scheduleId)}`, {
      method: "PATCH",
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
    }),
  pauseSchedule: (scheduleId: string) =>
    apiClient.postJson<{ id: string; status: FolderSchedule["status"] }>(`/api/v1/folder-ingest/schedules/${encodeURIComponent(scheduleId)}/pause`, null),
  resumeSchedule: (scheduleId: string) =>
    apiClient.postJson<{ id: string; status: FolderSchedule["status"] }>(`/api/v1/folder-ingest/schedules/${encodeURIComponent(scheduleId)}/resume`, null),
  cancelSchedule: (scheduleId: string) =>
    apiClient.postJson<{ id: string; status: FolderSchedule["status"] }>(`/api/v1/folder-ingest/schedules/${encodeURIComponent(scheduleId)}/cancel`, null),
  listRuns: (scheduleId: string) =>
    apiClient.get<{ items: FolderRun[]; total: number }>(`/api/v1/folder-ingest/schedules/${encodeURIComponent(scheduleId)}/runs`),
  listRunItems: (runId: string) =>
    apiClient.get<{ items: FolderRunItem[]; total: number }>(`/api/v1/folder-ingest/runs/${encodeURIComponent(runId)}/items`),
};

export const queryApi = {
  ask: (request: QueryRequest) => apiClient.postJson<RAGResponse>("/api/v1/query", request),
  stream: (request: QueryRequest, init?: RequestInit) => apiClient.postJsonSse<RagSseEvent>("/api/v1/query/stream", request, init),
  getArtifactJob: (jobId: string) =>
    apiClient.get<ArtifactJobDetail>(`/api/v1/artifact-jobs/${encodeURIComponent(jobId)}`),
  clarifyArtifactJob: (jobId: string, answers: Record<string, string>) =>
    apiClient.postJson<{ job: ArtifactJobSummary }>(`/api/v1/artifact-jobs/${encodeURIComponent(jobId)}/clarifications`, { answers }),
  cancelArtifactJob: (jobId: string) =>
    apiClient.postJson<{ job: ArtifactJobSummary }>(`/api/v1/artifact-jobs/${encodeURIComponent(jobId)}/cancel`, null),
  retryArtifactJob: (jobId: string) =>
    apiClient.postJson<{ job: ArtifactJobSummary }>(`/api/v1/artifact-jobs/${encodeURIComponent(jobId)}/retry`, null),
  listSessions: async (request: ChatSessionListRequest = {}): Promise<SavedChatSessionPage> => {
    const response = await apiClient.get<ChatSessionListResponse>(chatSessionListPath(request));
    return {
      ...response,
      limit: response.limit ?? request.limit ?? response.items.length,
      offset: response.offset ?? request.offset ?? 0,
      items: response.items.map(normalizeChatSessionSummary),
    };
  },
  getSession: async (sessionId: string) =>
    normalizeChatSession(await apiClient.get<ChatSessionResponse>(`/api/v1/query/sessions/${encodeURIComponent(sessionId)}`)),
  deleteSession: (sessionId: string) =>
    apiClient.delete<void>(`/api/v1/query/sessions/${encodeURIComponent(sessionId)}`),
  artifactContentUrl: (artifact: Pick<GeneratedArtifact, "download_url">) =>
    artifact.download_url.startsWith("http")
      ? artifact.download_url
      : `${normalizeBaseUrl(getConfiguredBaseUrl())}${artifact.download_url.startsWith("/") ? artifact.download_url : `/${artifact.download_url}`}`,
};

export const documentsApi = {
  list: async (request: DocumentListRequest = {}) => {
    const response = await apiClient.get<{ items: Document[]; total: number }>(documentListPath(request));
    return { ...response, items: response.items.map(normalizeDocument) };
  },
  get: async (documentId: string) => normalizeDocument(await apiClient.get<Document>(`/api/v1/docs/${encodeURIComponent(documentId)}`)),
  source: (documentId: string, chunkId: string) =>
    apiClient.get<SourceAnchor>(`/api/v1/docs/${encodeURIComponent(documentId)}/sources/${encodeURIComponent(chunkId)}`),
  contentPath: documentContentPath,
  contentUrl: (documentId: string) => `${normalizeBaseUrl(getConfiguredBaseUrl())}${documentContentPath(documentId)}`,
  content: (documentId: string, init?: RequestInit) => apiClient.fetchRaw(documentContentPath(documentId), init),
  imageAssetContentPath: documentImageAssetContentPath,
  imageAssetContentUrl: (documentId: string, assetId: string) =>
    `${normalizeBaseUrl(getConfiguredBaseUrl())}${documentImageAssetContentPath(documentId, assetId)}`,
  imageAssetContent: (documentId: string, assetId: string, init?: RequestInit) =>
    apiClient.fetchRaw(documentImageAssetContentPath(documentId, assetId), init),
  versions: (documentId: string) =>
    apiClient.get<VersionChainResponse>(`/api/v1/docs/${encodeURIComponent(documentId)}/versions`),
  remove: (documentId: string) =>
    apiClient.delete<DeleteDocumentResponse>(`/api/v1/docs/${encodeURIComponent(documentId)}`),
  permanentlyRemove: (documentId: string) =>
    apiClient.delete<DeleteDocumentResponse>(`/api/v1/docs/${encodeURIComponent(documentId)}/permanent`),
  reingest: (documentId: string) =>
    apiClient.postJson<DocumentReingestResponse>(`/api/v1/docs/${encodeURIComponent(documentId)}/reingest`, null),
  restore: (documentId: string) =>
    apiClient.postJson<DocumentReingestResponse>(`/api/v1/docs/${encodeURIComponent(documentId)}/restore`, null),
  updateClearance: async (documentId: string, request: UpdateDocumentClearanceRequest) =>
    normalizeDocument(await apiClient.request<Document>(`/api/v1/docs/${encodeURIComponent(documentId)}/clearance`, {
      method: "PATCH",
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
    })),
  supersede: (documentId: string, supersedes: string[]) =>
    apiClient.postJson<VersionChainResponse>(`/api/v1/docs/${encodeURIComponent(documentId)}/supersede`, { supersedes }),
};

function documentListPath(request: DocumentListRequest) {
  const params = new URLSearchParams();
  if (request.state && request.state !== "active") params.set("state", request.state);
  if (request.group_path) params.set("group_path", request.group_path);
  if (request.include_descendants) params.set("include_descendants", "true");
  const query = params.toString();
  return query ? `/api/v1/docs?${query}` : "/api/v1/docs";
}

function documentContentPath(documentId: string) {
  return `/api/v1/docs/${encodeURIComponent(documentId)}/content`;
}

function documentImageAssetContentPath(documentId: string, assetId: string) {
  return `/api/v1/docs/${encodeURIComponent(documentId)}/image-assets/${encodeURIComponent(assetId)}/content`;
}

function normalizeChatSession(session: ChatSessionResponse): SavedChatSession {
  const turns = session.turns.filter(isChatTurn);
  return {
    id: session.id,
    title: session.title,
    createdAt: session.created_at,
    updatedAt: session.updated_at,
    questionCount: turns.filter((turn) => turn.role === "user").length,
    turns,
  };
}

function normalizeChatSessionSummary(session: ChatSessionSummaryResponse): SavedChatSessionSummary {
  const fallbackTurns = session.turns?.filter(isChatTurn) ?? [];
  return {
    id: session.id,
    title: session.title,
    createdAt: session.created_at,
    updatedAt: session.updated_at,
    questionCount: session.question_count ?? fallbackTurns.filter((turn) => turn.role === "user").length,
  };
}

function chatSessionListPath(request: ChatSessionListRequest): string {
  const params = new URLSearchParams();
  if (request.limit !== undefined) params.set("limit", String(request.limit));
  if (request.offset !== undefined) params.set("offset", String(request.offset));
  const query = params.toString();
  return query ? `/api/v1/query/sessions?${query}` : "/api/v1/query/sessions";
}

function isChatTurn(value: unknown): value is ChatTurn {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ChatTurn>;
  if (candidate.role === "user") {
    return typeof candidate.id === "string" && typeof candidate.content === "string" && typeof candidate.createdAt === "string";
  }
  if (candidate.role === "assistant") {
    return typeof candidate.id === "string" && typeof candidate.question === "string" && typeof candidate.createdAt === "string";
  }
  return false;
}

const DOCUMENT_INGEST_STATUSES: DocumentIngestStatus[] = ["scheduled", "queued", "processing", "complete", "failed", "human_review", "cancelled", "unknown"];

function ingestJobListPath(basePath: string, request: IngestJobListRequest): string {
  const params = new URLSearchParams();
  if (request.status) params.set("status", request.status);
  if (request.origin) params.set("origin", request.origin);
  if (request.group_path) params.set("group_path", request.group_path);
  if (request.include_descendants) params.set("include_descendants", "true");
  if (request.search?.trim()) params.set("search", request.search.trim());
  if (request.created_from) params.set("created_from", request.created_from);
  if (request.created_to) params.set("created_to", request.created_to);
  if (request.limit !== undefined) params.set("limit", String(request.limit));
  if (request.offset !== undefined) params.set("offset", String(request.offset));
  const query = params.toString();
  return query ? `${basePath}?${query}` : basePath;
}

function normalizeDocument(document: Document): Document {
  const status = DOCUMENT_INGEST_STATUSES.includes(document.ingest_status) ? document.ingest_status : "unknown";
  return {
    ...document,
    clearance_level: document.clearance_level ?? "NATO_RESTRICTED",
    topics: Array.isArray(document.topics) ? document.topics : [],
    llm_topics: Array.isArray(document.llm_topics) ? document.llm_topics : [],
    entities: Array.isArray(document.entities) ? document.entities : [],
    cross_references: Array.isArray(document.cross_references) ? document.cross_references : [],
    claims: Array.isArray(document.claims) ? document.claims : [],
    ingest_status: status,
    deleted_at: document.deleted_at ?? null,
  };
}

export const auditApi = {
  list: (request: AuditEventListRequest = {}) => apiClient.get<AuditEventListResponse>(auditListPath(request)),
};

function auditListPath(request: AuditEventListRequest): string {
  const params = new URLSearchParams();
  setTrimmedParam(params, "search", request.search);
  setTrimmedParam(params, "category", request.category);
  setTrimmedParam(params, "event_type", request.event_type);
  setTrimmedParam(params, "actor_id", request.actor_id);
  setTrimmedParam(params, "target_type", request.target_type);
  setTrimmedParam(params, "target_id", request.target_id);
  setTrimmedParam(params, "group_path", request.group_path);
  if (request.created_from) params.set("created_from", request.created_from);
  if (request.created_to) params.set("created_to", request.created_to);
  if (request.limit !== undefined) params.set("limit", String(request.limit));
  if (request.offset !== undefined) params.set("offset", String(request.offset));
  const query = params.toString();
  return query ? `/api/v1/audit-log?${query}` : "/api/v1/audit-log";
}

function setTrimmedParam(params: URLSearchParams, key: string, value: string | undefined) {
  const trimmed = value?.trim();
  if (trimmed) params.set(key, trimmed);
}

export const adminApi = {
  listGroups: () => apiClient.get<{ items: Group[] }>("/api/v1/admin/groups"),
  createGroup: (request: CreateGroupRequest) => apiClient.postJson<Group>("/api/v1/admin/groups", request),
  updateGroup: (request: UpdateGroupRequest) => apiClient.putJson<Group>("/api/v1/admin/groups", request),
  deleteGroup: (request: DeleteGroupRequest) =>
    apiClient.request<void>("/api/v1/admin/groups", {
      method: "DELETE",
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
    }),
  listUsers: () => apiClient.get<{ items: UserAdmin[]; total: number }>("/api/v1/admin/users"),
  createUser: (request: CreateUserRequest) => apiClient.postJson<UserAdmin>("/api/v1/admin/users", request),
  updateUser: (userId: string, request: UpdateUserRequest) =>
    apiClient.putJson<UserAdmin>(`/api/v1/admin/users/${encodeURIComponent(userId)}`, request),
  deleteUser: (userId: string) => apiClient.delete<void>(`/api/v1/admin/users/${encodeURIComponent(userId)}`),
  addUserGroup: (userId: string, request: UserGroupRequest) =>
    apiClient.postJson<UserAdmin>(`/api/v1/admin/users/${encodeURIComponent(userId)}/groups`, request),
  removeUserGroup: (userId: string, request: UserGroupRequest) =>
    apiClient.request<UserAdmin>(`/api/v1/admin/users/${encodeURIComponent(userId)}/groups`, {
      method: "DELETE",
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
    }),
  getRagConfig: () => apiClient.get<RagConfig>("/api/v1/admin/rag-config"),
  listRerankerModels: () => apiClient.get<RerankerModelsResponse>("/api/v1/admin/rag-config/rerankers"),
  listRagModels: (request: RagModelDiscoveryRequest) =>
    apiClient.postJson<RagModelDiscoveryResult>("/api/v1/admin/rag-config/models", request),
  testRagConfig: (request: RagConfigRequest) =>
    apiClient.postJson<RagConfigTestResult>("/api/v1/admin/rag-config/test", request),
  updateRagConfig: (request: RagConfigRequest) =>
    apiClient.putJson<RagConfig>("/api/v1/admin/rag-config", request),
  getVllmDeploymentConfig: () => apiClient.get<VllmDeploymentConfig>("/api/v1/admin/vllm-deployment-config"),
  updateVllmDeploymentConfig: (request: VllmDeploymentConfigRequest) =>
    apiClient.putJson<VllmDeploymentConfig>("/api/v1/admin/vllm-deployment-config", request),
  applyVllmDeploymentConfig: (request: VllmDeploymentConfigRequest) =>
    apiClient.postJson<VllmDeploymentConfig>("/api/v1/admin/vllm-deployment-config/apply", request),
  getIngestConfig: () => apiClient.get<IngestConfig>("/api/v1/admin/ingest-config"),
  updateIngestConfig: (request: IngestConfigRequest) =>
    apiClient.putJson<IngestConfig>("/api/v1/admin/ingest-config", request),
};

export const reviewApi = {
  list: () => apiClient.get<{ items: ReviewItem[]; total: number }>("/api/v1/review-queue"),
  approve: (itemId: string, correctedText: string) =>
    apiClient.postJson<ReviewDecisionResponse>(`/api/v1/review-queue/${encodeURIComponent(itemId)}/approve`, {
      corrected_text: correctedText,
    }),
  reject: (itemId: string) =>
    apiClient.postJson<ReviewDecisionResponse>(`/api/v1/review-queue/${encodeURIComponent(itemId)}/reject`, null),
};

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
