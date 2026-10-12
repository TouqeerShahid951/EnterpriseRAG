import type { ReactNode } from "react";
import { Activity, CheckCircle2, Clock3, RefreshCw, ShieldAlert, TriangleAlert, Users } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { InlineMessage, Skeleton } from "@/components/layout/Common";
import { PrudentiaBasicPage } from "@/components/layout/PrudentiaWorkspace";
import { analyticsApi } from "@/lib/api/contracts";
import { errorMessage } from "@/lib/utils/format";
import type { AnalyticsSeriesBucket, AnalyticsSummary, User as AuthUser } from "@/types/api";
import type { RouteId } from "@/routes/routes";
import { AnalyticsChartPanel as ChartPanel, AnalyticsPeriodOutcomeFilters } from "../components/AnalyticsChartPanel";
import { AnalyticsLineChart, AnalyticsOutcomeChart } from "../components/AnalyticsCharts";
import { AnswerQualityDiagnostics, PerformanceDiagnostics, RetrievalDiagnostics } from "../components/AnalyticsDiagnostics";
import { ANALYTICS_PAGE_SIZE, analyticsRequests } from "../state/analyticsPageState";
import { useAnalyticsPageState } from "../state/useAnalyticsPageState";
import { ExecutionInspector } from "../components/ExecutionInspector";
import { executionStatus } from "../utils/executionStatus";

