import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { ChatEmptyState } from "@/features/chat/components/ChatEmptyState";
import { ChatWorkspaceHeader } from "@/features/chat/components/ChatWorkspaceHeader";
import { CorpusRail } from "@/features/chat/components/CorpusRail";
import { EvidenceInspector, MobileEvidencePanel } from "@/features/chat/components/EvidenceInspector";
import { PrudentiaWorkspace } from "@/components/layout/PrudentiaWorkspace";
import { readStoredBoolean, writeStoredBoolean } from "@/lib/utils/uiPreferences";
import { withSourceDocumentTitle } from "@/features/chat/utils/sourceDocument";
import type { Props } from "@/features/chat/types/chatPageTypes";
import {
  chatStreamPositionKey,
  documentsInActiveSpace,
  isNearChatBottom,
  selectedSourceNumber,
} from "@/features/chat/utils/chatPageUtils";
import { ChatTurns } from "@/features/chat/components/ChatTurns";
import { ChatComposer } from "@/features/chat/components/ChatComposer";

const CHAT_HISTORY_COLLAPSED_STORAGE_KEY = "Prudentia-chat-history-collapsed";

export function PrudentiaChatPage(props: Props) {
  const activeSpaceDocuments = useMemo(
    () => documentsInActiveSpace(props.documents, props.activeSpacePath),
    [props.activeSpacePath, props.documents],
  );
  const activeCurrentDocuments = useMemo(
    () => documentsInActiveSpace(props.currentDocuments, props.activeSpacePath),
    [props.activeSpacePath, props.currentDocuments],
  );
  const hasCorpus = activeCurrentDocuments.length > 0;
  const source = props.selectedSource ? withSourceDocumentTitle(props.selectedSource, props.documents) : null;
  const sourceCount = props.latestResponse?.sources.length ?? 0;
  const sourceNumber = selectedSourceNumber(props.latestResponse?.sources ?? [], props.selectedSource);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const scrollFrameRef = useRef<number | null>(null);
  const shouldFollowStreamRef = useRef(true);
  const streamIdentityRef = useRef<string | null>(null);
  const mobileHistoryRef = useRef<HTMLDivElement | null>(null);
  const mobileEvidenceRef = useRef<HTMLElement | null>(null);
  const streamPositionKey = useMemo(() => chatStreamPositionKey(props.chatTurns), [props.chatTurns]);
  const lastTurnId = props.chatTurns.at(-1)?.id ?? "empty";
  const streamIdentity = `${props.activeSessionId ?? "new"}:${lastTurnId}`;
  const [historyCollapsed, setHistoryCollapsed] = useState(() => readStoredBoolean(CHAT_HISTORY_COLLAPSED_STORAGE_KEY, false));
  const [mobileHistoryOpen, setMobileHistoryOpen] = useState(false);

  useEffect(() => {
    const streamChanged = streamIdentityRef.current !== streamIdentity;
    streamIdentityRef.current = streamIdentity;
    if (streamChanged) shouldFollowStreamRef.current = true;
    if (!shouldFollowStreamRef.current || scrollFrameRef.current !== null) return;

    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const scrollNode = scrollRef.current;
      if (!scrollNode || !shouldFollowStreamRef.current) return;
      scrollNode.scrollTo({ top: scrollNode.scrollHeight, behavior: "auto" });
    });
  }, [streamIdentity, streamPositionKey]);

  useEffect(() => {
    if (!source || !window.matchMedia("(max-width: 1180px)").matches) return;
    const frame = window.requestAnimationFrame(() => {
      const scrollNode = scrollRef.current;
      const evidenceNode = mobileEvidenceRef.current;
      if (!scrollNode || !evidenceNode) return;
      const top = evidenceNode.getBoundingClientRect().top - scrollNode.getBoundingClientRect().top + scrollNode.scrollTop;
      scrollNode.scrollTo({ top, behavior: "auto" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [source?.chunk_id, source?.doc_id]);

  useEffect(() => () => {
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current);
      scrollFrameRef.current = null;
    }
  }, []);

  useEffect(() => {
    writeStoredBoolean(CHAT_HISTORY_COLLAPSED_STORAGE_KEY, historyCollapsed);
  }, [historyCollapsed]);

  useEffect(() => {
    document.body.classList.toggle("rag-mobile-history-open", mobileHistoryOpen);
    if (mobileHistoryOpen) {
      window.requestAnimationFrame(() => {
        mobileHistoryRef.current?.querySelector<HTMLElement>("button:not([disabled])")?.focus();
      });
    }
    return () => document.body.classList.remove("rag-mobile-history-open");
  }, [mobileHistoryOpen]);

  function closeMobileHistory() {
    setMobileHistoryOpen(false);
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>("[data-chat-history-trigger]")?.focus();
    });
  }

  function handleChatScroll() {
    const scrollNode = scrollRef.current;
    if (!scrollNode) return;
    shouldFollowStreamRef.current = isNearChatBottom(scrollNode);
  }

  function handleMobileHistoryKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeMobileHistory();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      mobileHistoryRef.current?.querySelectorAll<HTMLElement>(
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

  const chatBodyClassName = [
    "rag-chat-body",
    source ? "rag-chat-body-with-evidence" : "",
    historyCollapsed ? "rag-chat-body-history-collapsed" : "",
  ].filter(Boolean).join(" ");

  return (
    <PrudentiaWorkspace activeRoute="chat" onLogout={props.onLogout} onNavigate={props.onNavigate} user={props.user}>
      <main className="rag-chat-page" id="main-content">
        <ChatWorkspaceHeader onOpenHistory={() => setMobileHistoryOpen(true)} savedSessionsTotal={props.savedSessionsTotal} />
        <div className={chatBodyClassName}>
          <CorpusRail
            activeSessionId={props.activeSessionId}
            collapsed={historyCollapsed}
            generatingSessionId={props.generatingSessionId}
            onCollapsedChange={setHistoryCollapsed}
            onDeleteSession={props.deleteChatSession}
            onLoadSession={props.loadChatSession}
            onLoadMoreSessions={props.loadMoreSavedSessions}
            onReset={props.onReset}
            loading={props.savedSessionsLoading}
            loadingSessionId={props.loadingSessionId}
            errorMessage={props.savedSessionsError}
            loadErrorMessage={props.savedSessionLoadError}
            savedSessions={props.savedSessions}
            savedSessionsFetchingMore={props.savedSessionsFetchingMore}
            savedSessionsHasMore={props.savedSessionsHasMore}
            savedSessionsTotal={props.savedSessionsTotal}
          />
          <section className="rag-chat-thread" aria-label="Document chat">
            <div className="rag-chat-scroll" onScroll={handleChatScroll} ref={scrollRef}>
              <div className={props.chatTurns.length === 0 ? "rag-chat-inner rag-chat-inner-empty" : "rag-chat-inner"}>
                {props.chatTurns.length === 0 ? (
                  <ChatEmptyState hasCorpus={hasCorpus} />
                ) : (
                  <ChatTurns
                    chatTurns={props.chatTurns}
                    documents={props.documents}
                    onCancelArtifactJob={props.onCancelArtifactJob}
                    onClarifyArtifactJob={props.onClarifyArtifactJob}
                    onExpandSourceSearch={props.onExpandSourceSearch}
                    onRetryArtifactJob={props.onRetryArtifactJob}
                    onSelectSource={props.onSelectSource}
                    selectedSource={props.selectedSource}
                  />
                )}
                {source ? <MobileEvidencePanel panelRef={mobileEvidenceRef} onClose={() => props.onSelectSource(null)} source={source} sourceCount={sourceCount} sourceNumber={sourceNumber} /> : null}
              </div>
            </div>
            <ChatComposer activeDocuments={activeSpaceDocuments} hasCorpus={hasCorpus} {...props} />
          </section>
          {source ? <EvidenceInspector onClose={() => props.onSelectSource(null)} source={source} sourceCount={sourceCount} sourceNumber={sourceNumber} /> : null}
        </div>
        {mobileHistoryOpen ? (
          <div className="rag-mobile-history-layer">
            <button type="button" className="rag-mobile-history-backdrop" onClick={closeMobileHistory} aria-label="Close chat history" />
            <div
              ref={mobileHistoryRef}
              className="rag-mobile-history-panel"
              role="dialog"
              aria-modal="true"
              aria-label="Chat history"
              onKeyDown={handleMobileHistoryKeyDown}
            >
              <CorpusRail
                activeSessionId={props.activeSessionId}
                collapsed={false}
                generatingSessionId={props.generatingSessionId}
                onCollapsedChange={closeMobileHistory}
                onDeleteSession={props.deleteChatSession}
                onLoadSession={(sessionId) => {
                  props.loadChatSession(sessionId);
                  closeMobileHistory();
                }}
                onLoadMoreSessions={props.loadMoreSavedSessions}
                onReset={() => {
                  props.onReset();
                  closeMobileHistory();
                }}
                loading={props.savedSessionsLoading}
                loadingSessionId={props.loadingSessionId}
                errorMessage={props.savedSessionsError}
                loadErrorMessage={props.savedSessionLoadError}
                mobile
                savedSessions={props.savedSessions}
                savedSessionsFetchingMore={props.savedSessionsFetchingMore}
                savedSessionsHasMore={props.savedSessionsHasMore}
                savedSessionsTotal={props.savedSessionsTotal}
              />
            </div>
          </div>
        ) : null}
      </main>
    </PrudentiaWorkspace>
  );
}
