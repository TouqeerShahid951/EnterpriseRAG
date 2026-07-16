import type { ArtifactJobSummary, RagSseEvent, RAGResponse, SourceAnchor } from "@/types/api";
import type { ChatTurn, QueryProgressItem } from "@/types/chat";
import { formatIntent } from "@/lib/utils/format";
import { createId } from "@/lib/utils/ids";

export function applyStreamEvent(turns: ChatTurn[], assistantTurnId: string, event: RagSseEvent): ChatTurn[] {
  return turns.map((turn) => {
    if (turn.id !== assistantTurnId || turn.role !== "assistant") return turn;
    if (event.event === "token") return { ...turn, streamText: appendText(turn.streamText, event.data.text) };
    if (event.event === "done") return { ...turn, status: "complete", response: event.data, streamText: event.data.answer };
    if (event.event === "verified") {
      return {
        ...turn,
        status: "complete",
        response: event.data,
        streamText: event.data.answer,
        progress: [...turn.progress, verifiedProgress(event.data.faithfulness_status)],
      };
    }
    const progress = progressFromEvent(event);
    return progress ? { ...turn, progress: [...turn.progress, progress] } : turn;
  });
}

function verifiedProgress(status: RAGResponse["faithfulness_status"]): QueryProgressItem {
  return {
    id: createId("progress"),
    label: status === "checked" ? "Grounding verified" : status === "failed" ? "Grounding check failed" : "Grounding check complete",
    detail: status === "checked" ? "Answer claims were checked against cited sources" : humanizeNode(status),
    kind: status === "failed" ? "warning" : "system",
  };
}

function progressFromEvent(event: RagSseEvent): QueryProgressItem | null {
  if (event.event === "trace" && event.data.node) {
    const nodeProgress = progressForNode(event.data.node);
    return {
      id: createId("progress"),
      label: nodeProgress.label,
      detail: executionDetail(event.data.execution_mode, event.data.detail) ?? event.data.agent ?? nodeProgress.detail,
      kind: "node",
    };
  }
  if (event.event === "intent") {
    return {
      id: createId("progress"),
      label: "Question type identified",
      detail: formatIntent(event.data.intent),
      intent: event.data.intent,
      kind: "intent",
    };
  }
  if (event.event === "source") {
    return {
      id: createId("progress"),
      label: "Evidence source found",
      detail: sourceDetail(event.data),
      kind: "source",
      source: event.data,
    };
  }
  if (event.event === "artifact") {
    return {
      id: createId("progress"),
      label: "File ready",
      detail: event.data.filename,
      kind: "system",
    };
  }
  if (event.event === "artifact_job") {
    return {
      id: createId("progress"),
      label: "Document job queued",
      detail: artifactJobProgressDetail(event.data),
      kind: "system",
    };
  }
  if (event.event === "warning") {
    return { id: createId("progress"), label: "Warning", detail: warningDetail(event), kind: "warning" };
  }
  return null;
}

function artifactJobProgressDetail(job: ArtifactJobSummary): string {
  const formats = job.requested_formats.map((format) => format.toUpperCase()).join(", ");
  const detail = job.stage_detail?.trim() || job.stage_label?.trim() || humanizeNode(job.status);
  return `${detail}${formats ? ` · ${formats}` : ""}`;
}

function executionDetail(mode?: string, detail?: string | null): string | null {
  if (mode === "ai_assisted") return detail ? `AI-assisted · ${humanizeNode(detail)}` : "AI-assisted";
  if (mode === "fallback") return detail ? `Rules fallback · ${humanizeNode(detail)}` : "Rules fallback";
  if (mode === "deterministic") return "Rules-only";
  return null;
}

function progressForNode(node: string): Pick<QueryProgressItem, "label" | "detail"> {
  const labels: Record<string, Pick<QueryProgressItem, "label" | "detail">> = {
    session_memory: { label: "Checking chat context", detail: "Looking for prior session hints" },
    source_resolver: { label: "Resolving source mode", detail: "Applying composer and source hints" },
    intent_router: { label: "Classifying question", detail: "Choosing the retrieval route" },
    query_planner: { label: "Planning retrieval path", detail: "Breaking the question into evidence targets" },
    abac_retriever: { label: "Searching permitted documents", detail: "Applying access filters first" },
    reranker: { label: "Ranking candidate passages", detail: "Prioritizing likely evidence" },
    verifier: { label: "Checking evidence quality", detail: "Deciding whether to retry retrieval" },
    temporal_resolver: { label: "Resolving document timeline", detail: "Preferring current effective sources" },
    contradiction_detector: { label: "Checking for conflicts", detail: "Comparing claims across sources" },
    evidence_builder: { label: "Assembling citations", detail: "Preparing source anchors" },
    synthesizer: { label: "Drafting cited answer", detail: "Writing from retrieved evidence" },
    faithfulness_checker: { label: "Verifying answer grounding", detail: "Checking claims against sources" },
    artifact_generator: { label: "Preparing requested files", detail: "Rendering downloadable artifacts" },
    response_serializer: { label: "Finalizing response", detail: "Packaging answer and citations" },
  };
  return labels[node] ?? { label: humanizeNode(node) };
}

function humanizeNode(node: string): string {
  return node
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function sourceDetail(source: SourceAnchor): string {
  const page = source.page_start ?? source.page ?? source.page_end;
  return page ? `${source.doc_title} · page ${page}` : source.doc_title;
}

function warningDetail(event: Extract<RagSseEvent, { event: "warning" }>): string {
  if (event.data.message) return event.data.message;
  if (event.data.code === "verifier_retry") return `Evidence check requested another search${event.data.retry_count ? ` (${event.data.retry_count})` : ""}`;
  if (event.data.code === "low_faithfulness") return "Some answer claims may need closer review";
  if (event.data.code === "conflicting_sources") return "Retrieved sources disagree";
  if (event.data.code === "artifact_generation_failed") return "The answer was generated, but file creation failed";
  if (event.data.code === "artifact_generation_partial") return "Some requested files could not be created";
  return humanizeNode(event.data.code);
}

export function compactText(value: string): string {
  return value.length > 96 ? `${value.slice(0, 93).trimEnd()}...` : value;
}

function appendText(current: string | undefined, next: string): string {
  return current ? `${current}${next}` : next;
}
