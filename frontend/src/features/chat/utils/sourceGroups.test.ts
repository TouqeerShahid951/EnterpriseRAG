import { describe, expect, it } from "vitest";

import type { SourceAnchor } from "@/types/api";
import type { ChatTurn } from "@/types/chat";
import { groupSourcesByDocument, sourcesForTurn } from "./sourceGroups";

function source(docId: string, chunkId: string, pageStart: number, pageEnd: number, spans: number): SourceAnchor {
  return {
    chunk_id: chunkId,
    doc_id: docId,
    doc_title: `${docId}.pdf`,
    effective_date: null,
    excerpt: "Evidence from several distinct passages in the retrieved document.",
    clearance_level: "NATO_RESTRICTED",
    group_path: "/legal",
    highlight_ranges: Array.from({ length: spans }, (_, index) => ({ start: index * 3, end: index * 3 + 1 })),
    citation_targets: [],
    page: pageStart,
    page_end: pageEnd,
    page_start: pageStart,
  };
}

describe("groupSourcesByDocument", () => {
  it("shows each document once while preserving citation numbers and aggregating evidence", () => {
    const groups = groupSourcesByDocument([
      source("contract", "chunk-7", 7, 8, 4),
      source("contract", "chunk-1", 1, 2, 1),
      source("policy", "chunk-3", 3, 3, 2),
    ]);

    expect(groups).toHaveLength(2);
    expect(groups[0]).toMatchObject({ docId: "contract", matchedSpanCount: 5, pageLabel: "Pages 1-2, 7-8" });
    expect(groups[0].citations.map((citation) => citation.number)).toEqual([1, 2]);
    expect(groups[1]).toMatchObject({ docId: "policy", matchedSpanCount: 2, pageLabel: "Page 3" });
  });

  it("does not count the same chunk twice", () => {
    const duplicate = source("contract", "chunk-1", 1, 2, 1);
    const [group] = groupSourcesByDocument([duplicate, duplicate]);

    expect(group.citations).toHaveLength(1);
    expect(group.matchedSpanCount).toBe(1);
  });

  it("returns the sources owned by the selected assistant turn", () => {
    const citedSource = source("contract", "chunk-1", 1, 2, 1);
    const turn: ChatTurn = {
      id: "assistant-older",
      role: "assistant",
      status: "complete",
      question: "Question",
      createdAt: "2026-09-03T00:00:00Z",
      progress: [],
      response: {
        trace_id: "trace-1",
        answer: "Answer",
        sources: [citedSource],
        artifacts: [],
        artifact_job: null,
        conflict_flag: false,
        conflict_detail: null,
        faithfulness_score: 1,
        faithfulness_status: "checked",
        unfounded_claims: [],
        intent: "factual_simple",
        session_id: "session-1",
        latency_ms: 10,
        node_timings: [],
        degraded: false,
        degraded_reason: null,
      },
    };

    expect(sourcesForTurn(turn)).toEqual([citedSource]);
  });
});
