import type { QueryIntent, RagSseEvent, RAGResponse, SourceAnchor } from "../../types/api";
import type { QueryNodeTiming } from "../../types/query";
import { formatIntent } from "../../utils/format";

export type QueryTrackerTimelineStatus = "running" | "complete" | "warning" | "error";
export type QueryTrackerTimelineKind = "trace" | "intent" | "source" | "artifact" | "warning" | "error" | "done" | "verified";

export interface QueryTrackerTimelineItem {
  id: string;
  kind: QueryTrackerTimelineKind;
  label: string;
  detail: string | null;
  status: QueryTrackerTimelineStatus;
  receivedAt: string;
  node?: string;
  executionMode?: string | null;
  durationMs?: number | null;
}

export interface QueryTrackerState {
  answerText: string;
  completedAt: string | null;
  errorMessage: string | null;
  events: RagSseEvent[];
  finalResponse: RAGResponse | null;
  intent: QueryIntent | null;
  sessionId: string | null;
  sources: SourceAnchor[];
  startedAt: string | null;
  timeline: QueryTrackerTimelineItem[];
  traceId: string | null;
  verifiedResponse: RAGResponse | null;
  warnings: string[];
}

export function createQueryTrackerState(startedAt: string | null = null): QueryTrackerState {
  return {
    answerText: "",
    completedAt: null,
    errorMessage: null,
    events: [],
    finalResponse: null,
    intent: null,
    sessionId: null,
    sources: [],
    startedAt,
    timeline: [],
    traceId: null,
    verifiedResponse: null,
    warnings: [],
  };
}

export function reduceQueryTrackerEvent(
  state: QueryTrackerState,
  event: RagSseEvent,
  receivedAt = new Date().toISOString(),
): QueryTrackerState {
  const eventIndex = state.events.length;
  const base: QueryTrackerState = { ...state, events: [...state.events, event] };

  if (event.event === "trace") {
    const traceId = event.data.trace_id ?? state.traceId;
    const sessionId = event.data.session_id ?? state.sessionId;
    if (!event.data.node) return { ...base, traceId, sessionId };
    return {
      ...base,
      sessionId,
      timeline: [
        ...completeOpenTraceItems(state.timeline),
        {
          id: `trace-${eventIndex}-${event.data.node}`,
          kind: "trace",
          label: labelForNode(event.data.node),
          detail: traceDetail(event.data.execution_mode, event.data.detail),
          status: "running",
          receivedAt,
          node: event.data.node,
          executionMode: event.data.execution_mode ?? null,
          durationMs: null,
        },
      ],
      traceId,
    };
  }

  if (event.event === "intent") {
    return {
      ...base,
      intent: event.data.intent,
      timeline: [
        ...completeOpenTraceItems(state.timeline),
        timelineItem(eventIndex, "intent", "Intent detected", formatIntent(event.data.intent), "complete", receivedAt),
      ],
    };
  }

  if (event.event === "token") {
    return { ...base, answerText: `${state.answerText}${event.data.text}` };
  }

  if (event.event === "source") {
    return {
      ...base,
      sources: [...state.sources, event.data],
      timeline: [
        ...completeOpenTraceItems(state.timeline),
        timelineItem(eventIndex, "source", "Source returned", sourceDetail(event.data), "complete", receivedAt),
      ],
    };
  }

  if (event.event === "artifact" || event.event === "artifact_job") {
    const detail = event.event === "artifact" ? event.data.filename : `${event.data.stage} / ${event.data.progress_pct}%`;
    return {
      ...base,
      timeline: [
        ...completeOpenTraceItems(state.timeline),
        timelineItem(eventIndex, "artifact", event.event === "artifact" ? "Artifact produced" : "Artifact job updated", detail, "complete", receivedAt),
      ],
    };
  }

  if (event.event === "warning") {
    const message = warningMessage(event);
    return {
      ...base,
      timeline: [
        ...completeOpenTraceItems(state.timeline),
        timelineItem(eventIndex, "warning", "Warning", message, "warning", receivedAt),
      ],
      warnings: [...state.warnings, message],
    };
  }

  if (event.event === "error") {
    return {
      ...base,
      completedAt: state.completedAt ?? receivedAt,
      errorMessage: event.data.message,
      timeline: [
        ...completeOpenTraceItems(state.timeline),
        timelineItem(eventIndex, "error", "Query failed", event.data.message, "error", receivedAt),
      ],
    };
  }

  const response = event.data;
  const completedTimeline = applyNodeTimings(completeOpenTraceItems(state.timeline), response.node_timings ?? []);
  const finalTimeline = [
    ...completedTimeline,
    timelineItem(
      eventIndex,
      event.event,
      event.event === "verified" ? "Verification complete" : "Response complete",
      response.degraded ? response.degraded_reason ?? "Completed with degraded retrieval" : `${response.latency_ms}ms total`,
      "complete",
      receivedAt,
    ),
  ];

  return {
    ...base,
    answerText: response.answer || state.answerText,
    completedAt: receivedAt,
    finalResponse: response,
    intent: response.intent ?? state.intent,
    sessionId: response.session_id ?? state.sessionId,
    sources: response.sources.length ? response.sources : state.sources,
    timeline: finalTimeline,
    traceId: response.trace_id ?? state.traceId,
    verifiedResponse: event.event === "verified" ? response : state.verifiedResponse,
  };
}

