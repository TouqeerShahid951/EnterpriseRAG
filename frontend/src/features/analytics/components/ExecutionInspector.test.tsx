import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ApiClientError } from "@/lib/api/client";
import type { AnalyticsExecution } from "@/types/api/analytics";
import { ExecutionInspector } from "./ExecutionInspector";

function render(execution?: Partial<AnalyticsExecution>, error: Error | null = null, loading = false) {
  return renderToStaticMarkup(<ExecutionInspector execution={execution as AnalyticsExecution | undefined} loading={loading} error={error} onClose={() => {}} onRetry={() => {}} />);
}

describe("execution inspector", () => {
  it("shows lineage attempts, generation identities and repeated timings without raw content", () => {
    const markup = render({ execution_id: "old", latency_ms: 300, retrieval_lineage_status: "available", retrieval_lineage: {
      performance: { node_timings: [{ node: "retrieve", duration_ms: 100 }, { node: "retrieve", duration_ms: 200 }] },
      stages: [{ name: "reranked", attempt: 1, status: "completed", candidate_count: 2, truncated: true,
        candidates: [{ doc_id: "doc", chunk_id: "chunk", index_generation_id: "generation-7", rank: 1, retrieval_score: null, rerank_score: 0.8 }] }],
    } });
    expect(markup).toContain("attempt 2");
    expect(markup).toContain("generation-7");
    expect(markup).toContain("100 ms");
    expect(markup).toContain("200 ms");
    expect(markup).toContain("Not measured");
    expect(markup).toContain("Conversation content restricted");
  });

  it("distinguishes missing, expired, forbidden, loading and unavailable details", () => {
    expect(render(undefined, null, true)).toContain("Loading execution details");
    expect(render(undefined, new ApiClientError({ status: 404, code: "missing", message: "missing" }))).toContain("history was deleted or has expired");
    expect(render(undefined, new ApiClientError({ status: 403, code: "denied", message: "denied" }))).toContain("no longer have access");
    expect(render({ retrieval_lineage_status: "expired", latency_ms: null })).toContain("Evidence details expired");
    expect(render({ retrieval_lineage_status: "unavailable", latency_ms: null })).toContain("not captured or are unavailable");
    expect(render(undefined, new Error("outage"))).toContain("Could not load execution details");
    const overdue = render({ outcome: "interrupted", liveness_status: "heartbeat_expired", latency_ms: null });
    expect(overdue).toContain("Heartbeat overdue");
    expect(overdue).toContain("interruption is inferred");
    const untracked = render({ outcome: null, liveness_status: "untracked", latency_ms: null });
    expect(untracked).toContain("Status unknown");
    expect(untracked).toContain("no heartbeat tracking");
  });
});
