import { useState } from "react";
import { Activity, AlertTriangle, FileClock, Loader2, Network, RotateCw, XCircle } from "lucide-react";
import {
  canAccessClearance,
  clearanceLevelLabel,
  hasExactGroupScope,
  isGlobalAdmin,
} from "@/lib/auth/authz";
import {
  formatIngestRunLabel,
  formatSecondaryStageProgress,
  formatUploadWarning,
  graphEnrichmentForJob,
  graphEnrichmentTaskForJob,
  isUploadCancellableStatus,
  type GraphEnrichmentChip as GraphEnrichmentChipShape,
  type GraphEnrichmentTask,
} from "@/features/upload/state/uploadJobProgress";
import type { GraphRAGStatus, IngestJob, ParserProvenance, UploadJobState, User as AuthUser } from "@/types/api";
import { formatDateTime } from "@/lib/utils/format";

export function JobTable({ cancelingJobId, cancellingGraphTaskId, enrichingJobId, graphStatus, graphStatusError, items, onCancelGraph, onCancelJob, onEnrichGraph, onReingestJob, reingestingDocumentId, user }: { cancelingJobId: string | null; cancellingGraphTaskId: string | null; enrichingJobId: string | null; graphStatus: GraphRAGStatus | undefined; graphStatusError: string | null; items: IngestJob[]; onCancelGraph: (job: IngestJob, task: GraphEnrichmentTask) => void; onCancelJob: (jobId: string) => void; onEnrichGraph: (job: IngestJob) => void; onReingestJob: (job: IngestJob) => void; reingestingDocumentId: string | null; user: AuthUser }) {
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

export function labelize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function isActiveJob(status: UploadJobState) {
  return ["scheduled", "queued", "processing", "human_review"].includes(status);
}

function canReingestFromActivity(job: IngestJob, user: AuthUser) {
  return (
    ["complete", "failed", "cancelled"].includes(job.status) &&
    canManageActivityJob(job, user)
  );
}

export function retryRequestForJob(job: IngestJob) {
  return job.status === "failed" || job.status === "cancelled" ? { retry_of_job_id: job.job_id } : null;
}

function canManageActivityJob(job: IngestJob, user: AuthUser) {
  return (
    job.uploaded_by === user.user_id ||
    (canAccessClearance(user, job.clearance_level) &&
      (isGlobalAdmin(user) || (user.account_type === "space_admin" && hasExactGroupScope(user, job.group_path))))
  );
}
