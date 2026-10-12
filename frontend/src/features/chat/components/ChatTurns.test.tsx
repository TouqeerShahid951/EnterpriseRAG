import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChatTurns } from "./ChatTurns";

describe("ChatTurns reply actions", () => {
  it("offers reply only on completed assistant responses", () => {
    const markup = renderToStaticMarkup(
      <ChatTurns
        chatTurns={[
          { id: "user-1", role: "user", content: "Question", createdAt: "2026-09-02T00:00:00Z" },
          { id: "assistant-1", role: "assistant", status: "complete", question: "Question", createdAt: "2026-09-02T00:00:01Z", progress: [] },
        ]}
        documents={[]}
        onCancelArtifactJob={async () => undefined}
        onClarifyArtifactJob={async () => undefined}
        onChooseQuerySource={() => undefined}
        onExpandSourceSearch={() => undefined}
        onReplyToTurn={() => undefined}
        onRetryArtifactJob={async () => undefined}
        onSelectSource={() => undefined}
        selectedSource={null}
      />,
    );

    expect(markup).toContain('aria-label="Reply to this answer"');
    expect(markup).not.toContain("Reply to this question");
  });
});

it.each(["pending", "cancelled"] as const)("shows %s streamed text and hides answer actions", (status) => {
  const markup = renderToStaticMarkup(
    <ChatTurns
      chatTurns={[{ id: "draft", role: "assistant", status, question: "Question", createdAt: "2026-09-09T00:00:00Z", progress: [], streamText: "Draft answer" }]}
      documents={[]} onCancelArtifactJob={async () => undefined} onClarifyArtifactJob={async () => undefined}
      onChooseQuerySource={() => undefined} onExpandSourceSearch={() => undefined} onReplyToTurn={() => undefined}
      onRetryArtifactJob={async () => undefined} onSelectSource={() => undefined} selectedSource={null}
    />,
  );
  expect(markup).toContain(status === "pending" ? "Running graph" : "Partial draft");
  expect(markup).toContain("Draft answer");
  expect(markup).not.toContain('aria-label="Reply to this answer"');
  expect(markup).not.toContain("Citations verified");
});

it.each(["verified", "abstained", "source_matched", "unverified"] as const)("shows the final %s response without draft withdrawal notices", (status) => {
  const markup = renderToStaticMarkup(
    <ChatTurns
      chatTurns={[{ id: "a", role: "assistant", status: "complete", question: "Question", createdAt: "2026-09-09T00:00:00Z", progress: [],
        streamText: "Old unsupported draft",
        response: { trace_id: "trace", session_id: "session", answer: "Final response", sources: [], conflict_flag: false, conflict_detail: null,
          faithfulness_score: status === "verified" ? 1 : 0, faithfulness_status: status === "verified" ? "checked" : status === "abstained" ? "failed" : "skipped",
          unfounded_claims: [], intent: "factual_simple", latency_ms: 10, degraded: status === "abstained", degraded_reason: null,
          citation_verification: { version: 1, offset_unit: "unicode_code_point", answer_sha256: "hash", status, repair_count: 1, claims: [] } },
      }]}
      documents={[]} onCancelArtifactJob={async () => undefined} onClarifyArtifactJob={async () => undefined}
      onChooseQuerySource={() => undefined} onExpandSourceSearch={() => undefined} onReplyToTurn={() => undefined}
      onRetryArtifactJob={async () => undefined} onSelectSource={() => undefined} selectedSource={null}
    />,
  );
  expect(markup).not.toContain("Draft withdrawn");
  expect(markup).not.toContain("Draft replaced");
  expect(markup).toContain("Final response");
  expect(markup).not.toContain("Old unsupported draft");
});
