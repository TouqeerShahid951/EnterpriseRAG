import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertTriangle, ChevronLeft, ChevronRight, FileClock, FileSearch, Loader2, Network, RotateCw, Search, Upload, XCircle } from "lucide-react";

import { adminApi, documentsApi, ingestJobsApi } from "../api/contracts";
import { canAccessClearance, canManageSpaces, canUpload, canViewSpaceMetadata, clearanceLevelLabel, hasExactGroupScope, isGlobalAdmin } from "../authz";
import { useToast } from "../components/feedback/ToastProvider";
import { InlineMessage, Skeleton } from "../components/layout/Common";
import { PrudentiaWorkspace } from "../components/layout/PrudentiaWorkspace";
import type { RouteId } from "../routes";
import { formatIngestRunLabel, formatSecondaryStageProgress, formatUploadWarning, graphEnrichmentForJob, graphEnrichmentTaskForJob, isUploadCancellableStatus, type GraphEnrichmentChip as GraphEnrichmentChipShape, type GraphEnrichmentTask } from "../state/uploadJobProgress";
import type { GraphRAGStatus, IngestJob, IngestJobOrigin, ParserProvenance, UploadJobState, User as AuthUser } from "../types/api";
import { errorMessage, formatDateTime } from "../utils/format";
import { flattenGroups, userSpacesFromPaths } from "../utils/groups";

const PAGE_SIZE = 25;

