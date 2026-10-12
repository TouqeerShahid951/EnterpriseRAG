import { describe, expect, it } from "vitest";

import type { ChatTurn } from "@/types/chat";
import { replyLabelForTurn, replyPreviewForTurn, restoredChatTurnKey } from "./chatPageUtils";

describe("chat reply presentation", () => {
  it("labels questions and compacts long answers", () => {
    const userTurn: ChatTurn = {
      id: "user-1",
      role: "user",
      content: "Which case was filed first?",
      createdAt: "2026-09-02T00:00:00Z",
    };
    const assistantTurn: ChatTurn = {
      id: "assistant-1",
      role: "assistant",
      status: "complete",
      question: userTurn.content,
      createdAt: "2026-09-02T00:00:01Z",
      progress: [],
      streamText: `The first case was ${"Acme ".repeat(50)}`,
    };

    expect(replyLabelForTurn(userTurn)).toBe("Your question");
    expect(replyPreviewForTurn(userTurn)).toBe("Which case was filed first?");
    expect(replyLabelForTurn(assistantTurn)).toBe("Prudentia AI");
    expect(replyPreviewForTurn(assistantTurn).length).toBeLessThanOrEqual(180);
    expect(replyPreviewForTurn(assistantTurn).endsWith("…")).toBe(true);
  });
});

describe("restored chat position", () => {
  it("uses a stable key after the requested turn is available", () => {
    const chatTurns: ChatTurn[] = [
      { id: "user-1", role: "user", content: "Question", createdAt: "2026-09-02T00:00:00Z" },
    ];

    expect(restoredChatTurnKey("session-1", "user-1", chatTurns)).toBe("session-1:user-1");
    expect(restoredChatTurnKey("session-1", "missing", chatTurns)).toBeNull();
  });
});
