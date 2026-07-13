import { ApiClient } from "./client";
import { getConfiguredBaseUrl, normalizeBaseUrl } from "./url";
import type {
  Document,
  DeleteDocumentResponse,
  DocumentReingestRequest,
  DocumentGraphEnrichmentResponse,
  DocumentIngestStatus,
  DocumentReingestResponse,
  DocumentSharesResponse,
  AuditEventListResponse,
  ConnectorDeletionPolicy,
  ConnectorIngestionMode,
  ConnectorProfile,
  ConnectorSchemaCatalog,
  ConnectorSchemaCatalogStatus,
  ConnectorSchemaSnapshot,
  ConnectorTestResponse,
  ConnectorType,
  Group,
  GraphRAGCancelResponse,
  GraphRAGStatus,
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
  IngestionQualityPreset,
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
  QuerySource,
  RagConfig,
  IngestConfig,
  RagModelDiscoveryResult,
  RagConfigTestResult,
  RerankerModelsResponse,
  RagSseEvent,
  RAGResponse,
  ImageReviewDecisionResponse,
  ImageReviewQueueResponse,
  ReviewItem,
  ReviewDecisionResponse,
  RecurrenceWindow,
  SourceAnchor,
  UploadResponse,
  User,
  UserAdmin,
  VersionChainResponse,
  VllmDeploymentConfig,
  VllmDeploymentService,
  VllmServiceDeploymentLimits,
} from "@/types/api";
import type { ChatTurn, SavedChatSession, SavedChatSessionPage, SavedChatSessionSummary } from "@/types/chat";

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

export type AuditEventExportRequest = AuditEventListRequest & {
  max_rows?: number;
};

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

