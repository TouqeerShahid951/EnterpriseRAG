import type {
  ClearanceLevel,
  DeleteDocumentResponse,
  Document,
  DocumentCatalogSummary,
  DocumentGraphEnrichmentResponse,
  DocumentIngestStatus,
  DocumentReingestRequest,
  DocumentReingestResponse,
  DocumentSharesResponse,
  SourceAnchor,
  VersionChainResponse,
} from "@/types/api";
import { getConfiguredBaseUrl, normalizeBaseUrl } from "../url";
import { apiClient } from "./apiClient";

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

export const documentsApi = {
  list: async (request: DocumentListRequest = {}) => {
    const response = await apiClient.get<{ items: Document[]; total: number }>(documentListPath(request));
    return { ...response, items: response.items.map(normalizeDocument) };
  },
  summary: () => apiClient.get<DocumentCatalogSummary>("/api/v1/docs/summary"),
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

const DOCUMENT_INGEST_STATUSES: DocumentIngestStatus[] = ["scheduled", "queued", "processing", "complete", "failed", "human_review", "cancelled", "unknown"];

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
