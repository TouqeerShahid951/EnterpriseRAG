import type {
  AccountType,
  ClearanceLevel,
  Group,
  IngestConfig,
  IngestionQualityPreset,
  RagConfig,
  RagConfigTestResult,
  RagModelDiscoveryResult,
  RerankerModelsResponse,
  UserAdmin,
  VllmDeploymentConfig,
  VllmDeploymentService,
  VllmServiceDeploymentLimits,
} from "@/types/api";
import type { SavedChatSessionPage } from "@/types/chat";
import { apiClient } from "./apiClient";
import {
  normalizeChatSession,
  normalizeChatSessionSummary,
  type ChatSessionListRequest,
  type ChatSessionListResponse,
  type ChatSessionResponse,
} from "./query";

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

export interface VllmDeploymentConfigRequest {
  text: VllmServiceDeploymentLimits;
  embeddings: VllmServiceDeploymentLimits;
  vision: VllmServiceDeploymentLimits;
  services?: VllmDeploymentService[];
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

function adminUserChatActivityPath(userId: string, request: ChatSessionListRequest): string {
  const params = new URLSearchParams();
  if (request.limit !== undefined) params.set("limit", String(request.limit));
  if (request.offset !== undefined) params.set("offset", String(request.offset));
  const query = params.toString();
  const basePath = `/api/v1/admin/users/${encodeURIComponent(userId)}/chat-activity`;
  return query ? `${basePath}?${query}` : basePath;
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
