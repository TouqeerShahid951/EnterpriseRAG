import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Download, File, FileText, Loader2, Presentation } from "lucide-react";
import { queryApi } from "@/lib/api/contracts";
import type { ArtifactJobSummary } from "@/types/api";
import type { GeneratedArtifact } from "@/types/query";
import { formatElapsed, secondsBetween, useElapsedSeconds } from "@/features/chat/utils/assistantTiming";

export function ArtifactDownloads({ artifacts }: { artifacts: GeneratedArtifact[] }) {
  return (
    <div className="rag-artifact-list" aria-label="Generated files">
      {artifacts.map((artifact) => {
        let Icon = FileText;
        if (artifact.format === "pptx") Icon = Presentation;
        else if (artifact.format === "pdf") Icon = File;

        return (
          <a
            key={artifact.id}
            href={queryApi.artifactContentUrl(artifact)}
            download={artifact.filename}
            className="rag-artifact-download"
            aria-label={`Download ${artifact.filename}`}
            title={`Download ${artifact.filename}`}
          >
            <Icon size={16} aria-hidden="true" />
            <span className="rag-artifact-copy">
              <strong>{artifact.filename}</strong>
              <small>{artifact.format.toUpperCase()} - {formatArtifactSize(artifact.size_bytes)}</small>
            </span>
            <Download size={15} aria-hidden="true" />
          </a>
        );
      })}
    </div>
  );
}

export function ArtifactJobPanel({ job, onCancel, onClarify, onRetry }: ArtifactJobPanelProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [pendingAction, setPendingAction] = useState<"cancel" | "clarify" | "retry" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const progressPct = Math.max(0, Math.min(100, job.progress_pct));
  const isTerminal = isArtifactJobTerminal(job.status);
  const isWaiting = job.status === "needs_input";
  const canCancel = !isTerminal && !isWaiting && Boolean(onCancel);
  const canRetry = (job.status === "failed" || job.status === "partial" || job.status === "cancelled") && Boolean(onRetry);
  const questions = job.clarification_questions ?? [];
  const formats = job.requested_formats.map((format) => format.toUpperCase()).join(", ");
  const stageLabel = job.stage_label?.trim() || artifactJobStatusLabel(job.status);
  const stageDetail = job.stage_detail?.trim() || artifactJobStageLabel(job);
  const stageProgressLabel = job.stage_progress?.label?.trim() || formatArtifactStageProgress(job);

  useEffect(() => {
    setAnswers({});
    setActionError(null);
  }, [job.id, questions.join("|")]);

  async function runAction(action: "cancel" | "clarify" | "retry", callback: () => Promise<void>) {
    setPendingAction(action);
    setActionError(null);
    try {
      await callback();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Artifact job action failed.");
    } finally {
      setPendingAction(null);
    }
  }

  function submitClarifications(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!onClarify) return;
    const payload = Object.fromEntries(
      questions
        .map((question) => [question, answers[question]?.trim() ?? ""] as const)
        .filter(([, answer]) => answer.length > 0),
    );
    if (Object.keys(payload).length === 0) {
      setActionError("Answer at least one clarification question.");
      return;
    }
    void runAction("clarify", () => onClarify(job.id, payload));
  }

  return (
    <section className={`rag-artifact-job-panel is-${artifactJobTone(job.status)}`} aria-live={isTerminal ? "off" : "polite"}>
      <div className="rag-artifact-job-header">
        <div>
          <p className="rag-live-eyebrow">Document generation</p>
          <h3>{stageLabel}</h3>
          <p>{stageDetail}{formats ? ` - ${formats}` : ""}</p>
        </div>
        <span className="sv-pill">
          {artifactJobIcon(job.status)}
          {progressPct}%
        </span>
      </div>

      <div className="rag-artifact-job-progress" role="progressbar" aria-label="Document generation progress" aria-valuemax={100} aria-valuemin={0} aria-valuenow={progressPct}>
        <span style={{ width: `${progressPct}%` }} />
      </div>
      {stageProgressLabel ? <p className="rag-artifact-job-stage-progress">{stageProgressLabel}</p> : null}

      {job.error_message ? <p className="rag-artifact-job-message is-error">{job.error_message}</p> : null}
      {actionError ? <p className="rag-artifact-job-message is-error">{actionError}</p> : null}

      {job.artifacts.length > 0 ? <ArtifactDownloads artifacts={job.artifacts} /> : null}

      {isWaiting && questions.length > 0 ? (
        <form className="rag-artifact-clarifications" onSubmit={submitClarifications}>
          <p className="rag-live-section-label">Planner needs clarification</p>
          {questions.map((question) => (
            <label key={question}>
              <span>{question}</span>
              <textarea
                value={answers[question] ?? ""}
                onChange={(event) => setAnswers((current) => ({ ...current, [question]: event.target.value }))}
                rows={2}
              />
            </label>
          ))}
          <button type="submit" className="sv-action-primary" disabled={pendingAction === "clarify"}>
            {pendingAction === "clarify" ? "Submitting..." : "Submit answers"}
          </button>
        </form>
      ) : null}

      <div className="rag-artifact-job-actions">
        {canCancel ? (
          <button type="button" className="sv-action-secondary" disabled={pendingAction === "cancel"} onClick={() => onCancel && void runAction("cancel", () => onCancel(job.id))}>
            {pendingAction === "cancel" ? "Cancelling..." : "Cancel generation"}
          </button>
        ) : null}
        {canRetry ? (
          <button type="button" className="sv-action-secondary" disabled={pendingAction === "retry"} onClick={() => onRetry && void runAction("retry", () => onRetry(job.id))}>
            {pendingAction === "retry" ? "Retrying..." : "Retry generation"}
          </button>
        ) : null}
      </div>
    </section>
  );
}

function formatArtifactSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function ArtifactJobElapsed({ fallbackCreatedAt, job }: { fallbackCreatedAt: string; job: ArtifactJobSummary }) {
  const startedAt = artifactJobElapsedStart(job, fallbackCreatedAt);
  const liveElapsedSeconds = useElapsedSeconds(startedAt);
  const elapsedSeconds = isArtifactJobTerminal(job.status)
    ? secondsBetween(startedAt, artifactJobElapsedEnd(job, startedAt))
    : liveElapsedSeconds;

  return (
    <span className="text-label-md text-secondary" aria-label="Document generation elapsed time">
      {formatElapsed(elapsedSeconds)}
    </span>
  );
}

function artifactJobElapsedStart(job: ArtifactJobSummary, fallbackCreatedAt: string): string {
  if (job.started_at) return job.started_at;
  if (job.status === "queued" && job.updated_at) return job.updated_at;
  return job.created_at ?? fallbackCreatedAt;
}

function artifactJobElapsedEnd(job: ArtifactJobSummary, startedAt: string): string {
  return job.completed_at ?? job.updated_at ?? startedAt;
}

function artifactJobStatusLabel(status: ArtifactJobSummary["status"]): string {
  const labels: Record<ArtifactJobSummary["status"], string> = {
    queued: "Queued",
    planning: "Planning document",
    needs_input: "Needs input",
    retrieving: "Retrieving evidence",
    composing: "Composing content",
    validating: "Validating grounding",
    rendering: "Rendering files",
    complete: "Complete",
    partial: "Partially complete",
    failed: "Failed",
    cancelled: "Cancelled",
  };
  return labels[status];
}

function artifactJobStageLabel(job: ArtifactJobSummary): string {
  if (!job.stage) return artifactJobStatusLabel(job.status);
  const composingMatch = job.stage.match(/^composing_(\d+)_of_(\d+)(?:_(batch|direct))?$/);
  if (composingMatch) {
    const [, completed, total, mode] = composingMatch;
    return mode === "direct"
      ? `Composing ${completed}/${total} - Direct evidence`
      : `Composing ${completed}/${total}`;
  }
  return job.stage
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatArtifactStageProgress(job: ArtifactJobSummary): string | null {
  const progress = job.stage_progress;
  if (!progress || progress.total <= 0) return null;
  const unit = progress.unit === "batches" ? "Batch" : progress.unit.slice(0, -1).replace(/^\w/, (char) => char.toUpperCase());
  return `${unit} ${progress.current} of ${progress.total}`;
}

function artifactJobTone(status: ArtifactJobSummary["status"]): "pending" | "success" | "warning" | "error" {
  if (status === "complete") return "success";
  if (status === "failed" || status === "cancelled") return "error";
  if (status === "partial" || status === "needs_input") return "warning";
  return "pending";
}

function artifactJobIcon(status: ArtifactJobSummary["status"]): ReactNode {
  if (status === "complete") return <CheckCircle2 size={14} />;
  if (status === "failed" || status === "cancelled" || status === "partial" || status === "needs_input") {
    return <AlertTriangle size={14} />;
  }
  return <Loader2 size={14} className="animate-spin" />;
}

export function artifactJobBadgeFor(job: ArtifactJobSummary): { className: string; icon: ReactNode; label: string } {
  const tone = artifactJobTone(job.status);
  return {
    className: tone === "warning" || tone === "error" ? "sv-pill-warning" : "",
    icon: artifactJobIcon(job.status),
    label: artifactJobStatusLabel(job.status),
  };
}

function isArtifactJobTerminal(status: ArtifactJobSummary["status"]): boolean {
  return status === "complete" || status === "partial" || status === "failed" || status === "cancelled";
}

export type ArtifactJobPanelProps = {
  job: ArtifactJobSummary;
  onCancel?: (jobId: string) => Promise<void>;
  onClarify?: (jobId: string, answers: Record<string, string>) => Promise<void>;
  onRetry?: (jobId: string) => Promise<void>;
};
