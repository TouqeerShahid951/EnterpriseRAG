import { AlertTriangle, MessageSquare, Plus, Trash2 } from "lucide-react";

import type { SavedChatSession } from "../../types/chat";

export function CorpusRail({ activeSessionId, errorMessage, hasPendingTurn, loading, onDeleteSession, onLoadSession, onReset, savedSessions }: Props) {
  return (
    <aside className="rag-corpus-rail">
      <div>
        <p className="sv-eyebrow">Conversations</p>
        <div className="mt-2 flex items-center justify-between gap-2">
          <h2 className="text-headline-sm text-on-surface">Chat history</h2>
          <span className="rag-chat-history-count">{savedSessions.length}</span>
        </div>
      </div>

      <button type="button" onClick={onReset} disabled={hasPendingTurn} className="rag-secondary-action w-full">
        <Plus size={16} />
        New chat
      </button>

      <div className="rag-chat-history-list" role="list" aria-busy={loading ? "true" : undefined} aria-label="Chat history">
        {loading ? <ChatHistorySkeleton /> : null}
        {!loading && errorMessage ? (
          <div className="rag-chat-history-empty" role="status">
            <AlertTriangle size={17} />
            <span>
              <strong>Chat history unavailable</strong>
              <small>{errorMessage}</small>
            </span>
          </div>
        ) : null}
        {!loading && !errorMessage ? savedSessions.map((session) => (
          <ChatHistoryItem
            active={activeSessionId === session.id}
            disabled={hasPendingTurn}
            key={session.id}
            onDelete={() => onDeleteSession(session.id)}
            onLoad={() => onLoadSession(session.id)}
            session={session}
          />
        )) : null}
        {!loading && !errorMessage && savedSessions.length === 0 ? (
          <div className="rag-chat-history-empty">
            <MessageSquare size={17} />
            <span>
              <strong>No saved chats yet</strong>
              <small>Completed conversations will appear here.</small>
            </span>
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function ChatHistorySkeleton() {
  return (
    <>
      {[0, 1, 2].map((item) => (
        <div className="rag-chat-history-item rag-chat-history-skeleton" key={item} role="listitem">
          <span className="rag-chat-history-skeleton-icon" />
          <span>
            <span className="rag-chat-history-skeleton-line is-title" />
            <span className="rag-chat-history-skeleton-line is-meta" />
          </span>
        </div>
      ))}
    </>
  );
}

function ChatHistoryItem({ active, disabled, onDelete, onLoad, session }: ChatHistoryItemProps) {
  const questionCount = session.turns.filter((turn) => turn.role === "user").length;
  return (
    <div className={`rag-chat-history-item ${active ? "is-active" : ""}`} role="listitem">
      <button type="button" disabled={disabled} onClick={onLoad} className="rag-chat-history-open" aria-current={active ? "page" : undefined}>
        <MessageSquare size={16} />
        <span>
          <strong>{session.title}</strong>
          <small>{questionCount} question{questionCount === 1 ? "" : "s"} · {formatSessionTime(session.updatedAt)}</small>
        </span>
      </button>
      <button type="button" disabled={disabled} onClick={onDelete} className="rag-chat-history-delete" aria-label={`Delete ${session.title}`}>
        <Trash2 size={14} />
      </button>
    </div>
  );
}

function formatSessionTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recent";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

type Props = {
  activeSessionId: string | null;
  errorMessage: string | null;
  hasPendingTurn: boolean;
  loading: boolean;
  onDeleteSession: (sessionId: string) => void;
  onLoadSession: (sessionId: string) => void;
  onReset: () => void;
  savedSessions: SavedChatSession[];
};

type ChatHistoryItemProps = {
  active: boolean;
  disabled: boolean;
  onDelete: () => void;
  onLoad: () => void;
  session: SavedChatSession;
};
