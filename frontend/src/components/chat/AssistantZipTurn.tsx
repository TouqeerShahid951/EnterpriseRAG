import { Activity, AlertTriangle, Bot, CheckCircle2, Clock, Download, FileText, Presentation, File, GitBranch, Loader2, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";

import { queryApi } from "../../api/contracts";
import type { ArtifactJobSummary, Document, SourceAnchor } from "../../types/api";
import type { FaithfulnessStatus, GeneratedArtifact, QueryNodeTiming } from "../../types/query";
import type { ChatTurn } from "../../types/chat";
import { formatIntent, formatScore } from "../../utils/format";
import { sourceCitationLabel, sourceCitationName } from "../../utils/sourceCitation";
import { sourceDocumentTitle, withSourceDocumentTitle } from "../../utils/sourceDocument";
import { sourceMatchedSpanCount, sourceMatchedSpanLabel } from "../../utils/sourceEvidence";
import { sourcePageLabel } from "../../utils/sourcePage";
import { CitedAnswer } from "./CitedAnswer";

export function AssistantZipTurn({ documents, onCancelArtifactJob, onClarifyArtifactJob, onExpandSourceSearch, onRetryArtifactJob, onSelectSource, selectedSource, turn }: Props) {
  if (turn.status === "pending") return <PendingAssistant documents={documents} onSelectSource={onSelectSource} selectedSource={selectedSource} turn={turn} />;
  if (turn.status === "cancelled") return <StoppedAssistant documents={documents} onSelectSource={onSelectSource} turn={turn} />;
  if (turn.status === "error" || !turn.response) return <ErrorAssistant message={turn.errorMessage} />;

  const response = turn.response;
  const artifactJob = response.artifact_job ?? null;
  const headerBadge = artifactJob ? artifactJobBadgeFor(artifactJob) : faithfulnessBadgeFor(response.faithfulness_status, response.faithfulness_score);
  const artifacts = artifactJob?.artifacts.length ? artifactJob.artifacts : response.artifacts ?? [];
  return (
    <div className="rag-assistant-turn">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex items-center gap-1 text-label-md text-on-surface">
          <Bot size={18} className="text-primary" />
          Prudentia AI
        </span>
        <span className={`sv-pill ${headerBadge.className}`}>
          {headerBadge.icon}
          {headerBadge.label}
        </span>
        {artifactJob ? (
          <ArtifactJobElapsed job={artifactJob} fallbackCreatedAt={turn.createdAt} />
        ) : (
          <span className="text-label-md text-secondary">{formatLatencyMs(response.latency_ms)}</span>
        )}
      </div>
      <ResponseNotices
        degraded={response.degraded}
        degradedReason={response.degraded_reason}
        conflictFlag={response.conflict_flag}
        faithfulnessScore={response.faithfulness_score}
        faithfulnessStatus={response.faithfulness_status}
        unfoundedClaims={response.unfounded_claims}
      />
      {response.source_expansion?.available ? (
        <div className="rag-source-expansion">
          <AlertTriangle size={16} />
          <span>{response.source_expansion.reason || "The selected source could not answer this question."}</span>
          <button type="button" className="sv-action-secondary" onClick={() => onExpandSourceSearch?.(turn.id)}>
            <SearchAllIcon />
            Search all sources
          </button>
        </div>
      ) : null}
      <div className="rag-assistant-prose space-y-3 text-body-md text-on-surface">
        <CitedAnswer answer={response.answer} documents={documents} onSelectSource={onSelectSource} sources={response.sources} />
      </div>
      {artifactJob ? (
        <ArtifactJobPanel
          job={artifactJob}
          onCancel={onCancelArtifactJob}
          onClarify={onClarifyArtifactJob}
          onRetry={onRetryArtifactJob}
        />
      ) : artifacts.length > 0 ? (
        <ArtifactDownloads artifacts={artifacts} />
      ) : null}
      {response.node_timings?.length ? <NodeTimingsPanel timings={response.node_timings} /> : null}
      <div className="flex flex-wrap gap-2 border-t border-surface-border pt-3 text-label-md text-secondary">
        <span>{formatIntent(response.intent)}</span>
        {response.degraded ? <span className="text-warning-amber">Degraded</span> : null}
        {response.conflict_flag ? <span className="text-error-red">Conflict detected</span> : null}
      </div>
      <div className="flex flex-wrap gap-2">
        {response.sources.map((source, index) => (
          <SourceChip
            key={`${source.doc_id}-${source.chunk_id}-${index}`}
            documents={documents}
            onSelectSource={onSelectSource}
            selected={selectedSource?.doc_id === source.doc_id && selectedSource?.chunk_id === source.chunk_id}
            source={source}
            sourceNumber={index + 1}
          />
        ))}
      </div>
    </div>
  );
}

function SearchAllIcon() {
  return <GitBranch size={14} aria-hidden="true" />;
}

function NodeTimingsPanel({ timings }: { timings: QueryNodeTiming[] }) {
  const slowest = [...timings].sort((left, right) => right.duration_ms - left.duration_ms).slice(0, 3);
  return (
    <details className="rag-node-timings rounded border border-surface-border bg-surface-container-low px-3 py-2 text-label-md text-secondary">
      <summary className="cursor-pointer font-bold text-on-surface">Node timings - {formatNodeDurationMs(totalNodeDuration(timings))}</summary>
      <div className="mt-2 grid gap-2">
        <div className="flex flex-wrap gap-2">
          {slowest.map((timing, index) => (
            <span key={`${timing.node}-${index}`} className="sv-pill">
              {formatNodeLabel(timing.node)} {formatNodeDurationMs(timing.duration_ms)}
            </span>
          ))}
        </div>
        <div className="grid gap-1">
          {timings.map((timing, index) => (
            <div key={`${timing.node}-${index}`} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3">
              <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                {formatNodeLabel(timing.node)}
                {timing.execution_mode ? <span className="text-secondary"> - {timing.execution_mode}</span> : null}
                {timing.detail ? <span className="text-secondary"> - {timing.detail}</span> : null}
              </span>
              <span className="font-bold text-on-surface">{formatNodeDurationMs(timing.duration_ms)}</span>
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}

function totalNodeDuration(timings: QueryNodeTiming[]): number {
  return timings.reduce((total, timing) => total + Math.max(0, timing.duration_ms), 0);
}

function formatNodeLabel(node: string): string {
  return node.split("_").filter(Boolean).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

function formatNodeDurationMs(durationMs: number): string {
  if (!Number.isFinite(durationMs) || durationMs <= 0) return "0ms";
  if (durationMs < 1000) return `${Math.round(durationMs)}ms`;
  return `${(durationMs / 1000).toFixed(durationMs < 10000 ? 1 : 0)}s`;
}

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

function ArtifactJobPanel({ job, onCancel, onClarify, onRetry }: ArtifactJobPanelProps) {
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

function ArtifactJobElapsed({ fallbackCreatedAt, job }: { fallbackCreatedAt: string; job: ArtifactJobSummary }) {
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

function artifactJobBadgeFor(job: ArtifactJobSummary): { className: string; icon: ReactNode; label: string } {
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

function SourceChip({
  documents,
  onSelectSource,
  selected,
  source,
  sourceNumber,
}: {
  documents: Document[];
  onSelectSource: (source: SourceAnchor | null) => void;
  selected: boolean;
  source: SourceAnchor;
  sourceNumber: number | null;
}) {
  const pageLabel = sourcePageLabel(source);
  const title = sourceDocumentTitle(source, documents);
  const citationLabel = sourceCitationLabel(source);
  const sourceName = sourceCitationName(sourceNumber);
  const matchedSpanCount = sourceMatchedSpanCount(source);
  const matchedSpanLabel = sourceMatchedSpanLabel(source);
  const ariaDetails = [pageLabel, matchedSpanCount > 0 ? matchedSpanLabel : ""].filter(Boolean).join(", ");
  return (
    <button
      type="button"
      onClick={() => onSelectSource(withSourceDocumentTitle(source, documents))}
      className={`rag-source-chip ${selected ? "is-selected" : ""}`}
      aria-label={`Open ${sourceName}: ${title}${ariaDetails ? `, ${ariaDetails}` : ""}`}
      title={`${sourceName} - ${title}${pageLabel ? ` - ${pageLabel}` : ""} - ${citationLabel}`}
    >
      <FileText aria-hidden="true" size={15} />
      <span className="rag-source-chip-copy">
        <span className="rag-source-chip-title">{title}</span>
        <span className="rag-source-chip-meta">
          {pageLabel ? <span>{pageLabel}</span> : null}
          {matchedSpanCount > 0 ? <span>{matchedSpanLabel}</span> : null}
          <span className="rag-source-chip-label">{sourceName}</span>
        </span>
      </span>
    </button>
  );
}

function PendingAssistant({ documents, onSelectSource, selectedSource, turn }: Props) {
  const elapsedSeconds = useElapsedSeconds(turn.createdAt);
  const pendingSources = useMemo(() => uniqueProgressSources(turn.progress), [turn.progress]);
  const hasSources = pendingSources.length > 0;
  const hasDraft = Boolean(turn.streamText);
  const activeProgress = turn.progress.at(-1);

  return (
    <div className="rag-assistant-turn rag-assistant-turn-pending">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex items-center gap-1 text-label-md text-on-surface">
          <Bot size={18} className="text-primary" />
          Prudentia AI
        </span>
        <span className="rag-live-badge">
          <Activity size={14} />
          Running graph
        </span>
        <span className="rag-elapsed">
          <Clock size={13} />
          {formatElapsed(elapsedSeconds)}
        </span>
      </div>
      <div className="rag-live-panel" aria-busy="true" aria-live="polite">
        <div className="rag-live-summary">
          <div className="min-w-0">
            <p className="rag-live-eyebrow">Researching your question</p>
            <p className="rag-live-question">{turn.question}</p>
          </div>
          <QueryGraphPulse hasDraft={hasDraft} hasSources={hasSources} />
        </div>

        <div className="rag-progress-timeline" role="list" aria-label="RAG progress">
          {activeProgress ? (
            <div key={activeProgress.id} className={`rag-progress-item is-active ${activeProgress.kind ? `is-${activeProgress.kind}` : ""}`} role="listitem">
              <ProgressIcon active kind={activeProgress.kind} />
              <span className="rag-progress-copy">
                <span className="rag-progress-label">{activeProgress.label}</span>
                {activeProgress.detail ? <span className="rag-progress-detail">{activeProgress.detail}</span> : null}
              </span>
            </div>
          ) : null}
        </div>

        {hasSources ? (
          <div className="rag-pending-sources">
            <p className="rag-live-section-label">Evidence coming in</p>
            <div className="flex flex-wrap gap-2">
              {pendingSources.slice(0, 4).map((source, index) => (
                <SourceChip
                  key={`${source.doc_id}-${source.chunk_id}`}
                  documents={documents}
                  onSelectSource={onSelectSource}
                  selected={selectedSource?.doc_id === source.doc_id && selectedSource?.chunk_id === source.chunk_id}
                  source={source}
                  sourceNumber={index + 1}
                />
              ))}
            </div>
          </div>
        ) : null}

        {turn.streamText ? (
          <div className="rag-stream-preview">
            <p className="rag-live-section-label">Drafting cited answer</p>
            <div className="rag-stream-text">
              <CitedAnswer answer={turn.streamText} documents={documents} onSelectSource={onSelectSource} sources={pendingSources} />
            </div>
          </div>
        ) : (
          <AnswerSkeleton />
        )}
      </div>
    </div>
  );
}

function StoppedAssistant({ documents, onSelectSource, turn }: StoppedAssistantProps) {
  const partialSources = useMemo(() => uniqueProgressSources(turn.progress), [turn.progress]);

  return (
    <div className="rag-assistant-turn rag-assistant-turn-stopped">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex items-center gap-1 text-label-md text-on-surface">
          <Bot size={18} className="text-primary" />
          Prudentia AI
        </span>
        <span className="rag-stopped-badge">
          <AlertTriangle size={14} />
          Stopped
        </span>
      </div>
      <div className="rag-live-panel rag-stopped-panel">
        <div className="rag-live-summary">
          <div className="min-w-0">
            <p className="rag-live-eyebrow">Response stopped</p>
            <p className="rag-live-question">{turn.question}</p>
          </div>
        </div>
        {turn.streamText ? (
          <div className="rag-stream-preview">
            <p className="rag-live-section-label">Partial draft</p>
            <div className="rag-stream-text">
              <CitedAnswer answer={turn.streamText} documents={documents} onSelectSource={onSelectSource} sources={partialSources} />
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ProgressIcon({ active, kind }: { active: boolean; kind?: Extract<ChatTurn, { role: "assistant" }>["progress"][number]["kind"] }) {
  if (active) {
    return (
      <span className="rag-progress-dot is-active-dot" aria-hidden="true">
        <Loader2 size={13} />
      </span>
    );
  }
  if (kind === "warning") {
    return (
      <span className="rag-progress-dot is-warning-dot" aria-hidden="true">
        <AlertTriangle size={13} />
      </span>
    );
  }
  if (kind === "source") {
    return (
      <span className="rag-progress-dot is-source-dot" aria-hidden="true">
        <FileText size={13} />
      </span>
    );
  }
  if (kind === "intent") {
    return (
      <span className="rag-progress-dot" aria-hidden="true">
        <GitBranch size={13} />
      </span>
    );
  }
  return (
    <span className="rag-progress-dot" aria-hidden="true">
      <CheckCircle2 size={13} />
    </span>
  );
}

function QueryGraphPulse({ hasDraft, hasSources }: { hasDraft: boolean; hasSources: boolean }) {
  return (
    <div className="rag-mini-graph" aria-hidden="true">
      <span className="rag-graph-node is-complete">Query</span>
      <span className={`rag-graph-connector ${hasSources || hasDraft ? "is-complete" : "is-active"}`} />
      <span className={`rag-graph-node ${hasSources ? "is-complete" : "is-active"}`}>Evidence</span>
      <span className={`rag-graph-connector ${hasDraft ? "is-complete" : hasSources ? "is-active" : ""}`} />
      <span className={`rag-graph-node ${hasDraft ? "is-active" : ""}`}>Answer</span>
    </div>
  );
}

function AnswerSkeleton() {
  return (
    <div className="rag-answer-skeleton" aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
  );
}

function uniqueProgressSources(progress: Extract<ChatTurn, { role: "assistant" }>["progress"]): SourceAnchor[] {
  const seen = new Set<string>();
  const sources: SourceAnchor[] = [];
  for (const item of progress) {
    if (!item.source) continue;
    const key = `${item.source.doc_id}-${item.source.chunk_id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    sources.push(item.source);
  }
  return sources;
}

function useElapsedSeconds(createdAt: string): number {
  const [elapsedSeconds, setElapsedSeconds] = useState(() => secondsSince(createdAt));

  useEffect(() => {
    setElapsedSeconds(secondsSince(createdAt));
    const timer = window.setInterval(() => {
      setElapsedSeconds(secondsSince(createdAt));
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, [createdAt]);

  return elapsedSeconds;
}

function secondsSince(createdAt: string): number {
  const createdTime = new Date(createdAt).getTime();
  if (Number.isNaN(createdTime)) return 0;
  return Math.max(0, Math.floor((Date.now() - createdTime) / 1000));
}

function secondsBetween(startedAt: string, endedAt: string): number {
  const startedTime = new Date(startedAt).getTime();
  const endedTime = new Date(endedAt).getTime();
  if (Number.isNaN(startedTime) || Number.isNaN(endedTime)) return 0;
  return Math.max(0, Math.floor((endedTime - startedTime) / 1000));
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}m ${remainder}s`;
}

function formatLatencyMs(latencyMs: number): string {
  if (!Number.isFinite(latencyMs) || latencyMs <= 0) return "0s";
  return formatElapsed(Math.max(1, Math.round(latencyMs / 1000)));
}

function hasLowFaithfulness(status: FaithfulnessStatus, score: number): boolean {
  return status === "checked" && score < 0.8;
}

function faithfulnessBadgeFor(status: FaithfulnessStatus, score: number): { className: string; icon: ReactNode; label: string } {
  if (status === "pending") {
    return { className: "", icon: <Clock size={14} />, label: "Checking grounding" };
  }
  if (status === "skipped") {
    return { className: "", icon: <Clock size={14} />, label: "Grounding not checked" };
  }
  if (status === "failed") {
    return { className: "sv-pill-warning", icon: <AlertTriangle size={14} />, label: "Grounding check failed" };
  }
  if (score < 0.8) {
    return { className: "sv-pill-warning", icon: <AlertTriangle size={14} />, label: `${formatScore(score)} faithfulness` };
  }
  return { className: "sv-pill-success", icon: <CheckCircle2 size={14} />, label: `${formatScore(score)} faithfulness` };
}

function ResponseNotices({ conflictFlag, degraded, degradedReason, faithfulnessScore, faithfulnessStatus, unfoundedClaims }: NoticeProps) {
  const lowFaithfulness = hasLowFaithfulness(faithfulnessStatus, faithfulnessScore);
  const faithfulnessFailed = faithfulnessStatus === "failed";
  if (!conflictFlag && !degraded && !lowFaithfulness && !faithfulnessFailed) return null;
  return (
    <div className="grid gap-2">
      {conflictFlag ? (
        <Notice icon={<ShieldAlert size={16} />} tone="error" text="The indexed sources conflict. Inspect the cited evidence before using this answer." />
      ) : null}
      {faithfulnessFailed ? (
        <Notice icon={<AlertTriangle size={16} />} tone="warning" text="Grounding check failed before it could score this answer. Inspect the cited evidence before using it." />
      ) : null}
      {lowFaithfulness ? (
        <Notice icon={<AlertTriangle size={16} />} tone="warning" text={faithfulnessNoticeText(faithfulnessScore, unfoundedClaims)} />
      ) : null}
      {degraded && !faithfulnessFailed ? (
        <Notice icon={<AlertTriangle size={16} />} tone="warning" text={`Response is degraded${degradedReason ? `: ${degradedReason}` : "."}`} />
      ) : null}
    </div>
  );
}

function faithfulnessNoticeText(score: number, claims: string[]): string {
  const prefix = `Faithfulness is low (${formatScore(score)}).`;
  const visibleClaims = claims.filter(Boolean).slice(0, 3);
  return visibleClaims.length ? `${prefix} Unsupported: ${visibleClaims.join("; ")}` : `${prefix} Inspect the cited evidence before using this answer.`;
}

function Notice({ icon, text, tone }: { icon: ReactNode; text: string; tone: "error" | "warning" }) {
  const className = tone === "error" ? "border-error-red/25 bg-error-container text-error-red" : "border-warning-amber/25 bg-warning-amber/10 text-warning-amber";
  return <div className={`flex items-start gap-2 rounded border p-3 text-body-md ${className}`}><span className="mt-0.5">{icon}</span><span>{text}</span></div>;
}

function ErrorAssistant({ message }: { message?: string }) {
  return <div className="rag-assistant-error rounded-lg border border-error-red/20 bg-error-container p-4 text-body-md text-error-red">{message ?? "Query failed."}</div>;
}

type Props = {
  documents: Document[];
  onCancelArtifactJob?: (jobId: string) => Promise<void>;
  onClarifyArtifactJob?: (jobId: string, answers: Record<string, string>) => Promise<void>;
  onExpandSourceSearch?: (assistantTurnId: string) => void;
  onRetryArtifactJob?: (jobId: string) => Promise<void>;
  onSelectSource: (source: SourceAnchor | null) => void;
  selectedSource: SourceAnchor | null;
  turn: Extract<ChatTurn, { role: "assistant" }>;
};

type StoppedAssistantProps = {
  documents: Document[];
  onSelectSource: (source: SourceAnchor | null) => void;
  turn: Extract<ChatTurn, { role: "assistant" }>;
};

type ArtifactJobPanelProps = {
  job: ArtifactJobSummary;
  onCancel?: (jobId: string) => Promise<void>;
  onClarify?: (jobId: string, answers: Record<string, string>) => Promise<void>;
  onRetry?: (jobId: string) => Promise<void>;
};

type NoticeProps = {
  conflictFlag: boolean;
  degraded: boolean;
  degradedReason: string | null;
  faithfulnessScore: number;
  faithfulnessStatus: FaithfulnessStatus;
  unfoundedClaims: string[];
};