export function PrudentiaIngestionJobsPage({ onLogout, onNavigate, user }: Props) {
  const [search, setSearch] = useState(() => initialActivityStringParam("job_q") || initialActivityStringParam("search"));
  const [status, setStatus] = useState<UploadJobState | "">(() => initialJobStatusFromUrl());
  const [origin, setOrigin] = useState<IngestJobOrigin | "">(() => initialJobOriginFromUrl());
  const [groupPath, setGroupPath] = useState(() => initialActivityStringParam("space"));
  const [createdFrom, setCreatedFrom] = useState(() => initialActivityStringParam("created_from"));
  const [createdTo, setCreatedTo] = useState(() => initialActivityStringParam("created_to"));
  const [offset, setOffset] = useState(() => initialActivityOffsetFromUrl());
  const debouncedSearch = useDebouncedText(search, 300);
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const canLoadDirectory = canManageSpaces(user) || canViewSpaceMetadata(user);
  const summaryRequest = {
    group_path: groupPath || undefined,
    created_from: createdFrom ? `${createdFrom}T00:00:00Z` : undefined,
    created_to: createdTo ? `${createdTo}T23:59:59Z` : undefined,
  };
  const hasSummaryFilters = Boolean(summaryRequest.group_path || summaryRequest.created_from || summaryRequest.created_to);
  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, enabled: canLoadDirectory, retry: false });
  const spaceOptions = useMemo(
    () => (canLoadDirectory ? flattenGroups(groupsQuery.data?.items ?? []) : userSpacesFromPaths(user.group_paths)),
    [canLoadDirectory, groupsQuery.data?.items, user.group_paths],
  );
  const jobsQuery = useQuery({
    queryKey: ["ingest-jobs", "list", debouncedSearch, status, origin, groupPath, createdFrom, createdTo, offset],
    queryFn: () =>
      ingestJobsApi.list({
        search: debouncedSearch,
        status,
        origin,
        group_path: groupPath || undefined,
        created_from: createdFrom ? `${createdFrom}T00:00:00Z` : undefined,
        created_to: createdTo ? `${createdTo}T23:59:59Z` : undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    refetchInterval: (query) => query.state.data?.items.some((job) => isActiveJob(job.status)) ? 2500 : false,
    retry: false,
  });
  const summaryQuery = useQuery({
    queryKey: hasSummaryFilters ? ["ingest-jobs", "summary", summaryRequest] : ["ingest-jobs", "summary"],
    queryFn: () => ingestJobsApi.summary(summaryRequest),
    refetchInterval: (query) => query.state.data?.active ? 2500 : false,
    staleTime: 4000,
    retry: false,
  });
  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => ingestJobsApi.cancel(jobId),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["ingest-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["upload"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
  const reingestMutation = useMutation({
    mutationFn: (job: IngestJob) => documentsApi.reingest(job.document_id, retryRequestForJob(job)),
    onSuccess: async (response, job) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ingest-jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["upload"] }),
        queryClient.invalidateQueries({ queryKey: ["documents"] }),
        queryClient.invalidateQueries({ queryKey: ["audit-log"] }),
      ]);
      notify({
        title: job.status === "complete" ? "Reingestion queued" : "Retry queued",
        description: `${job.document_title} queued as job ${response.job_id}.`,
        tone: "success",
      });
    },
    onError: (error) => notify({
      title: "Retry failed",
      description: errorMessage(error, "Unable to queue document reingestion."),
      tone: "error",
    }),
  });
  const graphEnrichmentMutation = useMutation({
    mutationFn: (job: IngestJob) => documentsApi.enrichGraph(job.document_id),
    onSuccess: async (response, job) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ingest-jobs", "graphrag-status"] }),
        queryClient.invalidateQueries({ queryKey: ["audit-log"] }),
      ]);
      notify({
        title: "Graph enrichment queued",
        description: `${job.document_title} queued as graph task for job ${response.job_id}.`,
        tone: "success",
      });
    },
    onError: (error) => notify({
      title: "Graph enrichment not queued",
      description: errorMessage(error, "Unable to queue graph enrichment."),
      tone: "error",
    }),
  });
  const graphCancelMutation = useMutation({
    mutationFn: ({ job, task }: { job: IngestJob; task: GraphEnrichmentTask }) =>
      ingestJobsApi.cancelGraphEnrichment(task.jobId ?? job.job_id, task.taskId),
    onSuccess: async (response, { job }) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ingest-jobs", "graphrag-status"] }),
        queryClient.invalidateQueries({ queryKey: ["audit-log"] }),
      ]);
      notify({ title: "Graph enrichment cancelled", description: `${job.document_title}: ${response.message}`, tone: "success" });
    },
    onError: (error) => notify({
      title: "Graph enrichment not cancelled",
      description: errorMessage(error, "Unable to cancel graph enrichment."),
      tone: "error",
    }),
  });
  const items = jobsQuery.data?.items ?? [];
  const hasIndexedJobs = items.some((job) => job.status === "complete");
  const graphStatusQuery = useQuery({
    queryKey: ["ingest-jobs", "graphrag-status", "activity"],
    queryFn: ingestJobsApi.graphragStatus,
    enabled: hasIndexedJobs,
    refetchInterval: hasIndexedJobs ? 5000 : false,
    staleTime: 3000,
    retry: false,
  });
  const graphStatusError = graphStatusQuery.isError ? errorMessage(graphStatusQuery.error, "Unable to load graph enrichment status.") : null;
  const total = jobsQuery.data?.total ?? 0;
  const summary = summaryQuery.data;
  const firstItem = total === 0 ? 0 : offset + 1;
  const lastItem = Math.min(offset + items.length, total);

  useEffect(() => {
    syncActivityUrl({ createdFrom, createdTo, groupPath, offset, origin, search, status });
  }, [createdFrom, createdTo, groupPath, offset, origin, search, status]);

  function resetOffset<T>(setter: (value: T) => void, value: T) {
    setOffset(0);
    setter(value);
  }

  return (
    <PrudentiaWorkspace activeRoute="ingestion-jobs" onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page" id="main-content">
        <div className="sv-page-inner sv-page-inner-workbench max-w-none">
          <header className="sv-page-header">
            <div>
              <p className="sv-eyebrow">Document Intake</p>
              <h1 className="sv-page-title">Activity</h1>
              <p className="sv-page-subtitle">Track upload, folder, restore, and reingestion runs across your visible Knowledge Spaces.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => onNavigate("document-overview")} className="sv-action-secondary">
                <FileSearch size={16} /> Overview
              </button>
              {canUpload(user) ? (
                <button type="button" onClick={() => onNavigate("upload")} className="sv-action-primary">
                  <Upload size={16} /> Add Files
                </button>
              ) : null}
            </div>
          </header>

          {summaryQuery.isError ? <InlineMessage tone="warning">{errorMessage(summaryQuery.error, "Unable to load activity summary.")}</InlineMessage> : null}
          <section className="sv-panel overflow-hidden">
            <div className="knowledge-job-metrics" aria-label="Ingestion job summary">
              <JobMetric label="Active" loading={summaryQuery.isLoading} value={summary?.active ?? 0} />
              <JobMetric label="Attention" loading={summaryQuery.isLoading} value={summary?.needs_attention ?? 0} />
              <JobMetric label="Needs Review" loading={summaryQuery.isLoading} value={summary?.status_counts.human_review ?? 0} />
              <JobMetric label="Failed Runs" loading={summaryQuery.isLoading} value={summary?.status_counts.failed ?? 0} />
              <JobMetric label="Indexed" loading={summaryQuery.isLoading} value={summary?.status_counts.complete ?? 0} tone="success" />
              <JobMetric label="Total Runs" loading={summaryQuery.isLoading} value={summary?.total ?? 0} />
            </div>
          </section>

          <section className="sv-panel p-4">
            <div className="ingest-job-filters">
              <label className="ingest-job-search sv-field">
                <span className="sv-label">Search</span>
                <span className="knowledge-tree-search">
                  <Search size={16} aria-hidden="true" />
                  <input value={search} onChange={(event) => resetOffset(setSearch, event.target.value)} placeholder="Search document, job ID, or space..." />
                </span>
              </label>
              <FilterSelect label="Status" value={status} onChange={(value) => resetOffset(setStatus, value as UploadJobState | "")} options={["", "scheduled", "queued", "processing", "human_review", "cancelled", "failed", "complete"]} helper="Filter by current ingestion state." />
              <FilterSelect label="Origin" value={origin} onChange={(value) => resetOffset(setOrigin, value as IngestJobOrigin | "")} options={["", "upload", "folder", "connector", "reingest", "restore", "unknown"]} helper="Filter by how the job entered the queue." />
              <FilterSelect label="Knowledge Space" value={groupPath} onChange={(value) => resetOffset(setGroupPath, value)} options={["", ...spaceOptions.map((space) => space.path)]} helper="Limit activity to one retrieval space." />
              <label className="sv-field">
                <span className="sv-label">From</span>
                <input type="date" className="sv-input" value={createdFrom} onChange={(event) => resetOffset(setCreatedFrom, event.target.value)} />
                <small className="text-secondary">Show jobs created on or after this date.</small>
              </label>
              <label className="sv-field">
                <span className="sv-label">To</span>
                <input type="date" className="sv-input" value={createdTo} onChange={(event) => resetOffset(setCreatedTo, event.target.value)} />
                <small className="text-secondary">Show jobs created on or before this date.</small>
              </label>
            </div>
          </section>

          {jobsQuery.isError ? <InlineMessage tone="error">{errorMessage(jobsQuery.error, "Unable to load ingestion jobs.")}</InlineMessage> : null}
          {cancelMutation.isError ? <InlineMessage tone="error">{errorMessage(cancelMutation.error, "Unable to cancel ingestion job.")}</InlineMessage> : null}
          {reingestMutation.isError ? <InlineMessage tone="error">{errorMessage(reingestMutation.error, "Unable to queue document reingestion.")}</InlineMessage> : null}
          <section className="sv-panel overflow-hidden">
            <div className="ingest-job-list-header">
              <div>
                <h2 className="sv-section-title">Activity History</h2>
                <p>{jobsQuery.isLoading ? "Loading jobs" : `${firstItem}-${lastItem} of ${total}`}</p>
              </div>
              <div className="ingest-job-pagination">
                <button type="button" className="sv-action-secondary" disabled={offset === 0 || jobsQuery.isLoading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                  <ChevronLeft size={15} /> Previous
                </button>
                <button type="button" className="sv-action-secondary" disabled={offset + PAGE_SIZE >= total || jobsQuery.isLoading} onClick={() => setOffset(offset + PAGE_SIZE)}>
                  Next <ChevronRight size={15} />
                </button>
              </div>
            </div>
            {jobsQuery.isLoading ? <JobSkeleton /> : null}
            {!jobsQuery.isLoading && items.length === 0 ? (
              <div className="knowledge-empty-state">
                <FileClock size={22} />
                <h3>No ingestion jobs match these filters</h3>
                <p>Adjust the filters or upload a document to start a new job.</p>
              </div>
            ) : null}
            {!jobsQuery.isLoading && items.length > 0 ? (
              <JobTable
                cancelingJobId={cancelMutation.isPending ? cancelMutation.variables ?? null : null}
                cancellingGraphTaskId={graphCancelMutation.isPending ? graphCancelMutation.variables?.task.taskId ?? null : null}
                enrichingJobId={graphEnrichmentMutation.isPending ? graphEnrichmentMutation.variables?.job_id ?? null : null}
                graphStatus={graphStatusQuery.data}
                graphStatusError={graphStatusError}
                items={items}
                onCancelJob={(jobId) => cancelMutation.mutate(jobId)}
                onCancelGraph={(job, task) => graphCancelMutation.mutate({ job, task })}
                onEnrichGraph={(job) => graphEnrichmentMutation.mutate(job)}
                onReingestJob={(job) => reingestMutation.mutate(job)}
                reingestingDocumentId={reingestMutation.isPending ? reingestMutation.variables?.document_id ?? null : null}
                user={user}
              />
            ) : null}
          </section>
        </div>
      </main>
    </PrudentiaWorkspace>
  );
}

