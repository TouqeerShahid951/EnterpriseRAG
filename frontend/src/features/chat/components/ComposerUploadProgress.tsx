import { AlertTriangle, CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import type { GraphRAGStatus } from "@/types/api";
import type { UploadJobView } from "@/types/chat";
import {
  formatSecondaryStageProgress,
  graphEnrichmentForJob,
  type GraphEnrichmentChip as GraphEnrichmentChipShape,
} from "@/features/upload/state/uploadJobProgress";

export function ComposerUploadProgress({ fileName, graphStatus, graphStatusError, job, pollError, space }: { fileName: string; graphStatus: GraphRAGStatus | undefined; graphStatusError: string | null; job: UploadJobView; pollError: string | null; space: string | null }) {
  const progressPct = Math.max(0, Math.min(100, job.progressPct));
  const stageProgress = formatSecondaryStageProgress(job.stageProgress, job.stageDetail);
  const graphChip = graphEnrichmentForJob(job, graphStatus, graphStatusError);
  const Icon = composerUploadIcon(job);
  const tone = composerUploadTone(job.status);
  const live = job.status === "queued" || job.status === "processing" ? "polite" : "off";
  return (
    <div className={`rag-composer-upload-status is-${tone}`} aria-live={live} role="status">
      <div className="rag-composer-upload-summary">
        <Icon className={job.status === "queued" || job.status === "processing" ? "animate-spin" : ""} size={16} />
        <div className="rag-composer-upload-copy">
          <div className="rag-composer-upload-title">
            <strong>{uploadStateLabel(job.status)}</strong>
            <span>{fileName}</span>
          </div>
          <p>{job.stageLabel}{space ? ` in ${space}` : ""}</p>
          <small>{job.stageDetail}</small>
          {stageProgress ? <small className="rag-composer-upload-stage-progress">{stageProgress}</small> : null}
          {graphChip ? <ComposerGraphEnrichmentChip chip={graphChip} /> : null}
        </div>
        <span className="rag-composer-upload-percent">{progressPct}%</span>
      </div>
      <div className="rag-composer-upload-progress" aria-label="Upload indexing progress" aria-valuemax={100} aria-valuemin={0} aria-valuenow={progressPct} role="progressbar">
        <span style={{ width: `${progressPct}%` }} />
      </div>
      <ol className="rag-composer-upload-steps" aria-label="Ingestion step status">
        {job.steps.map((step) => (
          <li key={step.id} className={`is-${step.state}`}>
            {composerStepIcon(step.state)}
            <span>{step.label}</span>
          </li>
        ))}
      </ol>
      {job.errorCode || job.errorMessage || pollError ? (
        <p className="rag-composer-upload-error">
          {job.errorCode ? <strong>{job.errorCode}: </strong> : null}
          {job.errorMessage ?? pollError}
        </p>
      ) : null}
    </div>
  );
}

function ComposerGraphEnrichmentChip({ chip }: { chip: GraphEnrichmentChipShape }) {
  const className = chip.state === "unavailable" ? "is-warning" : "is-active";
  return (
    <small className={`rag-composer-upload-graph ${className}`}>
      {chip.state === "unavailable" ? <AlertTriangle size={11} /> : <Circle className={chip.state === "running" ? "animate-pulse" : ""} fill="currentColor" size={9} />}
      <span>{chip.label}</span>
      {chip.detail ? <span>{chip.detail}</span> : null}
    </small>
  );
}

function composerUploadIcon(job: UploadJobView) {
  if (job.status === "complete") return CheckCircle2;
  if (job.status === "failed") return XCircle;
  if (job.status === "cancelled") return XCircle;
  if (job.status === "human_review") return AlertTriangle;
  return Loader2;
}

function composerStepIcon(state: UploadJobView["steps"][number]["state"]) {
  if (state === "complete") return <CheckCircle2 aria-hidden="true" size={12} />;
  if (state === "failed") return <XCircle aria-hidden="true" size={12} />;
  if (state === "cancelled") return <XCircle aria-hidden="true" size={12} />;
  if (state === "needs_review") return <AlertTriangle aria-hidden="true" size={12} />;
  if (state === "active") return <Loader2 aria-hidden="true" className="animate-spin" size={12} />;
  return <Circle aria-hidden="true" size={12} />;
}

function composerUploadTone(status: UploadJobView["status"]) {
  if (status === "complete") return "success";
  if (status === "failed") return "error";
  if (status === "cancelled") return "warning";
  if (status === "human_review") return "warning";
  return "pending";
}

function uploadStateLabel(status: UploadJobView["status"]) {
  if (status === "complete") return "Completed";
  if (status === "failed") return "Failed";
  if (status === "cancelled") return "Cancelled";
  if (status === "human_review") return "Needs review";
  return status.charAt(0).toUpperCase() + status.slice(1);
}
