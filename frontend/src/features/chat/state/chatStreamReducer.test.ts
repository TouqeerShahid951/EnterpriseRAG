import { describe, expect, it } from "vitest";

import { applyStreamEvent } from "./chatStreamReducer";
import type { ChatTurn } from "@/types/chat";

describe("chat stream progress", () => {
  it("identifies Live DB SQL preparation instead of document search", () => {
    const turns: ChatTurn[] = [{
      id: "assistant-1",
      role: "assistant",
      status: "pending",
      question: "What are Amina Khan's orders?",
      createdAt: "2026-08-26T00:00:00Z",
      sourceMode: "db_only",
      progress: [],
    }];

    const next = applyStreamEvent(turns, "assistant-1", {
      event: "trace",
      data: { node: "abac_retriever" },
    });

    expect(next[0]).toMatchObject({
      role: "assistant",
      progress: [{
        label: "Preparing live database query",
        detail: "Generating and validating read-only SQL",
      }],
    });
  });

  it("shows document summary preparation progress", () => {
    const turns: ChatTurn[] = [{
      id: "assistant-1",
      role: "assistant",
      status: "pending",
      question: "Summarize this document",
      createdAt: "2026-09-07T00:00:00Z",
      progress: [],
    }];

    const next = applyStreamEvent(turns, "assistant-1", {
      event: "trace",
      data: { node: "summary_preparer" },
    });

    expect(next[0]).toMatchObject({
      role: "assistant",
      progress: [{
        label: "Building complete summary",
        detail: "Processing the document in ordered sections",
      }],
    });
  });
});

function pendingDraft(): ChatTurn[] {
  return [{ id: "a", role: "assistant", status: "pending", question: "Question", createdAt: "2026-09-09T00:00:00Z", progress: [] }];
}

function finalResponse(answer: string, status: "verified" | "abstained"): import("@/types/api").RAGResponse {
  return {
    trace_id: "trace", session_id: "session", answer, sources: [], conflict_flag: false, conflict_detail: null,
    faithfulness_score: status === "verified" ? 1 : 0,
    faithfulness_status: status === "verified" ? "checked" : "failed", unfounded_claims: [],
    intent: "factual_simple", latency_ms: 10, degraded: status === "abstained", degraded_reason: null,
    citation_verification: { version: 1, offset_unit: "unicode_code_point", answer_sha256: "hash", status, repair_count: 1, claims: [] },
  };
}

it.each(["verified", "abstained"] as const)("uses the completed response and ignores late stream events for %s", (status) => {
  let turns = applyStreamEvent(pendingDraft(), "a", { event: "token", data: { text: "Unverified draft", draft: true } });
  expect(turns[0]).toMatchObject({ status: "pending", streamText: "Unverified draft" });
  const response = finalResponse(status === "verified" ? "Corrected answer" : "Could not verify", status);
  turns = applyStreamEvent(turns, "a", { event: "done", data: response });
  expect(turns[0]).toMatchObject({ status: "complete", streamText: response.answer });
  expect(turns[0]).not.toHaveProperty("draftResolution");
  turns = applyStreamEvent(turns, "a", { event: "token", data: { text: "late draft" } });
  turns = applyStreamEvent(turns, "a", { event: "done", data: response });
  expect(turns[0]).toMatchObject({ streamText: response.answer });
  expect(turns[0]).not.toHaveProperty("draftResolution");
});

it("does not resurrect a cancelled draft", () => {
  const turns = pendingDraft().map((turn) => ({ ...turn, status: "cancelled" as const }));
  expect(applyStreamEvent(turns, "a", { event: "done", data: finalResponse("Late answer", "verified") })).toEqual(turns);
});
