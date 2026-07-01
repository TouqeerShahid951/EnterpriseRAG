import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertTriangle, Database, FileClock, Loader2, Network, RotateCcw, ServerCog, ShieldAlert } from "lucide-react";

import { adminApi, folderIngestApi, ingestJobsApi } from "../api/contracts";
import { canManageSpaces, isGlobalAdmin, isPlatformAdmin } from "../authz";
import { useToast } from "../components/feedback/ToastProvider";
import { InlineMessage, Skeleton } from "../components/layout/Common";
import { PrudentiaWorkspace } from "../components/layout/PrudentiaWorkspace";
import type { RouteId } from "../routes";
import type { User as AuthUser } from "../types/api";
import { errorMessage, formatDateTime } from "../utils/format";

export function PrudentiaIngestionHealthPage({ onLogout, onNavigate, user }: Props) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const canViewConfigHealth = isPlatformAdmin(user);
  const canRecoverStaleJobs = isGlobalAdmin(user);
  const canViewSchedules = canManageSpaces(user);
  const summaryQuery = useQuery({ queryKey: ["ingest-jobs", "summary"], queryFn: () => ingestJobsApi.summary(), refetchInterval: 5000, staleTime: 4000, retry: false });
  const failuresQuery = useQuery({
    queryKey: ["ingest-jobs", "list", "health-failures"],
    queryFn: () => ingestJobsApi.list({ status: "failed", limit: 5 }),
    refetchInterval: 5000,
    staleTime: 4000,
    retry: false,
  });
  const schedulesQuery = useQuery({ queryKey: ["folder-ingest", "schedules"], queryFn: folderIngestApi.listSchedules, enabled: canViewSchedules, staleTime: 15000, retry: false });
  const ragConfigQuery = useQuery({ queryKey: ["admin", "rag-config"], queryFn: adminApi.getRagConfig, enabled: canViewConfigHealth, staleTime: 30000, retry: false });
  const ingestConfigQuery = useQuery({ queryKey: ["admin", "ingest-config"], queryFn: adminApi.getIngestConfig, enabled: canViewConfigHealth, refetchInterval: 5000, staleTime: 3000, retry: false });
  const graphStatusQuery = useQuery({ queryKey: ["ingest-jobs", "graphrag-status"], queryFn: ingestJobsApi.graphragStatus, refetchInterval: 5000, staleTime: 3000, retry: false });
  const staleJobsQuery = useQuery({
    queryKey: ["ingest-jobs", "stale"],
    queryFn: ingestJobsApi.listStale,
    enabled: canRecoverStaleJobs,
    refetchInterval: 5000,
    staleTime: 3000,
    retry: false,
  });
  const requeueMutation = useMutation({
    mutationFn: ingestJobsApi.requeueStale,
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ingest-jobs", "stale"] }),
        queryClient.invalidateQueries({ queryKey: ["ingest-jobs", "summary"] }),
        queryClient.invalidateQueries({ queryKey: ["ingest-jobs", "list"] }),
        queryClient.invalidateQueries({ queryKey: ["audit-log"] }),
      ]);
      notify({ title: "Job requeued", description: result.message, tone: "success" });
    },
    onError: (error) => notify({
      title: "Requeue failed",
      description: errorMessage(error, "The stale job could not be requeued."),
      tone: "error",
    }),
  });
  const summary = summaryQuery.data;
  const failedCount = summary?.status_counts.failed ?? 0;
  const reviewCount = summary?.status_counts.human_review ?? 0;
  const processingCount = (summary?.status_counts.processing ?? 0) + (summary?.status_counts.queued ?? 0) + (summary?.status_counts.scheduled ?? 0);
  const schedules = schedulesQuery.data?.items ?? [];
  const unhealthySchedules = schedules.filter((schedule) => schedule.status === "failed" || schedule.latest_run?.status === "failed");
  const graphStatus = graphStatusQuery.data;

  return (
    <PrudentiaWorkspace activeRoute="ingestion-health" onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page" id="main-content">
        <div className="sv-page-inner max-w-6xl">
          <header className="sv-page-header">
            <div>
              <p className="sv-eyebrow">System Overview</p>
              <h1 className="sv-page-title">Ingestion Health</h1>
              <p className="sv-page-subtitle">Operational status for document processing, review queues, failures, and scheduled folder sources.</p>
            </div>
            <button type="button" onClick={() => onNavigate("ingestion-jobs")} className="sv-action-secondary">
              <FileClock size={16} /> View Activity
            </button>
          </header>

          {summaryQuery.isError ? <InlineMessage tone="error">{errorMessage(summaryQuery.error, "Unable to load ingestion health.")}</InlineMessage> : null}
          <section className="ingestion-health-metrics">
            <HealthMetric icon={<Activity size={18} />} label="Active pipeline" value={String(processingCount)} detail="Scheduled, queued, or processing" loading={summaryQuery.isLoading} tone={processingCount > 0 ? "active" : "neutral"} />
            <HealthMetric icon={<ShieldAlert size={18} />} label="Needs review" value={String(reviewCount)} detail="Human intervention required" loading={summaryQuery.isLoading} tone={reviewCount > 0 ? "warning" : "neutral"} />
            <HealthMetric icon={<AlertTriangle size={18} />} label="Failed" value={String(failedCount)} detail="Runs needing investigation" loading={summaryQuery.isLoading} tone={failedCount > 0 ? "danger" : "neutral"} />
            <HealthMetric icon={<Database size={18} />} label="Completed" value={String(summary?.status_counts.complete ?? 0)} detail={`${summary?.total ?? 0} visible runs`} loading={summaryQuery.isLoading} tone="success" />
          </section>

          <div className="ingestion-health-grid">
            <section className="sv-panel p-5">
              <div className="knowledge-job-block-header">
                <div>
                  <h2>Stage distribution</h2>
                  <p>Current visible history grouped by the shared ingestion stage model.</p>
                </div>
              </div>
              <div className="ingestion-stage-list">
                {Object.entries(summary?.stage_counts ?? {}).sort(([, left], [, right]) => right - left).map(([stage, count]) => (
                  <div key={stage}>
                    <span>{labelize(stage)}</span>
                    <strong>{count}</strong>
                  </div>
                ))}
                {!summaryQuery.isLoading && Object.keys(summary?.stage_counts ?? {}).length === 0 ? <p className="text-secondary">No ingestion stages recorded yet.</p> : null}
              </div>
            </section>

            <section className="sv-panel p-5">
              <div className="knowledge-job-block-header">
                <div>
                  <h2>Runtime posture</h2>
                  <p>Services and scheduled sources visible to this account.</p>
                </div>
              </div>
              <div className="ingestion-runtime-list">
                <RuntimeRow icon={<Database size={16} />} label="Folder schedules" value={canViewSchedules ? `${schedules.length} visible` : "Restricted"} healthy={!canViewSchedules || unhealthySchedules.length === 0} />
                <RuntimeRow icon={<AlertTriangle size={16} />} label="Schedule failures" value={canViewSchedules ? String(unhealthySchedules.length) : "Restricted"} healthy={!canViewSchedules || unhealthySchedules.length === 0} />
                <RuntimeRow icon={<ServerCog size={16} />} label="Model runtime" value={canViewConfigHealth ? ragConfigQuery.data?.health.status ?? "Loading" : "Platform admin only"} healthy={!canViewConfigHealth || ["healthy", "ok"].includes(ragConfigQuery.data?.health.status ?? "")} />
                <RuntimeRow
                  icon={<Activity size={16} />}
                  label="Worker capacity"
                  value={canViewConfigHealth ? workerCapacityLabel(ingestConfigQuery.data) : "Platform admin only"}
                  healthy={!canViewConfigHealth || Boolean(ingestConfigQuery.data?.worker_online)}
                />
              </div>
              {schedulesQuery.isError ? <InlineMessage tone="warning">{errorMessage(schedulesQuery.error, "Unable to load folder schedule health.")}</InlineMessage> : null}
              {ragConfigQuery.isError ? <InlineMessage tone="warning">{errorMessage(ragConfigQuery.error, "Unable to load model runtime health.")}</InlineMessage> : null}
              {ingestConfigQuery.isError ? <InlineMessage tone="warning">{errorMessage(ingestConfigQuery.error, "Unable to load ingestion worker capacity.")}</InlineMessage> : null}
            </section>

            <section className="sv-panel p-5 ingestion-graph-panel">
              <div className="knowledge-job-block-header">
                <div>
                  <h2>GraphRAG activity</h2>
                  <p>Queue and worker activity for graph enrichment.</p>
                </div>
                <span className="sv-pill">{graphStatusQuery.isLoading ? "Checking" : graphStatus?.enabled ? "Enabled" : "Disabled"}</span>
              </div>
              <div className="ingestion-runtime-list">
                <RuntimeRow icon={<Network size={16} />} label="Graph queue" value={graphQueueLabel(graphStatus)} healthy={!graphStatus?.queue_error} />
                <RuntimeRow icon={<ServerCog size={16} />} label="Graph workers" value={graphWorkerLabel(graphStatus)} healthy={!graphStatus?.enabled || Boolean(graphStatus?.worker_online)} />
                <RuntimeRow icon={<Activity size={16} />} label="Active graph tasks" value={graphActiveLabel(graphStatus)} healthy={!graphStatus?.worker_error} />
              </div>
              {graphStatusQuery.isError ? <InlineMessage tone="warning">{errorMessage(graphStatusQuery.error, "Unable to load GraphRAG activity.")}</InlineMessage> : null}
              {graphStatus?.queue_error ? <InlineMessage tone="warning">Queue depth unavailable: {graphStatus.queue_error}</InlineMessage> : null}
              {graphStatus?.worker_error ? <InlineMessage tone="warning">Worker activity unavailable: {graphStatus.worker_error}</InlineMessage> : null}
              {graphStatusQuery.isLoading ? <p className="ingestion-graph-empty text-secondary">Checking GraphRAG activity.</p> : null}
              {!graphStatusQuery.isLoading && (graphStatus?.active_tasks.length ?? 0) === 0 ? (
                <p className="ingestion-graph-empty text-secondary">{graphStatus?.enabled ? "No active GraphRAG tasks." : "GraphRAG disabled."}</p>
              ) : null}
              {(graphStatus?.active_tasks ?? []).length > 0 ? (
                <div className="ingestion-graph-task-list">
                  {(graphStatus?.active_tasks ?? []).map((task) => (
                    <article key={task.task_id || `${task.worker}-${task.job_id ?? task.document_id ?? "graph-task"}`}>
                      <div>
                        <strong>{task.document_id ? shortIdentifier(task.document_id) : "Document pending"}</strong>
                        <p>{task.job_id ? `Job ${shortIdentifier(task.job_id)}` : "Graph task"} - {task.worker}</p>
                      </div>
                      <span>{formatGraphTaskDuration(task.elapsed_seconds)}</span>
                    </article>
                  ))}
                </div>
              ) : null}
            </section>
          </div>

          {canRecoverStaleJobs ? (
            <section className="sv-panel overflow-hidden ingestion-recovery-panel">
              <div className="ingest-job-list-header">
                <div>
                  <h2 className="sv-section-title">Stale Processing Runs</h2>
                  <p>
                    Runs missing a heartbeat for at least {formatDuration(staleJobsQuery.data?.stale_after_seconds ?? 120)}.
                    Active worker tasks are excluded.
                  </p>
                </div>
                <span className="sv-pill">
                  {staleJobsQuery.isLoading ? "Checking" : `${staleJobsQuery.data?.recoverable ?? 0} recoverable`}
                </span>
              </div>
              {staleJobsQuery.isError ? <InlineMessage tone="error">{errorMessage(staleJobsQuery.error, "Unable to check stale processing runs.")}</InlineMessage> : null}
              {staleJobsQuery.isLoading ? <p className="p-5 text-body-md text-secondary">Checking processing heartbeats and active worker tasks.</p> : null}
              {!staleJobsQuery.isLoading && (staleJobsQuery.data?.items.length ?? 0) === 0 ? (
                <p className="p-5 text-body-md text-secondary">No stale processing runs detected.</p>
              ) : null}
              {(staleJobsQuery.data?.items ?? []).map((job) => {
                const isRequeueing = requeueMutation.isPending && requeueMutation.variables === job.job_id;
                return (
                  <article key={job.job_id} className="ingestion-recovery-row">
                    <span className="ingestion-recovery-icon"><RotateCcw size={17} /></span>
                    <div>
                      <strong>{job.document_title}</strong>
                      <p>
                        {job.group_path} · attempt {job.attempt_count} of {job.max_attempts} · stale for {formatDuration(job.stale_for_seconds)}
                      </p>
                      <small>
                        Last activity {formatDateTime(job.last_activity_at)}. {job.recovery_message}
                      </small>
                    </div>
                    {job.recoverable ? (
                      <button
                        type="button"
                        className="sv-action-primary"
                        disabled={requeueMutation.isPending}
                        onClick={() => requeueMutation.mutate(job.job_id)}
                      >
                        {isRequeueing ? <Loader2 className="animate-spin" size={16} /> : <RotateCcw size={16} />}
                        {isRequeueing ? "Requeueing" : "Requeue run"}
                      </button>
                    ) : (
                      <span className="ingestion-recovery-blocked">Manual investigation required</span>
                    )}
                  </article>
                );
              })}
            </section>
          ) : null}

          <section className="sv-panel overflow-hidden">
            <div className="ingest-job-list-header">
              <div>
                <h2 className="sv-section-title">Recent Failures</h2>
                <p>Safe error details from the five most recent visible failed runs.</p>
              </div>
            </div>
            {failuresQuery.isError ? <InlineMessage tone="error">{errorMessage(failuresQuery.error, "Unable to load recent failures.")}</InlineMessage> : null}
            {!failuresQuery.isLoading && (failuresQuery.data?.items.length ?? 0) === 0 ? <p className="p-5 text-body-md text-secondary">No failed ingestion runs are visible.</p> : null}
            {(failuresQuery.data?.items ?? []).map((job) => (
              <article key={job.job_id} className="ingestion-failure-row">
                <span className="ingestion-failure-icon"><AlertTriangle size={17} /></span>
                <div>
                  <strong>{job.document_title}</strong>
                  <p>{job.group_path} · {labelize(job.origin)} · {formatDateTime(job.updated_at)}</p>
                  <small>{job.error_code ? `${job.error_code}: ` : ""}{job.error_message || job.stage_detail}</small>
                </div>
                <a href={`/documents?doc=${encodeURIComponent(job.document_id)}`} className="sv-action-secondary">Open Document</a>
              </article>
            ))}
          </section>
        </div>
      </main>
    </PrudentiaWorkspace>
  );
}

