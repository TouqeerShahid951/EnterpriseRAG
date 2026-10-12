import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { User } from "@/types/api";
import { ChatEmptyState } from "./ChatEmptyState";

describe("ChatEmptyState", () => {
  it("shows only shortcuts available to the current role", () => {
    const html = renderToStaticMarkup(
      <ChatEmptyState
        composer={<textarea aria-label="Ask a question" />}
        hasCorpus
        onFocusComposer={vi.fn()}
        onNavigate={vi.fn()}
        user={makeUser("member")}
      />,
    );

    expect(html).toContain("Ask indexed evidence");
    expect(html).toContain("Generate artifacts");
    expect(html).not.toContain("Upload governed documents");
    expect(html).not.toContain("Review OCR and image queues");
  });
});

function makeUser(accountType: User["account_type"]): User {
  return {
    user_id: `user-${accountType}`,
    email: `${accountType}@example.com`,
    account_type: accountType,
    group_paths: ["/finance"],
    clearance_level: "COSMIC_TOP_SECRET",
    permission_version: 1,
    must_change_password: false,
  };
}
