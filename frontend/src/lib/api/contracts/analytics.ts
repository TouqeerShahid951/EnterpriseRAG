import type { AnalyticsDiagnostics, AnalyticsExecution, AnalyticsExecutionListResponse, AnalyticsSeriesResponse, AnalyticsSummary } from "@/types/api";
import { apiClient } from "./apiClient";
import { setTrimmedParam } from "./requestParams";

export interface AnalyticsRequest {
  from?: string;
  to?: string;
  as_of?: string;
  origin?: string;
  work_kind?: string;
  user_id?: string;
  group_path?: string;
  outcome?: string;
  source_mode?: string;
  intent?: string;
  model_cohort?: string;
  configuration_digest?: string;
}

export interface AnalyticsListRequest extends AnalyticsRequest {
  limit?: number;
  offset?: number;
}

export const analyticsApi = {
  execution: (executionId: string) => apiClient.get<AnalyticsExecution>(`/api/v1/admin/query-analytics/executions/${encodeURIComponent(executionId)}`),
  summary: (request: AnalyticsRequest = {}) => apiClient.get<AnalyticsSummary>(analyticsPath("summary", request)),
  executions: (request: AnalyticsListRequest = {}) => apiClient.get<AnalyticsExecutionListResponse>(analyticsPath("executions", request)),
  series: (request: AnalyticsRequest = {}) => apiClient.get<AnalyticsSeriesResponse>(analyticsPath("series", request)),
  diagnostics: (request: AnalyticsRequest = {}) => apiClient.get<AnalyticsDiagnostics>(analyticsPath("diagnostics", request)),
};

function analyticsPath(resource: "summary" | "executions" | "series" | "diagnostics", request: AnalyticsListRequest): string {
  const params = new URLSearchParams();
  setTrimmedParam(params, "from", request.from);
  setTrimmedParam(params, "to", request.to);
  setTrimmedParam(params, "as_of", request.as_of);
  setTrimmedParam(params, "origin", request.origin);
  setTrimmedParam(params, "work_kind", request.work_kind);
  setTrimmedParam(params, "user_id", request.user_id);
  setTrimmedParam(params, "group_path", request.group_path);
  setTrimmedParam(params, "outcome", request.outcome);
  setTrimmedParam(params, "source_mode", request.source_mode);
  setTrimmedParam(params, "intent", request.intent);
  setTrimmedParam(params, "model_cohort", request.model_cohort);
  setTrimmedParam(params, "configuration_digest", request.configuration_digest);
  if (request.limit !== undefined) params.set("limit", String(request.limit));
  if (request.offset !== undefined) params.set("offset", String(request.offset));
  const query = params.toString();
  return query ? `/api/v1/admin/query-analytics/${resource}?${query}` : `/api/v1/admin/query-analytics/${resource}`;
}