function JobTable({ cancelingJobId, cancellingGraphTaskId, enrichingJobId, graphStatus, graphStatusError, items, onCancelGraph, onCancelJob, onEnrichGraph, onReingestJob, reingestingDocumentId, user }: { cancelingJobId: string | null; cancellingGraphTaskId: string | null; enrichingJobId: string | null; graphStatus: GraphRAGStatus | undefined; graphStatusError: string | null; items: IngestJob[]; onCancelGraph: (job: IngestJob, task: GraphEnrichmentTask) => void; onCancelJob: (jobId: string) => void; onEnrichGraph: (job: IngestJob) => void; onReingestJob: (job: IngestJob) => void; reingestingDocumentId: string | null; user: AuthUser }) {
  const retriedJobIds = new Set(items.map((job) => job.retry_of_job_id).filter((jobId): jobId is string => Boolean(jobId)));
  return (
    <div className="knowledge-doc-surface">
      <table className="sv-table ingest-job-table">
        <thead>
          <tr>
            <th>Document</th>
            <th>Origin</th>
            <th>Status</th>
            <th>Progress</th>
            <th>Started</th>
            <th>Details</th>
            <th className="ingest-job-actions-heading">Actions</th>
          </tr>
        </thead>
        <tbody>
          {items.map((job) => {
            const progressDetail = formatSecondaryStageProgress(job.stage_progress, job.stage_detail);
            const graphChip = graphEnrichmentForJob(
              { jobId: job.job_id, status: job.status, documentId: job.document_id },
              graphStatus,
              graphStatusError,
            );
            const graphTask = graphEnrichmentTaskForJob(
              { jobId: job.job_id, documentId: job.document_id },
              graphStatus,
            );
            const canManageJob = canManageActivityJob(job, user);
            const canCancel = isUploadCancellableStatus(job.status) && canManageJob;
            const canEnrichGraph = job.status === "complete" && canManageJob;
            const wasRetried = retriedJobIds.has(job.job_id);
            const canReingest = !wasRetried && canReingestFromActivity(job, user);
            const reingesting = reingestingDocumentId === job.document_id;
            return (
              <tr key={job.job_id} className="sv-table-row">
                <td data-label="Document">
                  <a className="knowledge-document-open" href={`/documents?doc=${encodeURIComponent(job.document_id)}`}>
                    <FileClock size={17} />
                    <span>
                      <strong>{job.document_title}</strong>
                      <small>{job.group_path} · {clearanceLevelLabel(job.clearance_level)} · {job.job_id}</small>
                    </span>
                  </a>
                </td>
                <td data-label="Origin"><span className="sv-pill">{labelize(job.origin)}</span></td>
                <td data-label="Status"><JobStatusPill status={job.status} warnings={job.warnings} /></td>
                <td data-label="Progress">
                  <div className="ingest-job-progress-cell">
                    <div className="knowledge-job-progress" aria-label={`${job.document_title} ingestion progress`} aria-valuemax={100} aria-valuemin={0} aria-valuenow={job.progress_pct} role="progressbar">
                      <span style={{ width: `${job.progress_pct}%` }} />
                    </div>
                    <strong>{job.progress_pct}%</strong>
                  </div>
                  {progressDetail ? <small>{progressDetail}</small> : null}
                </td>
                <td data-label="Started" className="text-secondary">{formatDateTime(job.created_at)}</td>
                <td data-label="Details">
                  <strong>{job.stage_label}</strong>
                  <p className="text-on-surface-variant">{job.error_message || job.stage_detail}</p>
                  {job.error_code ? <span className="ingest-job-error"><AlertTriangle size={13} /> {job.error_code}</span> : null}
                  {wasRetried ? <span className="ingest-job-error text-primary"><RotateCw size={13} /> Retried by a newer job</span> : null}
                  {job.retry_of_job_id ? <span className="ingest-job-error text-secondary"><RotateCw size={13} /> Retry of {job.retry_of_job_id}</span> : null}
                  {job.warnings.map((warning) => (
                    <span className="ingest-job-error text-warning-amber" key={warning}><AlertTriangle size={13} /> {formatUploadWarning(warning)}</span>
                  ))}
                  {graphChip ? <GraphEnrichmentChip chip={graphChip} /> : null}
                  {job.parser_provenance ? <ParserProvenanceDetails provenance={job.parser_provenance} /> : null}
                  <small>{formatIngestRunLabel(job)}</small>
                </td>
                <td className="ingest-job-actions-cell" data-label="Actions">
                  <div className="knowledge-row-actions ingest-job-actions">
                    {canCancel ? (
                      <CancelJobControl
                        disabled={cancelingJobId === job.job_id}
                        onCancel={() => onCancelJob(job.job_id)}
                      />
                    ) : null}
                    {canReingest ? (
                      <ReingestJobControl
                        disabled={reingesting}
                        job={job}
                        onReingest={() => onReingestJob(job)}
                      />
                    ) : null}
                    {canEnrichGraph && graphTask ? (
                      <CancelGraphControl
                        disabled={cancellingGraphTaskId === graphTask.taskId}
                        onCancel={() => onCancelGraph(job, graphTask)}
                        state={graphTask.state}
                      />
                    ) : null}
                    {canEnrichGraph && graphStatus?.enabled && !graphTask ? (
                      <EnrichGraphControl
                        chip={graphChip}
                        disabled={enrichingJobId === job.job_id || Boolean(graphChip)}
                        isQueueing={enrichingJobId === job.job_id}
                        onEnrich={() => onEnrichGraph(job)}
                        title={job.document_title}
                      />
                    ) : null}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CancelGraphControl({ disabled, onCancel, state }: { disabled: boolean; onCancel: () => void; state: GraphEnrichmentTask["state"] }) {
  return (
    <button
      className="ingest-job-action inline-flex items-center gap-1 rounded-md border border-error-red/30 px-2 py-1 text-label-md font-bold text-error-red hover:bg-error-container disabled:cursor-not-allowed disabled:opacity-50"
      disabled={disabled}
      onClick={onCancel}
      title={`Cancel ${state} graph enrichment`}
      type="button"
    >
      {disabled ? <Loader2 className="animate-spin" size={13} /> : <XCircle size={13} />}
      {disabled ? "Cancelling" : "Cancel graph"}
    </button>
  );
}

function EnrichGraphControl({ chip, disabled, isQueueing, onEnrich, title }: { chip: GraphEnrichmentChipShape | null; disabled: boolean; isQueueing: boolean; onEnrich: () => void; title: string }) {
  const label = isQueueing
    ? "Queueing"
    : chip?.state === "running"
      ? "Running"
      : chip?.state === "queued"
        ? "Queued"
        : chip?.state === "unavailable"
          ? "Unavailable"
          : "Enrich graph";
  return (
    <button
      className="ingest-job-action inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-secondary hover:bg-surface hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
      disabled={disabled}
      onClick={onEnrich}
      title={chip?.detail ?? `Enrich graph for ${title}`}
      type="button"
    >
      {isQueueing ? <Loader2 className="animate-spin" size={13} /> : <Network size={13} />}
      {label}
    </button>
  );
}

function GraphEnrichmentChip({ chip }: { chip: GraphEnrichmentChipShape }) {
  const className = chip.state === "unavailable"
    ? "ingest-job-error text-warning-amber"
    : "ingest-job-error text-primary";
  return (
    <span className={className}>
      {chip.state === "unavailable" ? <AlertTriangle size={13} /> : <Activity className={chip.state === "running" ? "animate-pulse" : ""} size={13} />}
      {chip.label}
      {chip.detail ? ` - ${chip.detail}` : ""}
    </span>
  );
}

function ReingestJobControl({ disabled, job, onReingest }: { disabled: boolean; job: IngestJob; onReingest: () => void }) {
  const isRetry = job.status === "failed" || job.status === "cancelled";
  return (
    <button
      className="ingest-job-action inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-secondary hover:bg-surface hover:text-primary disabled:opacity-50"
      disabled={disabled}
      onClick={onReingest}
      title={`${isRetry ? "Retry ingestion for" : "Reingest"} ${job.document_title}`}
      type="button"
    >
      {disabled ? <Loader2 className="animate-spin" size={13} /> : <RotateCw size={13} />}
      {disabled ? "Queueing" : isRetry ? "Retry" : "Reingest"}
    </button>
  );
}

function CancelJobControl({ disabled, onCancel }: { disabled: boolean; onCancel: () => void }) {
  const [confirming, setConfirming] = useState(false);
  if (confirming) {
    return (
      <div className="ingest-job-cancel-confirmation">
        <button
          className="ingest-job-action rounded-md border border-error-red/30 px-2 py-1 text-label-md font-bold text-error-red hover:bg-error-container disabled:opacity-50"
          disabled={disabled}
          onClick={() => {
            onCancel();
            setConfirming(false);
          }}
          type="button"
        >
          {disabled ? "Cancelling" : "Cancel"}
        </button>
        <button className="ingest-job-action rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-secondary hover:bg-surface" disabled={disabled} onClick={() => setConfirming(false)} type="button">
          Keep
        </button>
      </div>
    );
  }
  return (
    <button
      className="ingest-job-action inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-secondary hover:bg-surface hover:text-error-red disabled:opacity-50"
      disabled={disabled}
      onClick={() => setConfirming(true)}
      type="button"
    >
      <XCircle size={13} />
      {disabled ? "Cancelling" : "Cancel"}
    </button>
  );
}

function ParserProvenanceDetails({ provenance }: { provenance: ParserProvenance }) {
  const selection = provenance.docling_selection;
  const topFlags = topCounts(provenance.quality_flag_counts, 4);
  return (
    <details className="ingest-parser-provenance">
      <summary>Parser provenance</summary>
      <dl>
        <div>
          <dt>Routing</dt>
          <dd>{labelize(provenance.routing_mode)}</dd>
        </div>
        <div>
          <dt>Parsers</dt>
          <dd>{formatCounts(provenance.parser_item_counts) || provenance.primary_parser}</dd>
        </div>
        <div>
          <dt>Pages</dt>
          <dd>{provenance.page_count ?? "Unknown"}</dd>
        </div>
        {selection ? (
          <div>
            <dt>Docling</dt>
            <dd>
              {selection.selected_pages.total} selected, {selection.skipped_pages.total} skipped
              {" "}({selection.weak_pages_total} weak, budget {selection.budget_pages}, batch {selection.batch_pages})
            </dd>
          </div>
        ) : null}
        {topFlags ? (
          <div>
            <dt>Quality</dt>
            <dd>{topFlags}</dd>
          </div>
        ) : null}
        {provenance.fallback ? (
          <div>
            <dt>Fallback</dt>
            <dd>{[provenance.fallback.from, provenance.fallback.to, provenance.fallback.reason].filter(Boolean).join(" → ")}</dd>
          </div>
        ) : null}
        {provenance.errors.length > 0 ? (
          <div>
            <dt>Errors</dt>
            <dd>{provenance.errors.map((error) => error.code || error.component).filter(Boolean).join(", ")}</dd>
          </div>
        ) : null}
      </dl>
    </details>
  );
}

function formatCounts(counts: Record<string, number>) {
  return Object.entries(counts).map(([key, value]) => `${labelize(key)} ${value}`).join(", ");
}

function topCounts(counts: Record<string, number>, limit: number) {
  return Object.entries(counts)
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, limit)
    .map(([key, value]) => `${labelize(key)} ${value}`)
    .join(", ");
}

function JobStatusPill({ status, warnings }: { status: UploadJobState; warnings: string[] }) {
  const className = status === "complete" && warnings.length > 0
    ? "sv-pill sv-pill-warning"
    : status === "complete"
    ? "sv-pill sv-pill-success"
    : status === "failed"
      ? "sv-pill knowledge-status-failed"
      : status === "cancelled"
        ? "sv-pill sv-pill-warning"
      : status === "human_review"
        ? "sv-pill knowledge-status-human_review"
        : "sv-pill knowledge-status-processing";
  return <span className={className}>{status === "complete" && warnings.length > 0 ? "Indexed with warnings" : labelize(status)}</span>;
}

function FilterSelect({ helper, label, onChange, options, value }: { helper?: string; label: string; onChange: (value: string) => void; options: string[]; value: string }) {
  return (
    <label className="sv-field">
      <span className="sv-label">{label}</span>
      <select className="sv-select" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option || "all"} value={option}>{option ? labelize(option) : `All ${label}`}</option>)}
      </select>
      {helper ? <small className="text-secondary">{helper}</small> : null}
    </label>
  );
}

function JobSkeleton() {
  return <div className="grid gap-2 p-4">{Array.from({ length: 5 }, (_, index) => <div className="knowledge-skeleton-row" key={index} />)}</div>;
}

function JobMetric({ label, loading, tone, value }: { label: string; loading: boolean; tone?: "success"; value: number }) {
  return (
    <div className={tone === "success" ? "knowledge-context-metric knowledge-context-metric-success" : "knowledge-context-metric"}>
      <span>{label}</span>
      {loading ? <Skeleton className="mt-1 h-6 w-12" /> : <strong>{value}</strong>}
    </div>
  );
}

function labelize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function isActiveJob(status: UploadJobState) {
  return ["scheduled", "queued", "processing", "human_review"].includes(status);
}

function canReingestFromActivity(job: IngestJob, user: AuthUser) {
  return (
    ["complete", "failed", "cancelled"].includes(job.status) &&
    canManageActivityJob(job, user)
  );
}

function retryRequestForJob(job: IngestJob) {
  return job.status === "failed" || job.status === "cancelled" ? { retry_of_job_id: job.job_id } : null;
}

function canManageActivityJob(job: IngestJob, user: AuthUser) {
  return (
    job.uploaded_by === user.user_id ||
    (canAccessClearance(user, job.clearance_level) &&
      (isGlobalAdmin(user) || (user.account_type === "space_admin" && hasExactGroupScope(user, job.group_path))))
  );
}

function initialActivityStringParam(name: string) {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get(name)?.trim() ?? "";
}

function useDebouncedText(value: string, delayMs: number) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [delayMs, value]);
  return debounced;
}