export function markQueryTrackerCancelled(state: QueryTrackerState, receivedAt = new Date().toISOString()): QueryTrackerState {
  return {
    ...state,
    completedAt: state.completedAt ?? receivedAt,
    timeline: [
      ...completeOpenTraceItems(state.timeline),
      timelineItem(state.events.length, "warning", "Query cancelled", "Streaming was stopped by the user.", "warning", receivedAt),
    ],
    warnings: [...state.warnings, "Streaming was stopped by the user."],
  };
}

export function labelForNode(node: string): string {
  const labels: Record<string, string> = {
    abac_retriever: "Searching permitted documents",
    artifact_generator: "Preparing requested files",
    artifact_planner: "Planning artifact request",
    contradiction_detector: "Checking for conflicts",
    evidence_builder: "Assembling citations",
    faithfulness_checker: "Verifying answer grounding",
    intent_router: "Classifying question",
    query_planner: "Planning retrieval path",
    reranker: "Ranking candidate passages",
    response_serializer: "Finalizing response",
    session_memory: "Checking chat context",
    source_resolver: "Resolving source mode",
    synthesizer: "Drafting cited answer",
    temporal_resolver: "Resolving document timeline",
    verifier: "Checking evidence quality",
  };
  return labels[node] ?? humanizeNode(node);
}

export function slowestNodeTimings(response: RAGResponse | null, limit = 5): QueryNodeTiming[] {
  return [...(response?.node_timings ?? [])]
    .sort((left, right) => right.duration_ms - left.duration_ms)
    .slice(0, limit);
}

export function formatDurationMs(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Pending";
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`;
}

export function sourceDetail(source: SourceAnchor): string {
  const page = source.page_start ?? source.page ?? source.page_end;
  return page ? `${source.doc_title} / page ${page}` : source.doc_title;
}

function timelineItem(
  index: number,
  kind: QueryTrackerTimelineKind,
  label: string,
  detail: string | null,
  status: QueryTrackerTimelineStatus,
  receivedAt: string,
): QueryTrackerTimelineItem {
  return {
    id: `${kind}-${index}`,
    kind,
    label,
    detail,
    status,
    receivedAt,
  };
}

function completeOpenTraceItems(items: QueryTrackerTimelineItem[]): QueryTrackerTimelineItem[] {
  return items.map((item) => (item.kind === "trace" && item.status === "running" ? { ...item, status: "complete" } : item));
}

function applyNodeTimings(items: QueryTrackerTimelineItem[], timings: QueryNodeTiming[]): QueryTrackerTimelineItem[] {
  const usedTimingIndexes = new Set<number>();
  const timedItems = items.map((item) => {
    if (!item.node) return item;
    const timingIndex = timings.findIndex((timing, index) => !usedTimingIndexes.has(index) && timing.node === item.node);
    if (timingIndex < 0) return item;
    usedTimingIndexes.add(timingIndex);
    return {
      ...item,
      detail: timings[timingIndex].detail || item.detail,
      durationMs: timings[timingIndex].duration_ms,
      executionMode: timings[timingIndex].execution_mode ?? item.executionMode ?? null,
      status: "complete" as const,
    };
  });
  const missingTimingItems = timings
    .filter((_, index) => !usedTimingIndexes.has(index))
    .map((timing, index) => ({
      id: `timing-${timing.node}-${index}`,
      kind: "trace" as const,
      label: labelForNode(timing.node),
      detail: timing.detail,
      status: "complete" as const,
      receivedAt: new Date().toISOString(),
      node: timing.node,
      executionMode: timing.execution_mode,
      durationMs: timing.duration_ms,
    }));
  return [...timedItems, ...missingTimingItems];
}

function traceDetail(mode?: string, detail?: string | null): string | null {
  if (mode === "ai_assisted") return detail ? `AI-assisted / ${humanizeNode(detail)}` : "AI-assisted";
  if (mode === "fallback") return detail ? `Rules fallback / ${humanizeNode(detail)}` : "Rules fallback";
  if (mode === "deterministic") return "Rules-only";
  return detail ?? null;
}

function warningMessage(event: Extract<RagSseEvent, { event: "warning" }>): string {
  if (event.data.message) return event.data.message;
  if (event.data.code === "verifier_retry") return `Evidence check requested another search${event.data.retry_count ? ` (${event.data.retry_count})` : ""}`;
  if (event.data.code === "low_faithfulness") return "Some answer claims may need closer review";
  if (event.data.code === "conflicting_sources") return "Retrieved sources disagree";
  if (event.data.code === "artifact_generation_failed") return "The answer was generated, but file creation failed";
  if (event.data.code === "artifact_generation_partial") return "Some requested files could not be created";
  return humanizeNode(event.data.code);
}

function humanizeNode(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
