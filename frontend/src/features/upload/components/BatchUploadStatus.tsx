import { useState } from "react";
import { Activity, AlertTriangle, Clock3, Loader2, RotateCw, TimerReset, X, XCircle } from "lucide-react";
import {
  activeStageProgressNote,
  currentJobStep,
  durationTakenText,
  elapsedText,
  jobActivityClass,
  jobActivityText,
  jobPanelClass,
  nextJobStep,
  parserSummaryText,
  progressFillClass,
  progressTextClass,
  stageIcon,
  stageIconClass,
  stepChipClass,
  stepStateIcon,
  terminalDetailIcon,
} from "@/features/upload/components/uploadJobPresentation";
import { canWriteDocument, clearanceLevelLabel } from "@/lib/auth/authz";
import {
  formatIngestRunLabel,
  formatSecondaryStageProgress,
  formatUploadWarning,
  graphEnrichmentForJob,
  isUploadCancellableStatus,
  isUploadTerminalStatus,
  type GraphEnrichmentChip as GraphEnrichmentChipShape,
} from "@/features/upload/state/uploadJobProgress";
import type { GraphRAGStatus, User as AuthUser } from "@/types/api";
import type { UploadBatchItemView, UploadJobView } from "@/types/chat";
import { formatFileSize } from "@/features/upload/state/pdfUploadBatch";
import { errorMessage } from "@/lib/utils/format";

export function BatchUploadStatus({ cancelingJobId, currentUser, graphStatus, graphStatusError, items, onCancelIngestJob, onClearUploadJobs, onRetryIngestJob, retryingJobId }: BatchUploadStatusProps) {
  const completeCount = items.filter((item) => item.job?.status === "complete").length;
  const attentionCount = items.filter((item) => item.requestState === "failed" || item.job?.status === "failed" || item.job?.status === "human_review" || item.job?.status === "cancelled").length;
  const clearableIds = items.filter(isClearableUploadItem).map((item) => item.id);
  return (
    <section className="mt-6 border-t border-surface-border pt-5" aria-label="Document batch progress" aria-live="polite">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="sv-section-title">Recent upload jobs</h2>
          <p className="text-label-md text-secondary">{completeCount} complete{attentionCount > 0 ? ` · ${attentionCount} need attention` : ""}</p>
        </div>
        <button type="button" className="sv-action-secondary" disabled={clearableIds.length === 0} onClick={() => onClearUploadJobs(clearableIds)}>
          <X size={14} /> Clear finished
        </button>
      </div>
      <ol className="mt-3 grid gap-3">
        {items.map((item) => (
          <BatchUploadRow
            cancelingJobId={cancelingJobId}
            currentUser={currentUser}
            graphStatus={graphStatus}
            graphStatusError={graphStatusError}
            item={item}
            key={item.id}
            onCancelIngestJob={onCancelIngestJob}
            onClearUploadJobs={onClearUploadJobs}
            onRetryIngestJob={onRetryIngestJob}
            retryingJobId={retryingJobId}
          />
        ))}
      </ol>
    </section>
  );
}

