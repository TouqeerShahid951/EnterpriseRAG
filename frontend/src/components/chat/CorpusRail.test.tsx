import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { CorpusRail } from "./CorpusRail";
import type { SavedChatSessionSummary } from "../../types/chat";

describe("CorpusRail", () => {
  it("keeps history open enabled during generation and locks delete for the generating session only", () => {
    const html = renderToStaticMarkup(
      <CorpusRail
        activeSessionId="session-other"
        collapsed={false}
        errorMessage={null}
        generatingSessionId="session-generating"
        loadErrorMessage={null}
        loading={false}
        loadingSessionId={null}
        onCollapsedChange={vi.fn()}
        onDeleteSession={vi.fn()}
        onLoadMoreSessions={vi.fn()}
        onLoadSession={vi.fn()}
        onReset={vi.fn()}
        savedSessions={[
          session("session-generating", "Generating chat"),
          session("session-other", "Other chat"),
        ]}
        savedSessionsFetchingMore={false}
        savedSessionsHasMore={false}
        savedSessionsTotal={2}
      />,
    );

    expect(html).toContain("Generating");
    expect(html).toContain('aria-label="Open Generating chat"');
    expect(html).not.toContain('aria-label="Open Generating chat" disabled');
    expect(html).toContain('disabled="" class="rag-chat-history-delete" aria-label="Delete Generating chat"');
    expect(html).toContain('class="rag-chat-history-delete" aria-label="Delete Other chat"');
    expect(html).not.toContain('disabled="" class="rag-chat-history-delete" aria-label="Delete Other chat"');
  });

  it("keeps the collapsed rail restore control separate from chat actions", () => {
    const html = renderToStaticMarkup(
      <CorpusRail
        activeSessionId={null}
        collapsed={true}
        errorMessage={null}
        generatingSessionId={null}
        loadErrorMessage={null}
        loading={false}
        loadingSessionId={null}
        onCollapsedChange={vi.fn()}
        onDeleteSession={vi.fn()}
        onLoadMoreSessions={vi.fn()}
        onLoadSession={vi.fn()}
        onReset={vi.fn()}
        savedSessions={[session("session-one", "First chat")]}
        savedSessionsFetchingMore={false}
        savedSessionsHasMore={false}
        savedSessionsTotal={126}
      />,
    );

    expect(html).toContain('class="rag-history-rail-expand" aria-label="Expand chat history panel"');
    expect(html).toContain('aria-label="Open chat history, 126 saved conversations"');
    expect(html).toContain(">99+<");
  });

  it("uses an explicit close control in the mobile history drawer", () => {
    const html = renderToStaticMarkup(
      <CorpusRail
        activeSessionId={null}
        collapsed={false}
        errorMessage={null}
        generatingSessionId={null}
        loadErrorMessage={null}
        loading={false}
        loadingSessionId={null}
        mobile
        onCollapsedChange={vi.fn()}
        onDeleteSession={vi.fn()}
        onLoadMoreSessions={vi.fn()}
        onLoadSession={vi.fn()}
        onReset={vi.fn()}
        savedSessions={[session("session-one", "First chat")]}
        savedSessionsFetchingMore={false}
        savedSessionsHasMore={false}
        savedSessionsTotal={1}
      />,
    );

    expect(html).toContain('class="rag-corpus-rail rag-corpus-rail-mobile"');
    expect(html).toContain('aria-label="Close chat history"');
    expect(html).not.toContain('aria-label="Collapse chat history"');
  });
});

function session(id: string, title: string): SavedChatSessionSummary {
  return {
    id,
    title,
    createdAt: "2026-06-19T10:00:00Z",
    updatedAt: "2026-06-19T10:00:00Z",
    questionCount: 1,
  };
}