export function PrudentiaAnalyticsPage({ onLogout, onNavigate, user }: Props) {
  const { state, change, refresh } = useAnalyticsPageState();
  const { days, groupPath, sourceMode, modelCohort, configurationDigest, outcome, selectedExecutionId, tab, drilldown, offset, origin, workKind } = state;
  const { seriesRequest, listRequest } = analyticsRequests(state);
  const cacheScope = ["query-analytics", user.user_id, user.permission_version];
  const queryOptions = { retry: false, staleTime: 30000, refetchOnWindowFocus: false } as const;
  const summaryQuery = useQuery({
    ...queryOptions,
    queryKey: [...cacheScope, "summary", seriesRequest],
    queryFn: () => analyticsApi.summary(seriesRequest),
    enabled: tab === "overview",
  });
  const seriesQuery = useQuery({
    ...queryOptions,
    queryKey: [...cacheScope, "series", seriesRequest],
    queryFn: () => analyticsApi.series(seriesRequest),
    enabled: tab === "overview" || tab === "quality",
  });
  const executionsQuery = useQuery({
    ...queryOptions,
    queryKey: [...cacheScope, "executions", listRequest],
    queryFn: () => analyticsApi.executions(listRequest),
    enabled: tab === "queries",
  });
  const diagnosticsQuery = useQuery({
    ...queryOptions,
    queryKey: [...cacheScope, "diagnostics", seriesRequest],
    queryFn: () => analyticsApi.diagnostics(seriesRequest),
    enabled: tab === "retrieval" || tab === "performance" || tab === "quality",
  });
  const detailQuery = useQuery({
    ...queryOptions,
    queryKey: [...cacheScope, "execution", selectedExecutionId, state.asOf],
    queryFn: () => analyticsApi.execution(selectedExecutionId),
    enabled: tab === "queries" && Boolean(selectedExecutionId),
  });
  const chartFilters = { days, outcome, onChange: change };
  const summary = summaryQuery.data;
  const executions = executionsQuery.data?.items ?? [];
  const total = executionsQuery.data?.total ?? 0;

  function selectBucket(bucket: AnalyticsSeriesBucket) {
    change({ drilldown: { from: bucket.started_at, to: bucket.ended_at }, selectedExecutionId: "", offset: 0, tab: "queries" });
  }

  return (
    <PrudentiaBasicPage
      activeRoute="operational-analytics"
      onLogout={onLogout}
      onNavigate={onNavigate}
      title="Analytics"
      subtitle="Operational visibility into production query activity, outcomes, latency, and verification coverage."
      user={user}
    >
      <div className="analytics-dashboard">
        <div className="analytics-toolbar">
          <div>
            <p className="analytics-scope"><Activity size={15} aria-hidden="true" /> Platform Admin · selected query population · UTC</p>
            <p className="analytics-caption">Automated signals describe system behavior; they do not measure absolute answer accuracy.</p>
          </div>
          <div className="analytics-toolbar-actions">
            <label htmlFor="analytics-origin">Origin</label>
            <select id="analytics-origin" className="sv-action-secondary" value={origin} onChange={(event) => change({ origin: event.target.value })}>
              <option value="chat">Production chat</option><option value="query_tracker">Query tracker</option><option value="evaluation">Evaluation</option><option value="other_internal">Other internal</option><option value="all">All origins</option>
            </select>
            <label htmlFor="analytics-work-kind">Work kind</label>
            <select id="analytics-work-kind" className="sv-action-secondary" value={workKind} onChange={(event) => change({ workKind: event.target.value })}>
              <option value="answer">Answers</option><option value="artifact_submission">Artifact submissions</option><option value="all">All work</option>
            </select>
            <label htmlFor="analytics-group-path">Knowledge Space</label>
            <input id="analytics-group-path" className="analytics-filter-input" value={groupPath} onChange={(event) => change({ groupPath: event.target.value })} placeholder="All spaces" />
            <label htmlFor="analytics-source-mode">Route</label>
            <select id="analytics-source-mode" className="sv-action-secondary" value={sourceMode} onChange={(event) => change({ sourceMode: event.target.value })}>
              <option value="">All routes</option>
              <option value="auto">Auto</option>
              <option value="corpus_only">Corpus only</option>
              <option value="db_only">Database only</option>
              <option value="hybrid">Hybrid</option>
            </select>
            <label htmlFor="analytics-model-cohort">Model cohort</label>
            <input id="analytics-model-cohort" className="analytics-filter-input" value={modelCohort} onChange={(event) => change({ modelCohort: event.target.value })} placeholder="All cohorts" />
            <label htmlFor="analytics-configuration">Configuration</label>
            <input id="analytics-configuration" className="analytics-filter-input" value={configurationDigest} onChange={(event) => change({ configurationDigest: event.target.value })} placeholder="All configs" />
            <AnalyticsPeriodOutcomeFilters prefix="analytics" {...chartFilters} />
            <button type="button" className="sv-action-secondary" onClick={refresh} disabled={summaryQuery.isFetching || seriesQuery.isFetching || executionsQuery.isFetching || diagnosticsQuery.isFetching}>
              <RefreshCw size={14} aria-hidden="true" /> Refresh
            </button>
          </div>
        </div>

        {summaryQuery.isError ? <InlineMessage tone="error">{errorMessage(summaryQuery.error, "Unable to load analytics summary.")}</InlineMessage> : null}
        {seriesQuery.isError ? <InlineMessage tone="warning">{errorMessage(seriesQuery.error, "Unable to load analytics trends.")}</InlineMessage> : null}
        {executionsQuery.isError ? <InlineMessage tone="warning">{errorMessage(executionsQuery.error, "Unable to load recent executions.")}</InlineMessage> : null}
        {diagnosticsQuery.isError ? <InlineMessage tone="warning">{errorMessage(diagnosticsQuery.error, "Unable to load retrieval and performance diagnostics.")}</InlineMessage> : null}

        <nav className="analytics-tabs" aria-label="Analytics views">
          {(["overview", "queries", "retrieval", "performance", "quality"] as const).map((item) => <button key={item} type="button" className="analytics-tab" aria-current={tab === item ? "page" : undefined} onClick={() => change({ tab: item, selectedExecutionId: "" })}>{item[0].toUpperCase() + item.slice(1)}</button>)}
        </nav>

        {tab === "overview" ? <>
        {summaryQuery.isLoading ? <div className="analytics-metrics" aria-busy="true"><Skeleton className="h-28" /><Skeleton className="h-28" /><Skeleton className="h-28" /><Skeleton className="h-28" /><Skeleton className="h-28" /><Skeleton className="h-28" /></div> : null}
        {summary ? <div className="analytics-metrics" aria-label="Analytics summary">
          <Metric icon={<Activity size={18} />} label="Queries" value={summary.total_executions.toLocaleString()} detail={`${summary.unique_actor_count.toLocaleString()} unique actors`} />
          <Metric icon={<CheckCircle2 size={18} />} label="Complete answer rate" value={formatRate(summary.complete_rate.value)} detail={`${summary.complete_rate.numerator} of ${summary.complete_rate.denominator} answer executions`} />
          <Metric icon={<TriangleAlert size={18} />} label="Abstention rate" value={formatRate(summary.abstention_rate.value)} detail={`${summary.abstained.toLocaleString()} abstained`} tone="warning" />
          <Metric icon={<ShieldAlert size={18} />} label="System error rate" value={formatRate(summary.system_error_rate.value)} detail={`${summary.system_error.toLocaleString()} system errors`} tone="warning" />
          <Metric icon={<Clock3 size={18} />} label="P95 server latency" value={formatLatency(summary.p95_latency_ms)} detail={`P50 ${formatLatency(summary.p50_latency_ms)}`} />
          <Metric icon={<CheckCircle2 size={18} />} label="Verification coverage" value={formatRate(summary.verification_coverage.value)} detail={`${summary.verification_checked} checked of ${summary.verification_applicable} applicable`} />
        </div> : null}

        <section className="analytics-chart-grid" aria-label="Analytics trends">
          <ChartPanel filters={chartFilters} title="Query volume" subtitle="Captured executions by UTC bucket · select a bucket to filter the table">
            {seriesQuery.isLoading ? <Skeleton className="h-48" /> : seriesQuery.data && hasSeriesData(seriesQuery.data.buckets) ? <AnalyticsLineChart buckets={seriesQuery.data.buckets} metrics={[{ key: "total_executions", label: "Executions", tone: "accent", unit: "count" }]} onBucketSelect={selectBucket} /> : <ChartEmpty error={seriesQuery.isError} />}
          </ChartPanel>
          <ChartPanel filters={chartFilters} title="Outcome distribution" subtitle="Terminal outcomes grouped by UTC bucket">
            {seriesQuery.isLoading ? <Skeleton className="h-48" /> : seriesQuery.data && hasSeriesData(seriesQuery.data.buckets) ? <AnalyticsOutcomeChart buckets={seriesQuery.data.buckets} onBucketSelect={selectBucket} /> : <ChartEmpty error={seriesQuery.isError} />}
          </ChartPanel>
          <ChartPanel filters={chartFilters} title="Answer latency" subtitle="P50 and P95 completed answer latency">
            {seriesQuery.isLoading ? <Skeleton className="h-48" /> : seriesQuery.data && hasLatencyData(seriesQuery.data.buckets) ? <AnalyticsLineChart buckets={seriesQuery.data.buckets} metrics={[{ key: "p50_latency_ms", label: "P50", tone: "secondary", unit: "ms" }, { key: "p95_latency_ms", label: "P95", tone: "warning", unit: "ms" }]} onBucketSelect={selectBucket} /> : <ChartEmpty error={seriesQuery.isError} />}
          </ChartPanel>
        </section>

        {summary ? <section className="sv-panel analytics-panel" aria-labelledby="outcomes-title">
          <header className="analytics-panel-heading"><div><h2 id="outcomes-title">Query outcomes</h2><p>Terminal execution distribution for the selected period</p></div><Users size={18} aria-hidden="true" /></header>
          <div className="analytics-outcomes">
            {outcomes(summary).map((item) => <div className="analytics-outcome" key={item.label}>
              <div><span>{item.label}</span><strong>{item.value.toLocaleString()}</strong></div>
              <div className="analytics-bar" aria-label={`${item.label}: ${item.value}`}><span data-tone={item.tone} style={{ width: `${percentage(item.value, summary.terminal_executions)}%` }} /></div>
            </div>)}
          </div>
          <p className="analytics-footnote">Terminal executions: {summary.terminal_executions.toLocaleString()} · Answer denominator: {summary.answer_executions.toLocaleString()} · In flight: {summary.in_flight_executions.toLocaleString()} · Verification coverage: {formatRate(summary.verification_coverage.value)}</p>
        </section> : null}
        </> : null}

        {tab === "queries" ? <section className="sv-panel analytics-panel" aria-labelledby="executions-title">
          <header className="analytics-panel-heading"><div><h2 id="executions-title">Recent executions</h2><p>Metadata retained for the selected period{drilldown ? " and selected chart bucket" : ""} · newest first</p></div>{drilldown ? <button type="button" className="sv-action-secondary" onClick={() => change({ drilldown: null, offset: 0, selectedExecutionId: "" })}>Clear bucket</button> : null}</header>
          {executionsQuery.isLoading ? <Skeleton className="h-48" aria-label="Loading recent executions" /> : null}
          {!executionsQuery.isLoading && executions.length === 0 ? <p className="analytics-empty" role="status">{executionsQuery.isError ? "Recent executions are unavailable." : "No captured executions in this period."}</p> : null}
          {executions.length ? <div className="analytics-table-wrap"><table className="analytics-table"><caption className="sr-only">Recent query execution metadata</caption><thead><tr><th scope="col">Started</th><th scope="col">Outcome</th><th scope="col">Route</th><th scope="col">Latency</th><th scope="col">Review signals</th><th scope="col">Verification</th><th scope="col"><span className="sr-only">Inspect</span></th></tr></thead><tbody>{executions.map((execution) => <tr key={execution.execution_id}><td><time dateTime={execution.started_at}>{formatDate(execution.started_at)}</time><small>{execution.execution_id.slice(0, 8)}</small></td><td><span className="analytics-status" data-tone={outcomeTone(execution.outcome)}>{executionStatus(execution)}</span></td><td>{execution.resolved_source_mode ?? execution.requested_source_mode ?? "Unknown"}<small>{execution.final_intent ?? "Intent unavailable"}</small></td><td>{formatLatency(execution.latency_ms)}</td><td>{execution.review_reasons.length ? <span className="analytics-review-reasons" title={execution.review_reasons.map(reviewReasonLabel).join(", ")}>{execution.review_reasons.map(reviewReasonLabel).join(", ")}</span> : "None"}</td><td>{execution.verification_status ?? "Not measured"}</td><td><button type="button" className="sv-action-secondary analytics-inspect" onClick={() => change({ selectedExecutionId: execution.execution_id })}>Inspect</button></td></tr>)}</tbody></table></div> : null}
          <nav className="analytics-pagination" aria-label="Execution pages">
            <button type="button" className="sv-action-secondary" disabled={offset === 0 || executionsQuery.isFetching} onClick={() => change({ offset: Math.max(0, offset - ANALYTICS_PAGE_SIZE), selectedExecutionId: "" })}>Previous</button>
            <span role="status">{total ? `${offset + 1}–${Math.min(offset + ANALYTICS_PAGE_SIZE, total)} of ${total}` : "0 executions"}</span>
            <button type="button" className="sv-action-secondary" disabled={offset + ANALYTICS_PAGE_SIZE >= total || executionsQuery.isFetching} onClick={() => change({ offset: offset + ANALYTICS_PAGE_SIZE, selectedExecutionId: "" })}>Next</button>
          </nav>
          <p className="analytics-footnote">Snapshot: <time dateTime={state.asOf}>{formatDate(state.asOf)}</time> UTC. Refresh to include newer executions.</p>
        </section> : null}

        {tab === "retrieval" ? <RetrievalDiagnostics diagnostics={diagnosticsQuery.data} /> : null}
        {tab === "performance" ? <PerformanceDiagnostics diagnostics={diagnosticsQuery.data} /> : null}
        {tab === "quality" ? <>
          <section className="analytics-chart-grid" aria-label="Qualified faithfulness trend">
            <ChartPanel filters={chartFilters} title="Qualified faithfulness trend" subtitle="Mean checked score by UTC bucket · unavailable buckets have no checked scores">
              {seriesQuery.isLoading ? <Skeleton className="h-48" /> : seriesQuery.data && hasFaithfulnessData(seriesQuery.data.buckets) ? <AnalyticsLineChart buckets={seriesQuery.data.buckets} metrics={[{ key: "faithfulness_score_mean", label: "Checked score mean", tone: "accent", unit: "0–1 score" }]} onBucketSelect={selectBucket} /> : <ChartEmpty error={seriesQuery.isError} />}
            </ChartPanel>
          </section>
          <AnswerQualityDiagnostics diagnostics={diagnosticsQuery.data} />
        </> : null}

        {tab === "queries" && selectedExecutionId ? <ExecutionInspector execution={detailQuery.data} loading={detailQuery.isLoading} error={detailQuery.error} onRetry={() => { void detailQuery.refetch(); }} onClose={() => change({ selectedExecutionId: "" })} /> : null}
      </div>
    </PrudentiaBasicPage>
  );
}

