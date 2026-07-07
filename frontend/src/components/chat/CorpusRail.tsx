import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent, RefObject } from "react";
import { AlertTriangle, ChevronDown, Loader2, MessageSquare, PanelLeftClose, PanelLeftOpen, Plus, Trash2, X } from "lucide-react";

import type { SavedChatSessionSummary } from "../../types/chat";

export function CorpusRail({
  activeSessionId,
  collapsed,
  errorMessage,
  generatingSessionId,
  loadErrorMessage,
  loading,
  loadingSessionId,
  onCollapsedChange,
  onDeleteSession,
  onLoadSession,
  onLoadMoreSessions,
  onReset,
  savedSessions,
  savedSessionsFetchingMore,
  savedSessionsHasMore,
  savedSessionsTotal,
}: Props) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerCloseRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const drawerTriggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!collapsed) setDrawerOpen(false);
  }, [collapsed]);

  useEffect(() => {
    if (drawerOpen) requestAnimationFrame(() => drawerCloseRef.current?.focus());
  }, [drawerOpen]);

  function closeDrawer() {
    setDrawerOpen(false);
    drawerTriggerRef.current?.focus();
  }

  function handleDrawerKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeDrawer();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      drawerRef.current?.querySelectorAll<HTMLElement>(
        "button:not([disabled]), a[href], select:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])",
      ) ?? [],
    ).filter((element) => element.offsetParent !== null);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function handleReset() {
    onReset();
    setDrawerOpen(false);
  }

  function handleLoadSession(sessionId: string) {
    onLoadSession(sessionId);
    setDrawerOpen(false);
  }

  if (collapsed) {
    return (
      <>
        <aside className="rag-corpus-rail rag-corpus-rail-collapsed" aria-label="Conversations">
          <button
            type="button"
            onClick={() => onCollapsedChange(false)}
            className="rag-history-rail-expand"
            aria-label="Expand chat history panel"
            title="Expand chat history"
          >
            <PanelLeftOpen size={16} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={handleReset}
            disabled={Boolean(loadingSessionId)}
            className="rag-history-rail-action"
            aria-label="New chat"
            title="New chat"
          >
            <Plus size={17} aria-hidden="true" />
          </button>
          <button
            ref={drawerTriggerRef}
            type="button"
            onClick={() => setDrawerOpen(true)}
            className="rag-history-rail-action rag-history-rail-action-with-count"
            aria-label={`Open chat history, ${savedSessionsTotal} saved conversations`}
            aria-controls="rag-chat-history-drawer"
            aria-expanded={drawerOpen}
            title="Chat history"
          >
            <MessageSquare size={17} aria-hidden="true" />
            <span>{savedSessionsTotal > 99 ? "99+" : savedSessionsTotal}</span>
          </button>
        </aside>

        {drawerOpen ? (
          <button type="button" className="rag-history-drawer-backdrop" onClick={closeDrawer} aria-label="Close chat history" />
        ) : null}
        {drawerOpen ? (
          <aside
            ref={drawerRef}
            id="rag-chat-history-drawer"
            className="rag-history-drawer"
            aria-label="Chat history"
            onKeyDown={handleDrawerKeyDown}
          >
            <CorpusRailHeader
              count={savedSessionsTotal}
              onCollapse={() => {
                onCollapsedChange(false);
                setDrawerOpen(false);
              }}
              onClose={closeDrawer}
              closeRef={drawerCloseRef}
            />
            <CorpusRailContent
              activeSessionId={activeSessionId}
              errorMessage={errorMessage}
              generatingSessionId={generatingSessionId}
              loadErrorMessage={loadErrorMessage}
              loading={loading}
              loadingSessionId={loadingSessionId}
              onDeleteSession={onDeleteSession}
              onLoadSession={handleLoadSession}
              onLoadMoreSessions={onLoadMoreSessions}
              onReset={handleReset}
              savedSessions={savedSessions}
              savedSessionsFetchingMore={savedSessionsFetchingMore}
              savedSessionsHasMore={savedSessionsHasMore}
            />
          </aside>
        ) : null}
      </>
    );
  }

  return (
    <aside className="rag-corpus-rail" aria-label="Conversations">
      <CorpusRailHeader count={savedSessionsTotal} onCollapse={() => onCollapsedChange(true)} />
      <CorpusRailContent
        activeSessionId={activeSessionId}
        errorMessage={errorMessage}
        generatingSessionId={generatingSessionId}
        loadErrorMessage={loadErrorMessage}
        loading={loading}
        loadingSessionId={loadingSessionId}
        onDeleteSession={onDeleteSession}
        onLoadSession={onLoadSession}
        onLoadMoreSessions={onLoadMoreSessions}
        onReset={onReset}
        savedSessions={savedSessions}
        savedSessionsFetchingMore={savedSessionsFetchingMore}
        savedSessionsHasMore={savedSessionsHasMore}
      />
    </aside>
  );
}

