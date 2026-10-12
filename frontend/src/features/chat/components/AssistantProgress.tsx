import { useMemo } from "react";
import { Activity, AlertTriangle, Bot, CheckCircle2, Clock, FileText, GitBranch, Loader2 } from "lucide-react";
import { SourceChip } from "@/features/chat/components/AssistantSourceChip";
import { CitedAnswer } from "@/features/chat/components/CitedAnswer";
import { useBranding } from "@/components/brand/BrandContext";
import { formatElapsed, useElapsedSeconds } from "@/features/chat/utils/assistantTiming";
import { groupSourcesByDocument, sourcesForTurn } from "@/features/chat/utils/sourceGroups";
import type { Props } from "@/features/chat/types/assistantTurnTypes";
import type { Document, SourceAnchor } from "@/types/api";
import type { ChatTurn } from "@/types/chat";

export function PendingAssistant({ documents, onSelectSource, selectedSource, turn }: Props) {
  const branding = useBranding();
  const elapsedSeconds = useElapsedSeconds(turn.createdAt);
  const pendingSources = useMemo(() => sourcesForTurn(turn), [turn]);
  const pendingSourceGroups = useMemo(() => groupSourcesByDocument(pendingSources), [pendingSources]);
  const hasSources = pendingSources.length > 0;
  const hasDraft = Boolean(turn.streamText);
  const activeProgress = turn.progress.at(-1);

  return (
    <div className="rag-assistant-turn rag-assistant-turn-pending">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex items-center gap-1 text-label-md text-on-surface">
          <Bot size={18} className="text-primary" />
          {branding.app_name}
        </span>
        <span className="rag-live-badge" role="status">
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
              {pendingSourceGroups.slice(0, 4).map((group) => (
                <SourceChip
                  key={group.docId}
                  documents={documents}
                  group={group}
                  onSelectSource={onSelectSource}
                  selected={selectedSource?.doc_id === group.docId}
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

export function StoppedAssistant({ documents, onSelectSource, turn }: StoppedAssistantProps) {
  const branding = useBranding();
  const partialSources = useMemo(() => sourcesForTurn(turn), [turn]);

  return (
    <div className="rag-assistant-turn rag-assistant-turn-stopped">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex items-center gap-1 text-label-md text-on-surface">
          <Bot size={18} className="text-primary" />
          {branding.app_name}
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
        <span className="rag-progress-icon">
          <Loader2 className="rag-progress-icon-spinner" size={13} />
          <Activity className="rag-progress-icon-static" size={13} />
        </span>
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

export type StoppedAssistantProps = {
  documents: Document[];
  onSelectSource: (source: SourceAnchor | null) => void;
  turn: Extract<ChatTurn, { role: "assistant" }>;
};
