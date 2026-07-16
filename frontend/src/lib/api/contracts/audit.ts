import type { AuditEventListResponse } from "@/types/api";
import { apiClient } from "./apiClient";
import { setTrimmedParam } from "./requestParams";

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