function BatchUploadRow({ cancelingJobId, currentUser, graphStatus, graphStatusError, item, onCancelIngestJob, onClearUploadJobs, onRetryIngestJob, retryingJobId }: BatchUploadRowProps) {
  const job = item.job;
  const progressPct = job ? Math.max(0, Math.min(100, job.progressPct)) : item.requestState === "uploading" ? 8 : 0;
  const rowStatus = item.requestState === "failed" ? "failed" : job?.status ?? "processing";
  const canCancel = Boolean(job && isUploadCancellableStatus(job.status) && canWriteDocument(currentUser, item.groupPath, item.clearanceLevel));
  const canRetry = Boolean(job?.documentId && (job.status === "failed" || job.status === "cancelled") && canWriteDocument(currentUser, item.groupPath, item.clearanceLevel));
  const canceling = Boolean(job && cancelingJobId === job.jobId);
  const retrying = Boolean(job && retryingJobId === job.jobId);
  const stageProgress = formatSecondaryStageProgress(job?.stageProgress, job?.stageDetail);
  const graphChip = job ? graphEnrichmentForJob(job, graphStatus, graphStatusError) : null;
  const error = item.uploadError
    ? errorMessage(item.uploadError, "Document upload failed.")
    : item.jobError
      ? errorMessage(item.jobError, "Unable to poll upload status.")
      : job?.errorMessage;
  return (
    <li className={`rounded-lg border p-3 ${jobPanelClass(rowStatus)}`}>
      <div className="flex items-start gap-3">
        <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${stageIconClass(rowStatus)}`}>
          {item.requestState === "failed" ? <XCircle aria-hidden="true" size={17} /> : job ? stageIcon(job) : <Loader2 aria-hidden="true" className="animate-spin" size={17} />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="min-w-0 truncate text-body-md font-extrabold text-on-surface">{item.fileName}</h3>
            <strong className={`text-label-md ${progressTextClass(rowStatus)}`}>{progressPct}%</strong>
          </div>
          <p className="mt-0.5 text-label-md text-secondary">
            {[item.fileSize === null ? null : formatFileSize(item.fileSize), item.groupPath, clearanceLevelLabel(item.clearanceLevel), job ? `Job ${job.jobId.slice(0, 8)}` : null].filter(Boolean).join(" · ")}
          </p>
          <p className="mt-1 text-body-md text-on-surface-variant">
            {item.requestState === "uploading" ? "Validating, scanning, and queueing this document." : item.requestState === "failed" ? "The document was not queued." : job?.stageDetail}
          </p>
          {stageProgress ? <p className="mt-1 text-label-md font-extrabold text-primary">{stageProgress}</p> : null}
          {job ? <UploadJobRuntimeDetail job={job} stageProgress={stageProgress} /> : null}
          {graphChip ? <GraphEnrichmentChip chip={graphChip} /> : null}
          <UploadRowActions
            canCancel={canCancel}
            canRetry={canRetry}
            canceling={canceling}
            item={item}
            onCancel={() => {
              if (job) onCancelIngestJob(job.jobId);
            }}
            onClear={() => onClearUploadJobs([item.id])}
            onRetry={() => onRetryIngestJob(item)}
            retrying={retrying}
          />
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface">
            <div
              aria-label={`${item.fileName} ingestion progress`}
              aria-valuemax={100}
              aria-valuemin={0}
              aria-valuenow={progressPct}
              className={`h-full rounded-full transition-all duration-300 ${progressFillClass(rowStatus)}`}
              role="progressbar"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          {error ? <p className="mt-2 text-body-md font-semibold text-error-red">{job?.errorCode ? `${job.errorCode}: ` : ""}{error}</p> : null}
        </div>
      </div>
    </li>
  );
}

function GraphEnrichmentChip({ chip }: { chip: GraphEnrichmentChipShape }) {
  const className = chip.state === "unavailable"
    ? "border-warning-amber/30 bg-warning-amber/10 text-warning-amber"
    : "border-primary/30 bg-primary/10 text-primary";
  return (
    <p className={`mt-2 inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] font-bold ${className}`}>
      {chip.state === "unavailable" ? <AlertTriangle size={12} /> : <Activity className={chip.state === "running" ? "animate-pulse" : ""} size={12} />}
      <span>{chip.label}</span>
      {chip.detail ? <span className="font-semibold opacity-80">{chip.detail}</span> : null}
    </p>
  );
}

function UploadJobRuntimeDetail({ job, stageProgress }: { job: UploadJobView; stageProgress: string | null }) {
  const isActive = job.status === "scheduled" || job.status === "queued" || job.status === "processing";
  const currentStep = currentJobStep(job);
  const nextStep = nextJobStep(job);
  const activeStageNote = activeStageProgressNote(job, stageProgress);
  const parserSummary = parserSummaryText(job);
  const elapsedLabel = elapsedText(job);
  const durationLabel = durationTakenText(job);
  return (
    <div className="mt-3 rounded-md border border-surface-border bg-surface/45 p-2.5">
      <div className="flex flex-wrap items-center gap-2 text-label-md text-secondary">
        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 font-bold ${jobActivityClass(job)}`}>
          {isActive ? <Activity className="animate-pulse" size={13} /> : terminalDetailIcon(job)}
          {jobActivityText(job)}
        </span>
        {elapsedLabel ? (
          <span className="inline-flex items-center gap-1">
            <Clock3 size={13} />
            {elapsedLabel}
          </span>
        ) : null}
        {durationLabel ? (
          <span className="inline-flex items-center gap-1">
            <TimerReset size={13} />
            {durationLabel}
          </span>
        ) : null}
        <span>{formatIngestRunLabel(job)}</span>
      </div>
      {currentStep ? (
        <p className="mt-2 text-label-md text-on-surface-variant">
          <strong className="text-on-surface">{currentStep.label}:</strong> {currentStep.detail}
          {nextStep ? <span className="text-secondary"> Next: {nextStep.label}.</span> : null}
        </p>
      ) : null}
      {activeStageNote ? <p className="mt-1 text-label-md text-secondary">{activeStageNote}</p> : null}
      {parserSummary ? <p className="mt-1 text-label-md text-secondary">{parserSummary}</p> : null}
      <ol className="mt-2 flex flex-wrap gap-1.5" aria-label="Ingestion pipeline step status">
        {job.steps.map((step) => (
          <li key={step.id} className={`inline-flex min-h-7 items-center gap-1 rounded-full border px-2 py-1 text-[11px] font-bold ${stepChipClass(step.state)}`}>
            {stepStateIcon(step)}
            <span>{step.label}</span>
          </li>
        ))}
      </ol>
      {job.warnings.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {job.warnings.map((warning) => (
            <span className="inline-flex items-center gap-1 rounded-full border border-warning-amber/30 bg-warning-amber/10 px-2 py-1 text-[11px] font-bold text-warning-amber" key={warning}>
              <AlertTriangle size={12} />
              {formatUploadWarning(warning)}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function UploadRowActions({ canCancel, canRetry, canceling, item, onCancel, onClear, onRetry, retrying }: UploadRowActionsProps) {
  const [confirmCancel, setConfirmCancel] = useState(false);
  const clearable = isClearableUploadItem(item);
  if (!canCancel && !canRetry && !clearable) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-label-md">
      {canRetry ? (
        <button
          className="inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 font-bold text-secondary hover:bg-surface hover:text-primary disabled:opacity-50"
          disabled={retrying}
          onClick={onRetry}
          type="button"
        >
          {retrying ? <Loader2 className="animate-spin" size={13} /> : <RotateCw size={13} />}
          {retrying ? "Queueing" : "Retry"}
        </button>
      ) : null}
      {canCancel ? (
        <CancelIngestControl
          confirming={confirmCancel}
          disabled={canceling}
          onCancel={onCancel}
          onConfirmingChange={setConfirmCancel}
        />
      ) : null}
      {clearable ? (
        <button
          className="inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 font-bold text-secondary hover:bg-surface hover:text-on-surface"
          onClick={onClear}
          type="button"
        >
          <X size={13} /> Clear
        </button>
      ) : null}
    </div>
  );
}

function CancelIngestControl({ confirming, disabled, onCancel, onConfirmingChange }: { confirming: boolean; disabled: boolean; onCancel: () => void; onConfirmingChange: (value: boolean) => void }) {
  if (confirming) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-error-red">Cancel this ingestion job?</span>
        <button
          className="rounded-md border border-error-red/30 px-2 py-1 font-bold text-error-red hover:bg-error-container disabled:opacity-50"
          disabled={disabled}
          onClick={() => {
            onCancel();
            onConfirmingChange(false);
          }}
          type="button"
        >
          {disabled ? "Cancelling" : "Cancel job"}
        </button>
        <button className="rounded-md border border-surface-border px-2 py-1 font-bold text-secondary hover:bg-surface" disabled={disabled} onClick={() => onConfirmingChange(false)} type="button">
          Keep running
        </button>
      </div>
    );
  }
  return (
    <button
      className="inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 font-bold text-secondary hover:bg-surface hover:text-error-red disabled:opacity-50"
      disabled={disabled}
      onClick={() => onConfirmingChange(true)}
      type="button"
    >
      <XCircle size={13} />
      {disabled ? "Cancelling" : "Cancel job"}
    </button>
  );
}

function isClearableUploadItem(item: UploadBatchItemView) {
  return item.requestState === "failed" || isUploadTerminalStatus(item.job?.status);
}

export type BatchUploadStatusProps = { cancelingJobId: string | null; currentUser: AuthUser; graphStatus: GraphRAGStatus | undefined; graphStatusError: string | null; items: UploadBatchItemView[]; onCancelIngestJob: (jobId: string) => void; onClearUploadJobs: (itemIds: string[]) => void; onRetryIngestJob: (item: UploadBatchItemView) => void; retryingJobId: string | null };

type BatchUploadRowProps = Omit<BatchUploadStatusProps, "items"> & { item: UploadBatchItemView };

type UploadRowActionsProps = { canCancel: boolean; canRetry: boolean; canceling: boolean; item: UploadBatchItemView; onCancel: () => void; onClear: () => void; onRetry: () => void; retrying: boolean };