function CorpusRailHeader({ closeRef, count, onClose, onCollapse }: CorpusRailHeaderProps) {
  const drawer = Boolean(onClose);
  return (
    <div className="rag-corpus-header">
      <div>
        <p className="sv-eyebrow">Conversations</p>
        <div className="mt-2 flex items-center justify-between gap-2">
          <h2 className="text-headline-sm text-on-surface">Chat history</h2>
          <span className="rag-chat-history-count">{count}</span>
        </div>
      </div>
      <div className="rag-corpus-header-actions">
        <button
          type="button"
          onClick={onCollapse}
          className="rag-history-header-action"
          aria-label={drawer ? "Expand chat history rail" : "Collapse chat history"}
          title={drawer ? "Expand rail" : "Collapse history"}
        >
          {drawer ? <PanelLeftOpen size={16} aria-hidden="true" /> : <PanelLeftClose size={16} aria-hidden="true" />}
        </button>
        {onClose ? (
          <button ref={closeRef} type="button" onClick={onClose} className="rag-history-header-action" aria-label="Close chat history" title="Close">
            <X size={16} aria-hidden="true" />
          </button>
        ) : null}
      </div>
    </div>
  );
}

function CorpusRailContent({
  activeSessionId,
  errorMessage,
  generatingSessionId,
  loadErrorMessage,
  loading,
  loadingSessionId,
  onDeleteSession,
  onLoadSession,
  onLoadMoreSessions,
  onReset,
  savedSessions,
  savedSessionsFetchingMore,
  savedSessionsHasMore,
}: ContentProps) {
  const historyLocked = Boolean(loadingSessionId);
  return (
    <>
      <button type="button" onClick={onReset} disabled={historyLocked} className="rag-secondary-action w-full">
        <Plus size={16} />
        New chat
      </button>

      <div className="rag-chat-history-list" role="list" aria-busy={loading || savedSessionsFetchingMore ? "true" : undefined} aria-label="Chat history">
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
        {!loading && !errorMessage && loadErrorMessage ? (
          <div className="rag-chat-history-empty" role="status">
            <AlertTriangle size={17} />
            <span>
              <strong>Chat unavailable</strong>
              <small>{loadErrorMessage}</small>
            </span>
          </div>
        ) : null}
        {!loading && !errorMessage ? savedSessions.map((session) => (
          <ChatHistoryItem
            active={activeSessionId === session.id}
            deleteDisabled={historyLocked || generatingSessionId === session.id}
            generating={generatingSessionId === session.id}
            openDisabled={historyLocked}
            key={session.id}
            loading={loadingSessionId === session.id}
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
        {!loading && !errorMessage && savedSessionsHasMore ? (
          <button
            type="button"
            onClick={onLoadMoreSessions}
            disabled={savedSessionsFetchingMore}
            className="rag-secondary-action rag-chat-history-load-more w-full"
          >
            {savedSessionsFetchingMore ? <Loader2 className="animate-spin" size={15} /> : <ChevronDown size={15} />}
            {savedSessionsFetchingMore ? "Loading chats" : "Load more chats"}
          </button>
        ) : null}
      </div>
    </>
  );
}

function ChatHistorySkeleton({ count = 3 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }, (_value, item) => (
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

function ChatHistoryItem({ active, deleteDisabled, generating, loading, onDelete, onLoad, openDisabled, session }: ChatHistoryItemProps) {
  const openIcon = loading || generating ? <Loader2 className="animate-spin" size={16} /> : <MessageSquare size={16} />;
  return (
    <div className={`rag-chat-history-item ${active ? "is-active" : ""} ${generating ? "is-generating" : ""}`} role="listitem">
      <button
        type="button"
        disabled={openDisabled}
        onClick={onLoad}
        className="rag-chat-history-open"
        aria-label={`Open ${session.title}`}
        aria-current={active ? "page" : undefined}
        aria-busy={loading || generating ? "true" : undefined}
      >
        {openIcon}
        <span>
          <strong>{session.title}</strong>
          <small>
            {generating ? <span className="rag-chat-history-status">Generating</span> : null}
            {generating ? " " : null}
            {session.questionCount} question{session.questionCount === 1 ? "" : "s"} - {formatSessionTime(session.updatedAt)}
          </small>
        </span>
      </button>
      <button type="button" disabled={deleteDisabled} onClick={onDelete} className="rag-chat-history-delete" aria-label={`Delete ${session.title}`}>
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
  collapsed: boolean;
  errorMessage: string | null;
  generatingSessionId: string | null;
  loadErrorMessage: string | null;
  loading: boolean;
  loadingSessionId: string | null;
  onCollapsedChange: (collapsed: boolean) => void;
  onDeleteSession: (sessionId: string) => void;
  onLoadSession: (sessionId: string) => void;
  onLoadMoreSessions: () => void;
  onReset: () => void;
  savedSessions: SavedChatSessionSummary[];
  savedSessionsFetchingMore: boolean;
  savedSessionsHasMore: boolean;
  savedSessionsTotal: number;
};

type ContentProps = Omit<Props, "collapsed" | "onCollapsedChange" | "savedSessionsTotal">;

type CorpusRailHeaderProps = {
  closeRef?: RefObject<HTMLButtonElement>;
  count: number;
  onClose?: () => void;
  onCollapse: () => void;
};

type ChatHistoryItemProps = {
  active: boolean;
  deleteDisabled: boolean;
  generating: boolean;
  loading: boolean;
  onDelete: () => void;
  onLoad: () => void;
  openDisabled: boolean;
  session: SavedChatSessionSummary;
};