export interface CreateLocalFolderScheduleRequest {
  name: string;
  path: string;
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

interface LocalFolderDirectory {
  name: string;
  path: string;
  has_children: boolean;
}

export interface LocalFolderListResponse {
  root_path: string;
  current_path: string;
  parent_path?: string | null;
  items: LocalFolderDirectory[];
}

export interface CreateConnectorScheduleRequest {
  name: string;
  connector_profile_id: string;
  selection: Record<string, unknown>;
  identity_fields: string[];
  ingestion_mode: ConnectorIngestionMode;
  deletion_policy: ConnectorDeletionPolicy;
  batch_size: number;
  row_limit: number;
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

export interface CreateConnectorProfileRequest {
  name: string;
  connector_type: ConnectorType;
  public_config: Record<string, unknown>;
  secrets: Record<string, unknown>;
}

export interface UpdateConnectorProfileRequest {
  name?: string | null;
  public_config?: Record<string, unknown> | null;
  secrets?: Record<string, unknown> | null;
}

export interface CreateConnectorSchemaCatalogRequest {
  catalog_json?: Record<string, unknown> | null;
  status?: ConnectorSchemaCatalogStatus;
  group_path: string;
  group_paths?: string[];
  clearance_level?: ClearanceLevel;
}

export interface CreateConnectorSchemaCatalogAiDraftRequest {
  group_path: string;
  group_paths?: string[];
  clearance_level?: ClearanceLevel;
}

export interface EnrichConnectorSchemaCatalogTableRequest {
  table_key: string;
}

export interface UpdateConnectorSchemaCatalogRequest {
  catalog_json?: Record<string, unknown> | null;
  status?: ConnectorSchemaCatalogStatus | null;
  group_path?: string | null;
  group_paths?: string[] | null;
  clearance_level?: ClearanceLevel | null;
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

export interface UpdateDocumentTopicsRequest {
  topics: string[];
  llm_topics?: string[];
}

export interface UpdateDocumentSharesRequest {
  group_paths: string[];
}

export interface UpdateDocumentOwnerRequest {
  group_path: string;
}

export interface UnshareDocumentRequest {
  group_path: string;
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

export interface ResetUserPasswordRequest {
  temporary_password: string;
}

export interface UserGroupRequest {
  group_path: string;
}

export interface RagConfigRequest {
  provider?: "ollama" | "vllm";
  embedding_provider?: "ollama" | "openai_compatible" | "fastembed";
  reasoning_provider?: "ollama" | "vllm" | null;
  routing_provider?: "ollama" | "vllm" | null;
  faithfulness_provider?: "ollama" | "vllm" | null;
  ingestion_provider?: "ollama" | "vllm" | null;
  vision_provider?: "ollama" | "vllm" | null;
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
  vision_host?: string | null;
  vision_port?: number | null;
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
  query_planner_enabled: boolean;
  reranker_model: string;
  chat_timeout_seconds: number;
  embed_timeout_seconds: number;
}

export interface IngestConfigRequest {
  worker_concurrency: number;
  quality_preset: IngestionQualityPreset;
  ocr_review_confidence_threshold: number;
  pdf_image_review_threshold: number;
  vision_layout_repair_enabled: boolean;
  graph_enrichment_enabled: boolean;
}

export interface ImageReviewDecisionRequest {
  approve_candidate_ids?: string[];
  skip_candidate_ids?: string[];
  approve_recommended?: boolean;
  skip_remaining?: boolean;
}

export interface VllmDeploymentConfigRequest {
  text: VllmServiceDeploymentLimits;
  embeddings: VllmServiceDeploymentLimits;
  vision: VllmServiceDeploymentLimits;
  services?: VllmDeploymentService[];
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
  embedding_provider?: "ollama" | "openai_compatible" | "fastembed";
  reasoning_provider?: "ollama" | "vllm" | null;
  routing_provider?: "ollama" | "vllm" | null;
  faithfulness_provider?: "ollama" | "vllm" | null;
  ingestion_provider?: "ollama" | "vllm" | null;
  vision_provider?: "ollama" | "vllm" | null;
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
  vision_host?: string | null;
  vision_port?: number | null;
  timeout_seconds?: number;
}

export interface QuerySourceListRequest {
  group_path?: string | null;
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

const apiClient = new ApiClient();

export const authApi = {
  login: async (request: LoginRequest) => {
    const response = await apiClient.postJson<LoginResponse>("/api/v1/auth/login", request);
    return { ...response, user: normalizeUser(response.user) };
  },
  currentUser: async () => normalizeUser(await apiClient.get<User>("/api/v1/auth/me", { timeoutMs: 8000 })),
  refresh: async () => {
    const response = await apiClient.postJson<LoginResponse>("/api/v1/auth/refresh", null);
    return { ...response, user: normalizeUser(response.user) };
  },
  logout: () => apiClient.postJson<void>("/api/v1/auth/logout", null),
  changePassword: async (request: ChangePasswordRequest) => normalizeUser(await apiClient.postJson<User>("/api/v1/auth/change-password", request)),
};

function normalizeUser(user: User): User {
  const legacyUser = user as User & { id?: string };
  return {
    ...user,
    user_id: user.user_id ?? legacyUser.id ?? "",
    email: user.email ?? "",
    account_type: user.account_type ?? "member",
    group_paths: Array.isArray(user.group_paths) ? user.group_paths : [],
    clearance_level: user.clearance_level ?? "NATO_RESTRICTED",
    permission_version: user.permission_version ?? 0,
    must_change_password: Boolean(user.must_change_password),
  };
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

function localFolderListPath(path?: string | null): string {
  const params = new URLSearchParams();
  const trimmed = path?.trim();
  if (trimmed) {
    params.set("path", trimmed);
  }
  const query = params.toString();
  return `/api/v1/folder-ingest/local-folders${query ? `?${query}` : ""}`;
}

export const folderIngestApi = {
  listSchedules: () => apiClient.get<{ items: FolderSchedule[]; total: number }>("/api/v1/folder-ingest/schedules"),
  listLocalFolders: (path?: string | null) => apiClient.get<LocalFolderListResponse>(localFolderListPath(path)),
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
  createLocalFolder: (request: CreateLocalFolderScheduleRequest) =>
    apiClient.postJson<FolderSchedule>("/api/v1/folder-ingest/schedules/local-folder", request),
  createConnector: (request: CreateConnectorScheduleRequest) =>
    apiClient.postJson<FolderSchedule>("/api/v1/folder-ingest/schedules/connector", request),
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

export const connectorApi = {
  listProfiles: () => apiClient.get<{ items: ConnectorProfile[]; total: number }>("/api/v1/connectors/profiles"),
  createProfile: (request: CreateConnectorProfileRequest) =>
    apiClient.postJson<ConnectorProfile>("/api/v1/connectors/profiles", request),
  updateProfile: (profileId: string, request: UpdateConnectorProfileRequest) =>
    apiClient.putJson<ConnectorProfile>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}`, request),
  deleteProfile: (profileId: string) =>
    apiClient.delete<void>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}`),
  testProfile: (profileId: string) =>
    apiClient.postJson<ConnectorTestResponse>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}/test`, null),
  introspectProfile: (profileId: string) =>
    apiClient.postJson<ConnectorSchemaSnapshot>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}/introspect`, null),
  listSchemaCatalogs: async (profileId: string) => {
    const response = await apiClient.get<{ items: ConnectorSchemaCatalog[]; total: number }>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}/schema-catalogs`);
    return { ...response, items: response.items.map(normalizeConnectorSchemaCatalog) };
  },
  createSchemaCatalog: async (profileId: string, request: CreateConnectorSchemaCatalogRequest) =>
    normalizeConnectorSchemaCatalog(await apiClient.postJson<ConnectorSchemaCatalog>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}/schema-catalogs`, request)),
  createAiSchemaCatalogDraft: async (profileId: string, request: CreateConnectorSchemaCatalogAiDraftRequest) =>
    normalizeConnectorSchemaCatalog(await apiClient.postJson<ConnectorSchemaCatalog>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}/schema-catalogs/ai-draft`, request)),
  enrichSchemaCatalogTable: (profileId: string, catalogId: string, request: EnrichConnectorSchemaCatalogTableRequest) =>
    apiClient.postJson<ConnectorSchemaCatalog>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}/schema-catalogs/${encodeURIComponent(catalogId)}/ai-enrich-table`, request).then(normalizeConnectorSchemaCatalog),
  updateSchemaCatalog: (profileId: string, catalogId: string, request: UpdateConnectorSchemaCatalogRequest) =>
    apiClient.putJson<ConnectorSchemaCatalog>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}/schema-catalogs/${encodeURIComponent(catalogId)}`, request).then(normalizeConnectorSchemaCatalog),
};

export const queryApi = {
  ask: (request: QueryRequest) => apiClient.postJson<RAGResponse>("/api/v1/query", request),
  stream: (request: QueryRequest, init?: RequestInit) => apiClient.postJsonSse<RagSseEvent>("/api/v1/query/stream", request, init),
  sources: (request: QuerySourceListRequest = {}) =>
    apiClient.get<{ items: QuerySource[]; total: number }>(querySourceListPath(request)),
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

function querySourceListPath(request: QuerySourceListRequest): string {
  const params = new URLSearchParams();
  setTrimmedParam(params, "group_path", request.group_path ?? undefined);
  const query = params.toString();
  return query ? `/api/v1/query/sources?${query}` : "/api/v1/query/sources";
}

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
  shares: (documentId: string) =>
    apiClient.get<DocumentSharesResponse>(`/api/v1/docs/${encodeURIComponent(documentId)}/shares`),
  updateShares: (documentId: string, request: UpdateDocumentSharesRequest) =>
    apiClient.request<DocumentSharesResponse>(`/api/v1/docs/${encodeURIComponent(documentId)}/shares`, {
      method: "PUT",
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
    }),
  transferOwnership: async (documentId: string, request: UpdateDocumentOwnerRequest) =>
    normalizeDocument(await apiClient.request<Document>(`/api/v1/docs/${encodeURIComponent(documentId)}/owner`, {
      method: "PATCH",
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
    })),
  unshare: (documentId: string, request: UnshareDocumentRequest) =>
    apiClient.postJson<DocumentSharesResponse>(`/api/v1/docs/${encodeURIComponent(documentId)}/shares/unshare`, request),
  remove: (documentId: string) =>
    apiClient.delete<DeleteDocumentResponse>(`/api/v1/docs/${encodeURIComponent(documentId)}`),
  permanentlyRemove: (documentId: string) =>
    apiClient.delete<DeleteDocumentResponse>(`/api/v1/docs/${encodeURIComponent(documentId)}/permanent`),
  reingest: (documentId: string, request: DocumentReingestRequest | null = null) =>
    apiClient.postJson<DocumentReingestResponse>(`/api/v1/docs/${encodeURIComponent(documentId)}/reingest`, request),
  enrichGraph: (documentId: string) =>
    apiClient.postJson<DocumentGraphEnrichmentResponse>(`/api/v1/docs/${encodeURIComponent(documentId)}/graph-enrichment`, null),
  restore: (documentId: string) =>
    apiClient.postJson<DocumentReingestResponse>(`/api/v1/docs/${encodeURIComponent(documentId)}/restore`, null),
  updateClearance: async (documentId: string, request: UpdateDocumentClearanceRequest) =>
    normalizeDocument(await apiClient.request<Document>(`/api/v1/docs/${encodeURIComponent(documentId)}/clearance`, {
      method: "PATCH",
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
    })),
  updateTopics: async (documentId: string, request: UpdateDocumentTopicsRequest) =>
    normalizeDocument(await apiClient.patchJson<Document>(`/api/v1/docs/${encodeURIComponent(documentId)}/topics`, request)),
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

function adminUserChatActivityPath(userId: string, request: ChatSessionListRequest): string {
  const params = new URLSearchParams();
  if (request.limit !== undefined) params.set("limit", String(request.limit));
  if (request.offset !== undefined) params.set("offset", String(request.offset));
  const query = params.toString();
  const basePath = `/api/v1/admin/users/${encodeURIComponent(userId)}/chat-activity`;
  return query ? `${basePath}?${query}` : basePath;
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
  if (request.uploaded_by_me) params.set("uploaded_by_me", "true");
  if (request.limit !== undefined) params.set("limit", String(request.limit));
  if (request.offset !== undefined) params.set("offset", String(request.offset));
  const query = params.toString();
  return query ? `${basePath}?${query}` : basePath;
}

function normalizeDocument(document: Document): Document {
  const status = DOCUMENT_INGEST_STATUSES.includes(document.ingest_status) ? document.ingest_status : "unknown";
  const ownerGroupPath = document.owner_group_path || document.group_path;
  const sharedGroupPaths = Array.isArray(document.shared_group_paths) ? document.shared_group_paths : [];
  const accessGroupPaths = Array.isArray(document.access_group_paths) && document.access_group_paths.length
    ? document.access_group_paths
    : [ownerGroupPath, ...sharedGroupPaths].filter(Boolean);
  return {
    ...document,
    owner_group_path: ownerGroupPath,
    shared_group_paths: sharedGroupPaths,
    access_group_paths: accessGroupPaths,
    governance_owner: document.governance_owner ?? (sharedGroupPaths.length ? "system" : "space"),
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

function normalizeConnectorSchemaCatalog(catalog: ConnectorSchemaCatalog): ConnectorSchemaCatalog {
  const ownerGroupPath = catalog.owner_group_path || catalog.group_path;
  const jsonShared = Array.isArray(catalog.catalog_json?.shared_group_paths)
    ? catalog.catalog_json.shared_group_paths.filter((value): value is string => typeof value === "string")
    : [];
  const sharedGroupPaths = Array.isArray(catalog.shared_group_paths) ? catalog.shared_group_paths : jsonShared;
  const accessGroupPaths = Array.isArray(catalog.access_group_paths) && catalog.access_group_paths.length
    ? catalog.access_group_paths
    : [ownerGroupPath, ...sharedGroupPaths].filter(Boolean);
  return {
    ...catalog,
    owner_group_path: ownerGroupPath,
    shared_group_paths: sharedGroupPaths,
    access_group_paths: accessGroupPaths,
  };
}

export const auditApi = {
  list: (request: AuditEventListRequest = {}) => apiClient.get<AuditEventListResponse>(auditListPath(request)),
  exportCsv: async (request: AuditEventExportRequest = {}) => {
    const response = await apiClient.fetchRaw(auditExportPath(request));
    if (!response.ok) throw new Error("Unable to export audit logs.");
    return response.blob();
  },
};

function auditListPath(request: AuditEventListRequest): string {
  const params = new URLSearchParams();
  setAuditFilterParams(params, request);
  if (request.limit !== undefined) params.set("limit", String(request.limit));
  if (request.offset !== undefined) params.set("offset", String(request.offset));
  const query = params.toString();
  return query ? `/api/v1/audit-log?${query}` : "/api/v1/audit-log";
}

function auditExportPath(request: AuditEventExportRequest): string {
  const params = new URLSearchParams();
  setAuditFilterParams(params, request);
  if (request.max_rows !== undefined) params.set("max_rows", String(request.max_rows));
  const query = params.toString();
  return query ? `/api/v1/audit-log/export?${query}` : "/api/v1/audit-log/export";
}

function setAuditFilterParams(params: URLSearchParams, request: AuditEventExportRequest) {
  setTrimmedParam(params, "search", request.search);
  setTrimmedParam(params, "category", request.category);
  setTrimmedParam(params, "event_type", request.event_type);
  setTrimmedParam(params, "actor_id", request.actor_id);
  setTrimmedParam(params, "target_type", request.target_type);
  setTrimmedParam(params, "target_id", request.target_id);
  setTrimmedParam(params, "group_path", request.group_path);
  if (request.created_from) params.set("created_from", request.created_from);
  if (request.created_to) params.set("created_to", request.created_to);
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
  listUserChatActivity: async (userId: string, request: ChatSessionListRequest = {}): Promise<SavedChatSessionPage> => {
    const response = await apiClient.get<ChatSessionListResponse>(adminUserChatActivityPath(userId, request));
    return {
      ...response,
      limit: response.limit ?? request.limit ?? response.items.length,
      offset: response.offset ?? request.offset ?? 0,
      items: response.items.map(normalizeChatSessionSummary),
    };
  },
  getUserChatActivitySession: async (userId: string, sessionId: string) =>
    normalizeChatSession(await apiClient.get<ChatSessionResponse>(`/api/v1/admin/users/${encodeURIComponent(userId)}/chat-activity/${encodeURIComponent(sessionId)}`)),
  createUser: (request: CreateUserRequest) => apiClient.postJson<UserAdmin>("/api/v1/admin/users", request),
  updateUser: (userId: string, request: UpdateUserRequest) =>
    apiClient.putJson<UserAdmin>(`/api/v1/admin/users/${encodeURIComponent(userId)}`, request),
  resetUserPassword: (userId: string, request: ResetUserPasswordRequest) =>
    apiClient.postJson<UserAdmin>(`/api/v1/admin/users/${encodeURIComponent(userId)}/reset-password`, request),
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
  resetRagConfig: () => apiClient.delete<RagConfig>("/api/v1/admin/rag-config"),
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
  listImageBatches: () => apiClient.get<ImageReviewQueueResponse>("/api/v1/review-queue/image-batches"),
  decideImageBatch: (batchId: string, request: ImageReviewDecisionRequest) =>
    apiClient.postJson<ImageReviewDecisionResponse>(`/api/v1/review-queue/image-batches/${encodeURIComponent(batchId)}/decisions`, request),
  imageCandidateContentUrl: (contentUrl: string) =>
    contentUrl.startsWith("http")
      ? contentUrl
      : `${normalizeBaseUrl(getConfiguredBaseUrl())}${contentUrl.startsWith("/") ? contentUrl : `/${contentUrl}`}`,
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