function initialActivityOffsetFromUrl() {
  const value = Number.parseInt(initialActivityStringParam("offset"), 10);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function initialJobOriginFromUrl(): IngestJobOrigin | "" {
  const value = initialActivityStringParam("origin");
  return isJobOrigin(value) ? value : "";
}

function initialJobStatusFromUrl(): UploadJobState | "" {
  const value = initialActivityStringParam("status");
  return isJobStatus(value) ? value : "";
}

function syncActivityUrl({ createdFrom, createdTo, groupPath, offset, origin, search, status }: ActivityUrlState) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.delete("search");
  setUrlParam(url.searchParams, "job_q", search.trim());
  setUrlParam(url.searchParams, "status", status);
  setUrlParam(url.searchParams, "origin", origin);
  setUrlParam(url.searchParams, "space", groupPath);
  setUrlParam(url.searchParams, "created_from", createdFrom);
  setUrlParam(url.searchParams, "created_to", createdTo);
  setUrlParam(url.searchParams, "offset", offset > 0 ? String(offset) : "");
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== current) window.history.replaceState(window.history.state, "", next);
}

function setUrlParam(params: URLSearchParams, key: string, value: string) {
  if (value) params.set(key, value);
  else params.delete(key);
}

function isJobOrigin(value: string): value is IngestJobOrigin {
  return value === "upload" || value === "folder" || value === "connector" || value === "reingest" || value === "restore" || value === "unknown";
}

function isJobStatus(value: string): value is UploadJobState {
  return value === "scheduled" || value === "queued" || value === "processing" || value === "human_review" || value === "cancelled" || value === "failed" || value === "complete";
}

type ActivityUrlState = { createdFrom: string; createdTo: string; groupPath: string; offset: number; origin: IngestJobOrigin | ""; search: string; status: UploadJobState | "" };
type Props = { onLogout: () => void; onNavigate: (route: RouteId) => void; user: AuthUser };
