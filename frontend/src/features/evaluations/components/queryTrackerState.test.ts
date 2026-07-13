import { describe, expect, it } from "vitest";

import type { RagSseEvent, RAGResponse, SourceAnchor } from "@/types/api";
import { createQueryTrackerState, markQueryTrackerCancelled, reduceQueryTrackerEvent, slowestNodeTimings } from "./queryTrackerState";

describe("query tracker state", () => {
  it("turns trace events into timeline rows", () => {
    const state = reduceQueryTrackerEvent(
      createQueryTrackerState("2026-07-01T00:00:00.000Z"),
      { event: "trace", data: { trace_id: "trace-1", session_id: "session-1", node: "abac_retriever", execution_mode: "deterministic" } },
      "2026-07-01T00:00:01.000Z",
    );

    expect(state.traceId).toBe("trace-1");
    expect(state.sessionId).toBe("session-1");
    expect(state.timeline).toMatchObject([
      { kind: "trace", label: "Searching permitted documents", node: "abac_retriever", status: "running" },
    ]);
  });

  it("appends token text", () => {
    const state = [
      { event: "token", data: { text: "Policy" } },
      { event: "token", data: { text: " requires approval." } },
    ].reduce((current, event) => reduceQueryTrackerEvent(current, event as RagSseEvent), createQueryTrackerState());

    expect(state.answerText).toBe("Policy requires approval.");
  });

  it("collects returned sources", () => {
    const source = sourceAnchor({ doc_title: "Policy.pdf", page_start: 4 });
    const state = reduceQueryTrackerEvent(createQueryTrackerState(), { event: "source", data: source }, "2026-07-01T00:00:01.000Z");

    expect(state.sources).toEqual([source]);
    expect(state.timeline[0]).toMatchObject({ kind: "source", detail: "Policy.pdf / page 4", status: "complete" });
  });

  it("surfaces warnings and errors", () => {
    const warned = reduceQueryTrackerEvent(createQueryTrackerState(), { event: "warning", data: { code: "low_faithfulness" } }, "2026-07-01T00:00:01.000Z");
    const failed = reduceQueryTrackerEvent(warned, { event: "error", data: { code: "failed", message: "Model timed out" } }, "2026-07-01T00:00:02.000Z");

    expect(failed.warnings).toEqual(["Some answer claims may need closer review"]);
    expect(failed.errorMessage).toBe("Model timed out");
    expect(failed.timeline.map((item) => item.kind)).toEqual(["warning", "error"]);
  });

  it("finalizes done and verified responses with timings", () => {
    const traced = reduceQueryTrackerEvent(
      createQueryTrackerState(),
      { event: "trace", data: { node: "synthesizer", execution_mode: "ai_assisted", detail: "draft" } },
      "2026-07-01T00:00:01.000Z",
    );
    const done = reduceQueryTrackerEvent(traced, { event: "done", data: response() }, "2026-07-01T00:00:02.000Z");
    const verified = reduceQueryTrackerEvent(done, { event: "verified", data: response({ faithfulness_score: 0.92 }) }, "2026-07-01T00:00:03.000Z");

    expect(done.finalResponse?.answer).toBe("Use the approved policy.");
    expect(done.timeline.find((item) => item.node === "synthesizer")?.durationMs).toBe(240);
    expect(verified.verifiedResponse?.faithfulness_score).toBe(0.92);
    expect(slowestNodeTimings(done.finalResponse).map((timing) => timing.node)).toEqual(["synthesizer", "reranker"]);
  });

  it("marks user cancellation without a failure", () => {
    const state = markQueryTrackerCancelled(createQueryTrackerState(), "2026-07-01T00:00:04.000Z");

    expect(state.errorMessage).toBeNull();
    expect(state.timeline[0]).toMatchObject({ kind: "warning", label: "Query cancelled" });
  });
});

function response(overrides: Partial<RAGResponse> = {}): RAGResponse {
  return {
    answer: "Use the approved policy.",
    conflict_detail: null,
    conflict_flag: false,
    degraded: false,
    degraded_reason: null,
    faithfulness_score: 0.88,
    faithfulness_status: "checked",
    intent: "factual_simple",
    latency_ms: 640,
    node_timings: [
      { node: "synthesizer", duration_ms: 240, execution_mode: "ai_assisted", detail: "draft" },
      { node: "reranker", duration_ms: 80, execution_mode: "deterministic", detail: null },
    ],
    session_id: "session-1",
    sources: [sourceAnchor()],
    trace_id: "trace-1",
    unfounded_claims: [],
    ...overrides,
  };
}

function sourceAnchor(overrides: Partial<SourceAnchor> = {}): SourceAnchor {
  return {
    attribution_status: "complete",
    chunk_id: "chunk-1",
    clearance_level: "NATO_RESTRICTED",
    doc_id: "doc-1",
    doc_title: "Policy.pdf",
    effective_date: null,
    excerpt: "Approved policy excerpt.",
    group_path: "/ops",
    highlight_ranges: [],
    page: null,
    page_end: null,
    page_start: 1,
    ...overrides,
  };
}
