import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { createQueryTrackerState } from "../queryTrackerState";
import { QueryTrackerResults } from "./QueryTrackerResults";

describe("QueryTrackerResults", () => {
  it("exposes retrieved chunk text from a focusable chunk ID", () => {
    const state = createQueryTrackerState();
    state.sources = [{
      chunk_id: "contract:11",
      doc_id: "contract",
      doc_title: "Touqeer contract.pdf",
      page: 4,
      page_start: 4,
      page_end: 4,
      excerpt: "CLAUSE SIX: The employee shall receive remuneration.",
      group_path: "/legal",
      clearance_level: "NATO_RESTRICTED",
      effective_date: null,
      highlight_ranges: [],
      citation_targets: [],
    }];
    state.retrievalStages = [{
      name: "retrieved",
      attempt: 0,
      status: "completed",
      candidate_count: 1,
      candidates: [{
        rank: 1,
        point_id: "contract:11",
        chunk_id: "contract:11",
        doc_id: "contract",
        doc_title: "Touqeer contract.pdf",
        page_start: 4,
        group_path: "/legal",
        retrieval_score: 0.94,
        excerpt: "CLAUSE SIX: The employee shall receive remuneration.",
      }],
    }];

    const markup = renderToStaticMarkup(
      <QueryTrackerResults model={{
        finalResponse: null,
        onChooseQuerySource: () => undefined,
        onExpandSourceSearch: () => undefined,
        runtime: "Complete",
        slowTimings: [{ node: "abac_retriever", duration_ms: 225, execution_mode: "deterministic", detail: "candidates=60,limit=12" }],
        state,
      }} />,
    );

    expect(markup).toContain("<details");
    expect(markup).toContain("Vector retrieval");
    expect(markup).toContain("Pipeline overview");
    expect(markup).toContain("Stage details");
    expect(markup).toContain("Retrieved evidence");
    expect(markup).toContain("Run details");
    expect(markup).toContain("Duration");
    expect(markup).toContain("abac retriever");
    expect(markup).toContain("candidates=60, limit=12");
    expect(markup).toContain("vector 0.940");
    expect(markup).toContain("Final cited sources");
    expect(markup).toContain("Chunk contract:11");
    expect(markup).toContain('role="tooltip"');
    expect(markup).toContain("CLAUSE SIX: The employee shall receive remuneration.");
  });

  it("shows current query diagnostics and source recovery actions", () => {
    const state = createQueryTrackerState();
    const finalResponse = {
      ...response(),
      answer_status: "clarification" as const,
      coverage: { required_slots: ["policy owner"], covered_slots: [], completeness: "partial" as const, warnings: ["Missing owner"] },
      operational_failures: [{ stage: "execution" as const, code: "db_timeout", retryable: true, message: "Database timed out", source_id: "source-1" }],
      source_mode: "db_only",
      source_decision_reason: "source_match",
      source_expansion: { available: true, reason: "No database answer", suggested_source_mode: "hybrid" as const },
      source_clarification: { question: "Choose a source", options: [{ source_id: "source-1", name: "Cases", description: "Approved cases" }] },
    };

    const markup = renderToStaticMarkup(<QueryTrackerResults model={{
      finalResponse,
      onChooseQuerySource: () => undefined,
      onExpandSourceSearch: () => undefined,
      runtime: "Complete",
      slowTimings: [],
      state,
    }} />);

    expect(markup).toContain("Query outcome");
    expect(markup).toContain("source_match");
    expect(markup).toContain("Required evidence");
    expect(markup).toContain("Database timed out");
    expect(markup).toContain("Search all sources");
    expect(markup).toContain("Choose a source");
  });
});

function response() {
  return {
    answer: "Select a source.",
    conflict_detail: null,
    conflict_flag: false,
    degraded: false,
    degraded_reason: null,
    faithfulness_score: 0,
    faithfulness_status: "skipped" as const,
    intent: "conversational" as const,
    latency_ms: 20,
    session_id: "session-1",
    sources: [],
    trace_id: "trace-1",
    unfounded_claims: [],
  };
}
