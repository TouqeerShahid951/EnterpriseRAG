import { describe, expect, it } from "vitest";

import type { RAGResponse } from "@/types/api";
import type { ChatTurn, SavedChatSessionSummary } from "@/types/chat";
import { mergeSavedSessionsWithLocal, updateChatSessionTurns, type ChatSessionTurnCache } from "./chatSessionCache";
import { applyStreamEvent } from "./chatStreamReducer";

describe("chat session cache helpers", () => {
  it("updates a background session without changing the visible session id", () => {
    const activeSessionId = "session-visible";
    const cache: ChatSessionTurnCache = {
      "session-generating": [
        userTurn("user-1", "Draft the summary"),
        assistantTurn("assistant-1", "Draft the summary"),
      ],
      [activeSessionId]: [userTurn("user-2", "Older chat")],
    };

    const next = updateChatSessionTurns(cache, "session-generating", (turns) =>
      applyStreamEvent(turns, "assistant-1", { event: "done", data: response("session-generating", "Done") }),
    );

    expect(activeSessionId).toBe("session-visible");
    expect(next["session-visible"]).toEqual(cache["session-visible"]);
    expect(next["session-generating"][1]).toMatchObject({ role: "assistant", status: "complete", streamText: "Done" });
  });

  it("merges local in-flight sessions with saved sessions without duplicates", () => {
    const saved: SavedChatSessionSummary[] = [
      summary("session-existing", "Saved title", "2026-06-18T10:00:00Z"),
      summary("session-old", "Old saved", "2026-06-17T10:00:00Z"),
    ];
    const local: SavedChatSessionSummary[] = [
      summary("session-new", "Generating title", "2026-06-19T10:00:00Z"),
      summary("session-existing", "Local duplicate", "2026-06-19T11:00:00Z"),
    ];

    expect(mergeSavedSessionsWithLocal(saved, local, "session-new").map((session) => session.id)).toEqual([
      "session-new",
      "session-existing",
      "session-old",
    ]);
  });

  it("keeps a generating duplicate local row visible until the stream settles", () => {
    const saved = [summary("session-generating", "Saved title", "2026-06-18T10:00:00Z")];
    const local = [summary("session-generating", "Current question", "2026-06-19T10:00:00Z")];

    expect(mergeSavedSessionsWithLocal(saved, local, "session-generating")[0]).toMatchObject({
      id: "session-generating",
      title: "Current question",
    });
    expect(mergeSavedSessionsWithLocal(saved, local, null)[0]).toMatchObject({
      id: "session-generating",
      title: "Saved title",
    });
  });

});

function summary(id: string, title: string, updatedAt: string): SavedChatSessionSummary {
  return { id, title, createdAt: updatedAt, updatedAt, questionCount: 1 };
}

function userTurn(id: string, content: string): ChatTurn {
  return { id, role: "user", content, createdAt: "2026-06-19T10:00:00Z" };
}

function assistantTurn(id: string, question: string): ChatTurn {
  return {
    id,
    role: "assistant",
    status: "pending",
    question,
    createdAt: "2026-06-19T10:00:01Z",
    progress: [],
  };
}

function response(sessionId: string, answer: string): RAGResponse {
  return {
    trace_id: "trace-1",
    answer,
    sources: [],
    artifacts: [],
    artifact_job: null,
    conflict_flag: false,
    conflict_detail: null,
    faithfulness_score: 1,
    faithfulness_status: "checked",
    unfounded_claims: [],
    intent: "conversational",
    session_id: sessionId,
    latency_ms: 42,
    node_timings: [],
    degraded: false,
    degraded_reason: null,
  };
}