function workerCapacityLabel(config: Awaited<ReturnType<typeof adminApi.getIngestConfig>> | undefined) {
  if (!config) return "Loading";
  if (!config.worker_online) return `Offline · desired ${config.worker_concurrency}`;
  return `${config.observed_pool_size} running · ${config.active_jobs} active`;
}

type GraphRAGStatusShape = Awaited<ReturnType<typeof ingestJobsApi.graphragStatus>>;

function graphQueueLabel(status: GraphRAGStatusShape | undefined) {
  if (!status) return "Loading";
  if (!status.enabled) return "Disabled";
  if (status.queued_jobs === null) return "Unavailable";
  return `${status.queued_jobs} queued`;
}

function graphWorkerLabel(status: GraphRAGStatusShape | undefined) {
  if (!status) return "Loading";
  if (!status.enabled) return "Disabled";
  if (!status.worker_online) return "Offline";
  return `${status.observed_pool_size} running - ${status.active_jobs} active`;
}

function graphActiveLabel(status: GraphRAGStatusShape | undefined) {
  if (!status) return "Loading";
  if (!status.enabled) return "Disabled";
  return `${status.active_jobs} active`;
}

function HealthMetric({ detail, icon, label, loading, tone, value }: { detail: string; icon: JSX.Element; label: string; loading: boolean; tone: "active" | "danger" | "neutral" | "success" | "warning"; value: string }) {
  return (
    <article className="sv-panel ingestion-health-metric" aria-busy={loading} data-cursor-glow data-tone={tone}>
      <span>{icon}</span>
      <div>
        <p>{label}</p>
        {loading ? (
          <>
            <span className="sr-only">Loading {label.toLowerCase()}</span>
            <Skeleton className="mt-1 h-6 w-14" />
          </>
        ) : <strong>{value}</strong>}
        <small>{detail}</small>
      </div>
    </article>
  );
}

function RuntimeRow({ healthy, icon, label, value }: { healthy: boolean; icon: JSX.Element; label: string; value: string }) {
  return (
    <div>
      <span>{icon}{label}</span>
      <strong className={healthy ? "text-success" : "text-warning-amber"}>{value}</strong>
    </div>
  );
}

function labelize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDuration(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function formatGraphTaskDuration(seconds: number | null) {
  return seconds === null ? "Running" : formatDuration(seconds);
}

function shortIdentifier(value: string) {
  return value.length <= 14 ? value : `${value.slice(0, 8)}...${value.slice(-4)}`;
}

type Props = { onLogout: () => void; onNavigate: (route: RouteId) => void; user: AuthUser };