function Metric({ detail, icon, label, tone = "accent", value }: { detail: string; icon: ReactNode; label: string; tone?: string; value: string }) {
  return <div className="sv-panel analytics-metric"><span className="analytics-metric-icon" data-tone={tone}>{icon}</span><p>{label}</p><strong>{value}</strong><small>{detail}</small></div>;
}

function ChartEmpty({ error }: { error: boolean }) {
  return <p className="analytics-empty" role="status">{error ? "Could not refresh this trend." : "No recorded queries in this period."}</p>;
}

function outcomes(summary: AnalyticsSummary) {
  return [
    { label: "Complete", value: summary.complete, tone: "success" },
    { label: "Partial", value: summary.partial, tone: "warning" },
    { label: "Clarification", value: summary.clarification, tone: "muted" },
    { label: "Abstained", value: summary.abstained, tone: "warning" },
    { label: "System error", value: summary.system_error, tone: "danger" },
    { label: "Access denied", value: summary.access_denied, tone: "danger" },
    { label: "Cancelled", value: summary.cancelled, tone: "muted" },
    { label: "Interrupted", value: summary.interrupted, tone: "muted" },
    { label: "Artifact submitted", value: summary.artifact_submitted, tone: "muted" },
  ];
}

function formatRate(value: number | null) { return value === null ? "Not measured" : `${(value * 100).toFixed(1)}%`; }
function formatLatency(value: number | null) { return value === null ? "Not measured" : `${Math.round(value)} ms`; }
function formatDate(value: string) { const date = new Date(value); return `${date.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" })} ${date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", timeZone: "UTC" })}`; }
function percentage(value: number, total: number) { return total ? Math.max(0, Math.min(100, value / total * 100)) : 0; }
function outcomeTone(outcome: string | null) { return outcome === "complete" ? "success" : outcome === "system_error" || outcome === "access_denied" ? "danger" : "warning"; }
function hasSeriesData(buckets: AnalyticsSeriesBucket[]) { return buckets.some((bucket) => bucket.total_executions > 0); }
function hasLatencyData(buckets: AnalyticsSeriesBucket[]) { return buckets.some((bucket) => bucket.p50_latency_ms !== null || bucket.p95_latency_ms !== null); }
function hasFaithfulnessData(buckets: AnalyticsSeriesBucket[]) { return buckets.some((bucket) => bucket.faithfulness_score_mean !== null); }
function reviewReasonLabel(reason: string) { return reason.replace(/_/g, " "); }

type Props = { onLogout: () => void; onNavigate: (route: RouteId) => void; user: AuthUser };
