import { AlertTriangle, Bot, GitBranch } from "lucide-react";
import type { QueryNodeTiming } from "@/types/query";
import { formatIntent } from "@/lib/utils/format";
import { CitedAnswer } from "./CitedAnswer";
import type { Props } from "@/features/chat/types/assistantTurnTypes";
import { formatLatencyMs } from "@/features/chat/utils/assistantTiming";
import { SourceChip } from "@/features/chat/components/AssistantSourceChip";
import {
  ArtifactDownloads,
  ArtifactJobElapsed,
  ArtifactJobPanel,
  artifactJobBadgeFor,
} from "@/features/chat/components/AssistantArtifactJob";
import { PendingAssistant, StoppedAssistant } from "@/features/chat/components/AssistantProgress";
import {
  ErrorAssistant,
  ResponseNotices,
  faithfulnessBadgeFor,
} from "@/features/chat/components/AssistantResponseNotices";


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
            <div key={`${timing.node}-${index}`} className="grid gap-1">
              <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-3">
                <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                  {formatNodeLabel(timing.node)}
                  {timing.execution_mode ? <span className="text-secondary"> - {timing.execution_mode}</span> : null}
                  {timing.detail ? <span className="text-secondary"> - {timing.detail}</span> : null}
                </span>
                <span className="font-bold text-on-surface">{formatNodeDurationMs(timing.duration_ms)}</span>
              </div>
              {Object.entries(timing.phase_timings_ms ?? {}).map(([phase, durationMs]) => (
                <div key={phase} className="ml-4 grid grid-cols-[minmax(0,1fr)_auto] gap-3 text-secondary">
                  <span>{formatNodeLabel(phase)}</span>
                  <span>{formatNodeDurationMs(durationMs)}</span>
                </div>
              ))}
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
