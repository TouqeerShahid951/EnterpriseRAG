import { Activity, AlertTriangle, CheckCircle2, Clock3, Info, Loader2, ShieldCheck, XCircle, type LucideIcon } from "lucide-react";

import { EmptyPanel, InlineMessage } from "@/components/layout/Common";
import { formatIntent } from "@/lib/utils/format";
import {
  formatDurationMs,
  sourceDetail,
  type QueryTrackerTimelineItem,
} from "../queryTrackerState";
import type { QueryTrackerResultsViewModel } from "./useQueryTrackerController";

export function QueryTrackerResults({ model }: { model: QueryTrackerResultsViewModel }) {
  const { finalResponse, runtime, slowTimings, state } = model;

  return (
    <>
      <section className="sv-panel rag-eval-tracker-status">
        <TrackerFact icon={ShieldCheck} label="Trace" value={state.traceId ?? "Not started"} />
        <TrackerFact icon={Activity} label="Session" value={state.sessionId ?? "Created on completion"} />
        <TrackerFact icon={Info} label="Intent" value={state.intent ? formatIntent(state.intent) : "Pending"} />
        <TrackerFact icon={Clock3} label="Runtime" value={runtime} />
      </section>

      <div className="rag-eval-tracker-grid">
        <section className="sv-panel rag-eval-tracker-timeline-panel">
          <div className="rag-eval-section-header">
            <div>
              <h2 className="sv-section-title">System Trace</h2>
              <p>{state.timeline.length ? `${state.timeline.length} streamed events` : "Graph activity will appear here."}</p>
            </div>
          </div>
          {state.timeline.length === 0 ? (
            <div className="p-5"><EmptyPanel>Run a tracker query to see retrieval, ranking, synthesis, and verification steps.</EmptyPanel></div>
          ) : (
            <div className="rag-eval-tracker-timeline" role="list">
              {state.timeline.map((item) => <TimelineRow key={item.id} item={item} />)}
            </div>
          )}
        </section>

        <section className="sv-panel rag-eval-tracker-answer-panel">
          <div className="rag-eval-section-header">
            <div>
              <h2 className="sv-section-title">Answer Stream</h2>
              <p>{finalResponse ? finalResponse.faithfulness_status : "Tokens and final response."}</p>
            </div>
            {finalResponse ? <span className="sv-pill">{Math.round(finalResponse.faithfulness_score * 100)}% grounded</span> : null}
          </div>
          <div className="rag-eval-tracker-answer-body">
            {state.errorMessage ? <InlineMessage tone="error">{state.errorMessage}</InlineMessage> : null}
            {state.warnings.length > 0 ? (
              <div className="rag-eval-tracker-warning-list">
                {state.warnings.map((warning, index) => (
                  <span key={`${warning}-${index}`}><AlertTriangle size={14} /> {warning}</span>
                ))}
              </div>
            ) : null}
            {state.answerText ? (
              <p className="rag-eval-answer rag-eval-tracker-answer">{state.answerText}</p>
            ) : (
              <EmptyPanel>Answer tokens will stream here while the graph runs.</EmptyPanel>
            )}
          </div>
        </section>
      </div>

      <div className="rag-eval-tracker-detail-grid">
        <section className="sv-panel rag-eval-tracker-sources-panel">
          <div className="rag-eval-section-header">
            <div>
              <h2 className="sv-section-title">Sources</h2>
              <p>{state.sources.length ? `${state.sources.length} returned` : "Retrieved evidence anchors."}</p>
            </div>
          </div>
          {state.sources.length === 0 ? (
            <div className="p-5"><EmptyPanel>No sources have been streamed yet.</EmptyPanel></div>
          ) : (
            <div className="rag-eval-tracker-source-list">
              {state.sources.map((source, index) => (
                <article key={`${source.doc_id}-${source.chunk_id}-${index}`}>
                  <strong>{sourceDetail(source)}</strong>
                  <small>{source.group_path} / {source.clearance_level}</small>
                  <p>{source.excerpt}</p>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="sv-panel rag-eval-tracker-timings-panel">
          <div className="rag-eval-section-header">
            <div>
              <h2 className="sv-section-title">Node Timings</h2>
              <p>{slowTimings.length ? "Slowest completed graph steps." : "Available when the response completes."}</p>
            </div>
          </div>
          {slowTimings.length === 0 ? (
            <div className="p-5"><EmptyPanel>Node timings arrive with the final response.</EmptyPanel></div>
          ) : (
            <div className="rag-eval-tracker-timing-list">
              {slowTimings.map((timing) => (
                <div key={`${timing.node}-${timing.duration_ms}`}>
                  <span>{formatDurationMs(timing.duration_ms)}</span>
                  <strong>{timing.node}</strong>
                  <small>{timing.execution_mode ?? "mode unavailable"}{timing.detail ? ` / ${timing.detail}` : ""}</small>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </>
  );
}

function TimelineRow({ item }: { item: QueryTrackerTimelineItem }) {
  const Icon = item.status === "error" ? XCircle : item.status === "warning" ? AlertTriangle : item.status === "running" ? Loader2 : CheckCircle2;
  return (
    <div className="rag-eval-tracker-timeline-row" data-status={item.status} role="listitem">
      <span className="rag-eval-tracker-timeline-icon">
        <Icon className={item.status === "running" ? "animate-spin" : ""} size={15} />
      </span>
      <div>
        <strong>{item.label}</strong>
        {item.detail ? <small>{item.detail}</small> : null}
      </div>
      <span className="rag-eval-tracker-timeline-meta">{formatDurationMs(item.durationMs)}</span>
    </div>
  );
}

function TrackerFact({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="rag-eval-tracker-fact">
      <Icon size={15} />
      <span>
        <small>{label}</small>
        <strong>{value}</strong>
      </span>
    </div>
  );
}
