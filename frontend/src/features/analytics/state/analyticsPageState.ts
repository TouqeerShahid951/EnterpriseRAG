import type { AnalyticsRequest } from "@/lib/api/contracts/analytics";

const TABS = ["overview", "queries", "retrieval", "performance", "quality"] as const;
export type AnalyticsTab = (typeof TABS)[number];
export type AnalyticsState = {
  days: number;
  asOf: string;
  groupPath: string;
  sourceMode: string;
  modelCohort: string;
  configurationDigest: string;
  origin: string;
  workKind: string;
  outcome: string;
  selectedExecutionId: string;
  offset: number;
  tab: AnalyticsTab;
  drilldown: { from: string; to: string } | null;
};

export const ANALYTICS_PAGE_SIZE = 50;

export function readAnalyticsState(search: string, now = new Date()): AnalyticsState {
  const params = new URLSearchParams(search);
  const value = (name: string) => params.get(`analytics_${name}`)?.trim() ?? "";
  const days = Number(value("days"));
  const offset = Number(value("offset"));
  const tab = value("tab");
  const selectedExecutionId = value("execution");
  const asOf = validDate(value("as_of"));
  const from = validDate(value("bucket_from"));
  const to = validDate(value("bucket_to"));
  return {
    days: [1, 7, 30].includes(days) ? days : 7,
    asOf: asOf && asOf <= now.toISOString() ? asOf : now.toISOString(),
    groupPath: value("space"), sourceMode: value("route"),
    modelCohort: value("model_cohort"), configurationDigest: value("configuration"),
    origin: ["chat", "query_tracker", "evaluation", "other_internal", "all"].includes(value("origin")) ? value("origin") : "chat",
    workKind: ["answer", "artifact_submission", "all"].includes(value("work_kind")) ? value("work_kind") : "answer",
    outcome: value("outcome"), selectedExecutionId,
    offset: Number.isSafeInteger(offset) && offset >= 0 ? offset : 0,
    tab: selectedExecutionId ? "queries" : TABS.includes(tab as AnalyticsTab) ? tab as AnalyticsTab : "overview",
    drilldown: from && to && from < to && Date.parse(to) - Date.parse(from) <= 30 * 86400000 ? { from, to } : null,
  };
}

export function changeAnalyticsState(state: AnalyticsState, patch: Partial<AnalyticsState>): AnalyticsState {
  const filters = ["days", "groupPath", "sourceMode", "modelCohort", "configurationDigest", "origin", "workKind", "outcome"] as const;
  const changedFilter = filters.some((key) => key in patch && patch[key] !== state[key]);
  return { ...state, ...(changedFilter ? { offset: 0, drilldown: null, selectedExecutionId: "" } : {}), ...patch };
}

export function analyticsRequests(state: AnalyticsState) {
  const seriesRequest: AnalyticsRequest = {
    from: new Date(Date.parse(state.asOf) - state.days * 86400000).toISOString(),
    to: state.asOf, as_of: state.asOf,
    group_path: state.groupPath.trim() || undefined, source_mode: state.sourceMode || undefined,
    model_cohort: state.modelCohort.trim() || undefined, configuration_digest: state.configurationDigest.trim() || undefined,
    outcome: state.outcome || undefined, origin: state.origin, work_kind: state.workKind,
  };
  return { seriesRequest, listRequest: { ...seriesRequest, ...state.drilldown, limit: ANALYTICS_PAGE_SIZE, offset: state.offset } };
}

export function analyticsUrl(url: URL, state: AnalyticsState): string {
  const values = {
    days: String(state.days), as_of: state.asOf, space: state.groupPath, route: state.sourceMode,
    model_cohort: state.modelCohort, configuration: state.configurationDigest,
    origin: state.origin, work_kind: state.workKind, outcome: state.outcome,
    execution: state.selectedExecutionId, offset: String(state.offset), tab: state.tab,
    bucket_from: state.drilldown?.from ?? "", bucket_to: state.drilldown?.to ?? "",
  };
  for (const [name, value] of Object.entries(values)) {
    if (value) url.searchParams.set(`analytics_${name}`, value);
    else url.searchParams.delete(`analytics_${name}`);
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

function validDate(value: string): string | null {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : null;
}
