import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Clock3,
  Database,
  FileCheck2,
  Loader2,
  Route,
  ShieldCheck,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { EmptyPanel, InlineMessage } from "@/components/layout/Common";
import { formatIntent } from "@/lib/utils/format";
import { formatDurationMs, sourceDetail, type QueryTrackerTimelineItem } from "../queryTrackerState";
import type { QueryTrackerResultsViewModel } from "./useQueryTrackerController";
import { ChunkPreview } from "./ChunkPreview";
import { RetrievalStages } from "./RetrievalStages";

type PipelineStatus = "complete" | "error" | "pending" | "running";

interface PipelineStage {
  detail: string;
  label: string;
  status: PipelineStatus;
}

export function QueryTrackerResults({ model }: { model: QueryTrackerResultsViewModel }) {
  const { finalResponse, onChooseQuerySource, onExpandSourceSearch, runtime, slowTimings, state } = model;
  const retrieved = state.retrievalStages.find((stage) => stage.name === "retrieved")?.candidate_count ?? 0;
  const accepted = [...state.retrievalStages].reverse().find((stage) => stage.name === "final_evidence")?.candidate_count ?? 0;
  const pipeline = pipelineStages(model);
  const runStatus = state.errorMessage ? "Failed" : state.completedAt ? (state.answerText ? "Answered" : "No answer") : state.startedAt ? "Running" : "Ready";

  return (
    <>
      <section className="sv-panel rag-eval-tracker-status" aria-label="Query run summary">
        <TrackerFact icon={Activity} label="Status" value={runStatus} />
        <TrackerFact icon={Route} label="Intent" value={state.intent ? formatIntent(state.intent) : "Pending"} />
        <TrackerFact icon={Clock3} label="Runtime" value={runtime} />
        <TrackerFact icon={Database} label="Retrieved" value={`${retrieved} candidates`} />
        <TrackerFact icon={FileCheck2} label="Accepted" value={`${accepted} chunks`} />
        <TrackerFact icon={ShieldCheck} label="Groundedness" value={finalResponse ? `${Math.round(finalResponse.faithfulness_score * 100)}%` : "Pending"} />
      </section>

      <section className="sv-panel rag-eval-pipeline-overview">
        <div className="rag-eval-section-header">
          <div>
            <h2 className="sv-section-title">Pipeline overview</h2>
            <p>Follow the query from routing through verification.</p>
          </div>
        </div>
        <div className="rag-eval-pipeline-track" role="list" aria-label="RAG pipeline stages">
          {pipeline.map((stage) => <PipelineStep key={stage.label} stage={stage} />)}
        </div>
        {state.errorMessage ? (
          <div className="rag-eval-tracker-failure" role="alert">
            <XCircle size={17} />
            <span><strong>Query failed</strong>{state.errorMessage}</span>
          </div>
        ) : state.warnings.length ? (
          <div className="rag-eval-tracker-warning" role="status">
            <AlertTriangle size={17} />
            <span><strong>Review recommended</strong>{state.warnings[0]}</span>
          </div>
        ) : null}
      </section>

      <section className="sv-panel rag-eval-tracker-workbench">
        <div className="rag-eval-tracker-trace-pane">
          <PaneHeader title="Stage details" detail={state.timeline.length ? `${state.timeline.length} streamed events` : "Waiting for a run"} />
          {state.timeline.length === 0 ? (
            <div className="rag-eval-pane-empty"><EmptyPanel>Run a query to inspect each graph step.</EmptyPanel></div>
          ) : (
            <div className="rag-eval-tracker-timeline" role="list">
              {state.timeline.map((item) => <TimelineRow key={item.id} item={item} />)}
            </div>
          )}
        </div>

        <div className="rag-eval-tracker-evidence-pane">
          <PaneHeader
            title="Retrieved evidence"
            detail={state.retrievalStages.length ? `${state.retrievalStages.length} stage snapshots, ${state.sources.length} cited` : "Candidates appear after each retrieval stage"}
          />
          {state.retrievalStages.length === 0 && state.sources.length === 0 ? (
            <div className="rag-eval-pane-empty"><EmptyPanel>No retrieval evidence has streamed yet.</EmptyPanel></div>
          ) : (
            <>
              <RetrievalStages stages={state.retrievalStages} />
              {state.sources.length ? (
                <div className="rag-eval-final-sources">
                  <h3>Final cited sources</h3>
                  <div className="rag-eval-tracker-source-list">
                    {state.sources.map((source, index) => (
                      <article key={`${source.doc_id}-${source.chunk_id}-${index}`}>
                        <strong>{sourceDetail(source)}</strong>
                        <small>{source.group_path} / {source.clearance_level}</small>
                        <ChunkPreview chunkId={source.chunk_id} excerpt={source.excerpt} />
                      </article>
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          )}
        </div>

        <div className="rag-eval-tracker-answer-pane">
          <PaneHeader title="Answer" detail={finalResponse?.faithfulness_status ?? (state.completedAt ? "Complete" : "Live output")} />
          <div className="rag-eval-tracker-answer-body">
            {state.errorMessage ? <InlineMessage tone="error">{state.errorMessage}</InlineMessage> : null}
            {state.warnings.length > 1 ? (
              <div className="rag-eval-tracker-warning-list">
                {state.warnings.slice(1).map((warning, index) => (
                  <span key={`${warning}-${index}`}><AlertTriangle size={14} /> {warning}</span>
                ))}
              </div>
            ) : null}
            {state.answerText ? (
              <p className="rag-eval-answer rag-eval-tracker-answer">{state.answerText}</p>
            ) : (
              <div className="rag-eval-answer-empty">
                <CircleDashed size={24} />
                <strong>{state.completedAt ? "No answer generated" : "Waiting for generation"}</strong>
                <p>{state.completedAt ? "Inspect the evidence stages and warnings to see where the run stopped." : "Answer tokens will appear here when generation begins."}</p>
              </div>
            )}
          </div>
        </div>
      </section>

      {finalResponse ? (
        <section className="sv-panel rag-eval-tracker-diagnostics" aria-labelledby="query-tracker-diagnostics-title">
          <div className="rag-eval-section-header">
            <div>
              <h2 id="query-tracker-diagnostics-title" className="sv-section-title">Query outcome</h2>
              <p>Routing decisions, coverage, and recoverable source actions.</p>
            </div>
          </div>
          <dl className="rag-eval-tracker-diagnostic-facts">
            <DiagnosticFact label="Answer status" value={finalResponse.answer_status ?? "complete"} />
            <DiagnosticFact label="Source mode" value={finalResponse.source_mode ?? "Not reported"} />
            <DiagnosticFact label="Source decision" value={finalResponse.source_decision_reason ?? "Not reported"} />
            <DiagnosticFact label="Coverage" value={finalResponse.coverage?.completeness ?? "Not reported"} />
          </dl>
          {finalResponse.coverage ? (
            <div className="rag-eval-tracker-coverage">
              <DiagnosticList label="Required evidence" values={finalResponse.coverage.required_slots} empty="No required evidence slots." />
              <DiagnosticList label="Covered evidence" values={finalResponse.coverage.covered_slots} empty="No covered evidence slots." />
              {finalResponse.coverage.warnings.length ? <DiagnosticList label="Coverage warnings" values={finalResponse.coverage.warnings} empty="" /> : null}
            </div>
          ) : null}
          {finalResponse.operational_failures?.length ? (
            <div className="rag-eval-tracker-operational-failures" role="status">
              <AlertTriangle size={16} />
              <div>
                <strong>Operational failures</strong>
                {finalResponse.operational_failures.map((failure) => <span key={`${failure.stage}-${failure.code}`}>{failure.stage}: {failure.message}{failure.retryable ? " (retryable)" : ""}</span>)}
              </div>
            </div>
          ) : null}
          {finalResponse.source_expansion?.available ? (
            <div className="rag-eval-tracker-source-action" role="status">
              <AlertTriangle size={16} />
              <span>{finalResponse.source_expansion.reason}</span>
              <button type="button" className="sv-action-secondary" onClick={onExpandSourceSearch}>Search all sources</button>
            </div>
          ) : null}
          {finalResponse.source_clarification ? (
            <div className="rag-eval-tracker-source-action" role="status">
              <Database size={16} />
              <div>
                <strong>{finalResponse.source_clarification.question}</strong>
                <div className="rag-eval-tracker-source-options">
                  {finalResponse.source_clarification.options.map((option) => (
                    <button key={option.source_id} type="button" className="sv-action-secondary" onClick={() => onChooseQuerySource(option.source_id)} title={option.description ?? undefined}>{option.name}</button>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="sv-panel rag-eval-run-details">
        <div className="rag-eval-section-header">
          <div>
            <h2 className="sv-section-title">Run details</h2>
            <p>Identifiers and the slowest completed graph steps.</p>
          </div>
        </div>
        <div className="rag-eval-run-facts">
          <RunFact label="Trace ID" value={state.traceId ?? "Not started"} />
          <RunFact label="Session ID" value={state.sessionId ?? "Created on completion"} />
          <RunFact label="Intent" value={state.intent ? formatIntent(state.intent) : "Pending"} />
          <RunFact label="Runtime" value={runtime} />
        </div>
        <details className="rag-eval-run-timings" open={slowTimings.length > 0}>
          <summary>Node timings <span>{slowTimings.length ? `${slowTimings.length} slowest` : "Pending"}</span></summary>
          {slowTimings.length ? (
            <div className="rag-eval-tracker-timing-list">
              <div className="rag-eval-timing-header" aria-hidden="true">
                <span>Duration</span>
                <span>Node</span>
                <span>Mode</span>
                <span>Details</span>
              </div>
              {slowTimings.map((timing) => (
                <div className="rag-eval-timing-row" key={`${timing.node}-${timing.duration_ms}`}>
                  <span className="rag-eval-timing-duration">{formatDurationMs(timing.duration_ms)}</span>
                  <strong className="rag-eval-timing-node">{timing.node.split("_").join(" ")}</strong>
                  <small className="rag-eval-timing-mode">{timing.execution_mode?.split("_").join(" ") ?? "Mode not reported"}</small>
                  <small className="rag-eval-timing-detail">{timing.detail ? timing.detail.replace(/,(?!\s)/g, ", ") : "No detail recorded"}</small>
                </div>
              ))}
            </div>
          ) : <div className="rag-eval-pane-empty"><EmptyPanel>Timings arrive when the response completes.</EmptyPanel></div>}
        </details>
      </section>
    </>
  );
}

function pipelineStages({ finalResponse, state }: QueryTrackerResultsViewModel): PipelineStage[] {
  const active = state.startedAt !== null && state.completedAt === null;
  const retrieved = state.retrievalStages.find((stage) => stage.name === "retrieved");
  const reranked = state.retrievalStages.find((stage) => stage.name === "reranked");
  const evidence = [...state.retrievalStages].reverse().find((stage) => stage.name === "final_evidence");
  const stages: PipelineStage[] = [
    { label: "Routing", detail: state.intent ? formatIntent(state.intent) : "Classify and plan", status: state.intent ? "complete" : active ? "running" : "pending" },
    { label: "Permissions", detail: retrieved ? "Access filters applied" : "Enforce source access", status: retrieved ? "complete" : "pending" },
    { label: "Retrieval", detail: retrieved ? `${retrieved.candidate_count} candidates` : "Search permitted sources", status: retrieved ? "complete" : "pending" },
    { label: "Reranking", detail: reranked ? `${reranked.candidate_count} ranked` : "Order by relevance", status: reranked ? "complete" : "pending" },
    { label: "Evidence", detail: evidence ? `${evidence.candidate_count} accepted` : "Build grounded context", status: evidence ? "complete" : "pending" },
    { label: "Generation", detail: state.answerText ? "Answer generated" : "Compose cited answer", status: state.answerText ? "complete" : isNodeRunning(state.timeline, "synthesizer") ? "running" : "pending" },
    { label: "Verification", detail: finalResponse ? finalResponse.faithfulness_status : "Check answer support", status: finalResponse ? "complete" : "pending" },
  ];
  if (state.errorMessage) {
    const failed = stages.find((stage) => stage.status !== "complete");
    if (failed) failed.status = "error";
  }
  return stages;
}

function isNodeRunning(timeline: QueryTrackerTimelineItem[], node: string): boolean {
  return timeline.some((item) => item.node === node && item.status === "running");
}

function PipelineStep({ stage }: { stage: PipelineStage }) {
  const Icon = stage.status === "complete" ? CheckCircle2 : stage.status === "error" ? XCircle : stage.status === "running" ? Loader2 : CircleDashed;
  return (
    <div className="rag-eval-pipeline-step" data-status={stage.status} role="listitem">
      <Icon className={stage.status === "running" ? "animate-spin" : ""} size={16} />
      <span><strong>{stage.label}</strong><small>{stage.detail}</small></span>
    </div>
  );
}

function PaneHeader({ title, detail }: { title: string; detail: string }) {
  return <header className="rag-eval-pane-header"><h2>{title}</h2><p>{detail}</p></header>;
}

function TimelineRow({ item }: { item: QueryTrackerTimelineItem }) {
  const Icon = item.status === "error" ? XCircle : item.status === "warning" ? AlertTriangle : item.status === "running" ? Loader2 : CheckCircle2;
  return (
    <div className="rag-eval-tracker-timeline-row" data-status={item.status} role="listitem">
      <span className="rag-eval-tracker-timeline-icon"><Icon className={item.status === "running" ? "animate-spin" : ""} size={15} /></span>
      <div><strong>{item.label}</strong>{item.detail ? <small>{item.detail}</small> : null}</div>
      <span className="rag-eval-tracker-timeline-meta">{formatDurationMs(item.durationMs)}</span>
    </div>
  );
}

function TrackerFact({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return <div className="rag-eval-tracker-fact"><Icon size={16} /><span><small>{label}</small><strong>{value}</strong></span></div>;
}

function RunFact({ label, value }: { label: string; value: string }) {
  return <div><small>{label}</small><strong>{value}</strong></div>;
}

function DiagnosticFact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function DiagnosticList({ empty, label, values }: { empty: string; label: string; values: string[] }) {
  return (
    <div>
      <strong>{label}</strong>
      {values.length ? <ul>{values.map((value) => <li key={value}>{value}</li>)}</ul> : <span>{empty}</span>}
    </div>
  );
}
