import type {
  ArtifactJobDetail,
  ArtifactJobSummary,
  GeneratedArtifact,
  QueryRequest,
  QuerySource,
  RAGResponse,
  RagSseEvent,
} from "@/types/api";
import type { ChatTurn, SavedChatSession, SavedChatSessionPage, SavedChatSessionSummary } from "@/types/chat";
import { getConfiguredBaseUrl, normalizeBaseUrl } from "../url";
import { apiClient } from "./apiClient";
import { setTrimmedParam } from "./requestParams";

export interface QuerySourceListRequest {
  group_path?: string | null;
}

export interface ChatSessionResponse {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  turns: unknown[];
}

export interface ChatSessionSummaryResponse {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  question_count?: number;
  turns?: unknown[];
}

export interface ChatSessionListResponse {
  items: ChatSessionSummaryResponse[];
  total: number;
  limit?: number;
  offset?: number;
}

export interface ChatSessionListRequest {
  limit?: number;
  offset?: number;
}

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

export function normalizeChatSession(session: ChatSessionResponse): SavedChatSession {
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

export function normalizeChatSessionSummary(session: ChatSessionSummaryResponse): SavedChatSessionSummary {
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
