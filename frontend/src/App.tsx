import { useEffect, useMemo, useState } from "react";
import { Clock3 } from "lucide-react";

import { isGlobalAdmin } from "./authz";
import { ChatKnowledgeSpaceControl, type ChatSpaceOption } from "./components/chat/ChatWorkspaceHeader";
import { InlineMessage, SessionLoading } from "./components/layout/Common";
import { Modal } from "./components/layout/Modal";
import { PrudentiaSidebarHeaderProvider } from "./components/layout/PrudentiaWorkspace";
import { PrudentiaAccountPage } from "./pages/PrudentiaAccountPage";
import { PrudentiaAccessPage } from "./pages/PrudentiaAccessPage";
import { PrudentiaAuditPage } from "./pages/PrudentiaAuditPage";
import { PrudentiaChatPage } from "./pages/PrudentiaChatPage";
import { PrudentiaDatabaseConnectorsPage } from "./pages/PrudentiaDatabaseConnectorsPage";
import { PrudentiaDocumentOverviewPage } from "./pages/PrudentiaDocumentOverviewPage";
import { PrudentiaDocumentsPage } from "./pages/PrudentiaDocumentsPage";
import { PrudentiaFolderSourcesPage } from "./pages/PrudentiaFolderSourcesPage";
import { PrudentiaIngestionHealthPage } from "./pages/PrudentiaIngestionHealthPage";
import { PrudentiaIngestionJobsPage } from "./pages/PrudentiaIngestionJobsPage";
import { PrudentiaLogin } from "./pages/PrudentiaLogin";
import { PrudentiaOverviewPage } from "./pages/PrudentiaPlannedPage";
import { PrudentiaRagEvaluationsPage } from "./pages/PrudentiaRagEvaluationsPage";
import { PrudentiaReviewQueuePage } from "./pages/PrudentiaReviewQueuePage";
import { PrudentiaSettingsPage } from "./pages/PrudentiaSettingsPage";
import { SourceViewerPage } from "./pages/SourceViewerPage";
import { PrudentiaUploadPage } from "./pages/PrudentiaUploadPage";
import { canAccessRoute, canonicalRoute, defaultRouteForUser, routeFromLocation, routePaths, type NavigateOptions, type RouteId } from "./routes";
import { formatIdleCountdown } from "./state/authSessionTiming";
import { useAuthSession } from "./state/useAuthSession";
import { useChatSession } from "./state/useChatSession";
import { useDocumentInventory } from "./state/useDocumentInventory";
import { usePdfUpload } from "./state/usePdfUpload";
import { readStoredBoolean, writeStoredBoolean } from "./state/uiPreferences";
import type { Document, User as AuthUser } from "./types/api";
import { isDocumentInSpace, userSpacesFromPaths } from "./utils/groups";
import "./styles.css";

const THEME_STORAGE_KEY = "Prudentia-theme-light";

function App() {
  const [activeRoute, setActiveRoute] = useState<RouteId>(() => routeFromLocation() ?? "chat");
  const [isLightMode, setIsLightMode] = useState(() => readStoredBoolean(THEME_STORAGE_KEY, false));
  const auth = useAuthSession();
  const chat = useChatSession(auth.currentUser);
  const inventory = useDocumentInventory(auth.currentUser);
  const pdfUpload = usePdfUpload(auth.currentUser);
  const sidebarSpaceOptions = useMemo(() => knowledgeSpaceOptions(auth.currentUser, inventory.documents), [auth.currentUser, inventory.documents]);
  const sidebarDocumentCount = useMemo(
    () => documentsInActiveSpace(inventory.documents, chat.activeSpacePath).length,
    [chat.activeSpacePath, inventory.documents],
  );

  useEffect(() => {
    document.documentElement.classList.toggle("light", isLightMode);
    writeStoredBoolean(THEME_STORAGE_KEY, isLightMode);
  }, [isLightMode]);

  useEffect(() => {
    const handlePopState = () => setActiveRoute(routeFromLocation() ?? "chat");
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (auth.currentUserQuery.isLoading) return;
    if (!auth.currentUser) return navigate("login", { replace: true });
    const defaultRoute = defaultRouteForUser(auth.currentUser);
    if (auth.currentUser.must_change_password && activeRoute !== "account") return navigate("account", { replace: true });
    if (activeRoute === "login" || location.pathname === "/") return navigate(defaultRoute, { replace: true });
    if (canonicalRoute(activeRoute) !== activeRoute) return navigate(canonicalRoute(activeRoute), { replace: true });
    if (location.pathname !== routePaths[activeRoute]) return navigate(activeRoute, { replace: true });
    if (!canAccessRoute(auth.currentUser, activeRoute)) navigate(defaultRoute, { replace: true });
  }, [activeRoute, auth.currentUser, auth.currentUserQuery.isLoading]);

  function navigate(route: RouteId, options: NavigateOptions = {}) {
    const targetRoute = canonicalRoute(route);
    if (auth.currentUser && targetRoute !== "login" && !canAccessRoute(auth.currentUser, targetRoute)) return;
    setActiveRoute(targetRoute);
    const path = routePaths[targetRoute];
    const target = `${path}${normalizeSearch(options.search)}`;
    if (`${location.pathname}${location.search}` === target) return;
    if (options.replace) history.replaceState(null, "", target);
    else history.pushState(null, "", target);
  }

  function handleAuthChanged(authenticatedUser: AuthUser) {
    auth.authChanged();
    if (authenticatedUser.must_change_password) {
      navigate("account", { replace: true });
      return;
    }
    const redirect = redirectTargetFromStoredPath(auth.consumePostLoginRedirect());
    if (redirect && canAccessRoute(authenticatedUser, redirect.route)) {
      navigate(redirect.route, { replace: true, search: redirect.search });
      return;
    }
    navigate(defaultRouteForUser(authenticatedUser), { replace: true });
  }

  function handleLogout() {
    auth.logoutMutation.mutate(undefined, { onSettled: () => navigate("login", { replace: true }) });
  }

  if (auth.currentUserQuery.isLoading) return <SessionLoading />;
  if (!auth.currentUser) return <PrudentiaLogin onAuthChanged={handleAuthChanged} sessionExpired={auth.sessionExpired} />;

  const user = auth.currentUser;
  const sessionTimeoutDialog = (
    <SessionTimeoutDialog
      open={auth.idleWarning.open}
      remainingSeconds={auth.idleWarning.remainingSeconds}
      staySignedInError={auth.staySignedInMutation.isError}
      staySignedInPending={auth.staySignedInMutation.isPending}
      timeoutMinutes={auth.idleWarning.timeoutMinutes}
      onLogout={handleLogout}
      onStaySignedIn={auth.staySignedIn}
    />
  );

  if (activeRoute === "source-viewer") {
    return (
      <>
        <div className="app-route-stage"><SourceViewerPage /></div>
        {sessionTimeoutDialog}
      </>
    );
  }

  const sidebarHeaderContent = (
    <ChatKnowledgeSpaceControl
      activeSpacePath={chat.activeSpacePath}
      allowAllSpaces={isGlobalAdmin(user)}
      documentCount={sidebarDocumentCount}
      documentsLoading={inventory.documentsQuery.isLoading}
      onActiveSpaceChange={chat.changeActiveSpacePath}
      spaceSwitchDisabled={activeRoute === "chat" && chat.hasPendingGeneration}
      spaces={sidebarSpaceOptions}
    />
  );

  return (
    <PrudentiaSidebarHeaderProvider
      isLightMode={isLightMode}
      onToggleTheme={() => setIsLightMode((value) => !value)}
      value={sidebarHeaderContent}
    >
      <a className="skip-link" href="#main-content">Skip to content</a>

      <div className="app-route-stage" key={activeRoute}>
        {activeRoute === "chat" ? (
          <PrudentiaChatPage
            activeSessionId={chat.activeSessionId}
            activeSpacePath={chat.activeSpacePath}
            addScopedDocument={chat.addScopedDocument}
            cancelPendingTurn={chat.cancelPendingTurn}
            chatTurns={chat.chatTurns}
            currentDocuments={inventory.currentDocuments}
            deleteChatSession={chat.deleteChatSession}
            documents={inventory.documents}
            documentsLoading={inventory.documentsQuery.isLoading}
            activeSessionHasPendingTurn={chat.activeSessionHasPendingTurn}
            generatingSessionId={chat.generatingSessionId}
            hasPendingGeneration={chat.hasPendingGeneration}
            latestResponse={chat.latestResponse}
            loadChatSession={chat.loadChatSession}
            loadMoreSavedSessions={chat.loadMoreSavedSessions}
            loadingSessionId={chat.loadingSessionId}
            onActiveSpaceChange={chat.changeActiveSpacePath}
            onCancelArtifactJob={chat.cancelArtifactJob}
            onClarifyArtifactJob={chat.clarifyArtifactJob}
            onExpandSourceSearch={chat.expandSourceSearch}
            onLogout={handleLogout}
            onNavigate={navigate}
            onQuestionChange={chat.setQuestion}
            onQuestionSubmit={chat.handleQuestionSubmit}
            onReset={chat.resetChat}
            onRetryArtifactJob={chat.retryArtifactJob}
            onSelectSource={chat.setSelectedSource}
            onSelectedQuerySourceChange={chat.setSelectedQuerySourceId}
            onSourceModeChange={chat.setSourceMode}
            question={chat.question}
            removeScopedDocument={chat.removeScopedDocument}
            savedSessions={chat.savedSessions}
            savedSessionsError={chat.savedSessionsError}
            savedSessionLoadError={chat.savedSessionLoadError}
            savedSessionsFetchingMore={chat.savedSessionsFetchingMore}
            savedSessionsHasMore={chat.savedSessionsHasMore}
            savedSessionsLoading={chat.savedSessionsLoading}
            savedSessionsTotal={chat.savedSessionsTotal}
            scopedDocumentIds={chat.scopedDocumentIds}
            selectedQuerySourceId={chat.selectedQuerySourceId}
            selectedSource={chat.selectedSource}
            sourceMode={chat.sourceMode}
            user={user}
          />
        ) : null}
        {activeRoute === "knowledge-spaces" ? <PrudentiaDocumentsPage onLogout={handleLogout} onNavigate={navigate} uploadJobs={pdfUpload.batchItems} user={user} view="spaces" /> : null}
        {activeRoute === "document-overview" ? <PrudentiaDocumentOverviewPage documents={inventory.documents} documentsLoading={inventory.documentsQuery.isLoading} onLogout={handleLogout} onNavigate={navigate} uploadJobs={pdfUpload.batchItems} user={user} /> : null}
        {activeRoute === "documents" ? <PrudentiaDocumentsPage onLogout={handleLogout} onNavigate={navigate} user={user} view="documents" /> : null}
        {activeRoute === "document-trash" ? <PrudentiaDocumentsPage onLogout={handleLogout} onNavigate={navigate} user={user} view="trash" /> : null}
        {activeRoute === "upload" ? <PrudentiaUploadPage batchItems={pdfUpload.batchItems} cancelingJobId={pdfUpload.cancelingJobId} currentDocuments={inventory.documents} currentUser={user} onCancelIngestJob={pdfUpload.cancelJob} onClearUploadJobs={pdfUpload.clearUploadJobs} onLogout={handleLogout} onNavigate={navigate} onPdfDraftChange={pdfUpload.updatePdfDraft} onPdfSubmit={pdfUpload.onPdfSubmit} pdfDraft={pdfUpload.pdfDraft} selectionError={pdfUpload.selectionError} uploadPending={pdfUpload.uploadMutation.isPending} /> : null}
        {activeRoute === "document-extraction" ? <PrudentiaFolderSourcesPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {activeRoute === "database-connectors" ? <PrudentiaDatabaseConnectorsPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {activeRoute === "ingestion-jobs" ? <PrudentiaIngestionJobsPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {activeRoute === "ingestion-health" ? <PrudentiaIngestionHealthPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {activeRoute === "review" ? <PrudentiaReviewQueuePage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {activeRoute === "access" ? <PrudentiaAccessPage currentUser={user} onAuthChanged={auth.authChanged} onLogout={handleLogout} onNavigate={navigate} /> : null}
        {activeRoute === "account" ? <PrudentiaAccountPage currentUser={user} isLoggingOut={auth.logoutMutation.isPending} onAuthChanged={auth.authChanged} onLogout={handleLogout} onNavigate={navigate} /> : null}
        {activeRoute === "settings" ? <PrudentiaSettingsPage currentUser={user} onLogout={handleLogout} onNavigate={navigate} /> : null}

        {activeRoute === "overview" ? <PrudentiaOverviewPage documents={inventory.documents} documentsLoading={inventory.documentsQuery.isLoading} onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {activeRoute === "activity-log" ? <PrudentiaAuditPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {activeRoute === "evaluations" ? (
          <PrudentiaRagEvaluationsPage
            activeSpacePath={chat.activeSpacePath}
            currentDocuments={inventory.currentDocuments}
            documents={inventory.documents}
            documentsLoading={inventory.documentsQuery.isLoading}
            onActiveSpaceChange={chat.changeActiveSpacePath}
            onLogout={handleLogout}
            onNavigate={navigate}
            user={user}
          />
        ) : null}
      </div>
      {sessionTimeoutDialog}
    </PrudentiaSidebarHeaderProvider>
  );
}

function documentsInActiveSpace(documents: Document[], activeSpacePath: string | null): Document[] {
  if (!activeSpacePath) return documents;
  return documents.filter((document) => isDocumentInSpace(document.group_path, activeSpacePath));
}

function knowledgeSpaceOptions(user: AuthUser | null, documents: Document[]): ChatSpaceOption[] {
  if (!user) return [];
  const paths = isGlobalAdmin(user) ? Array.from(new Set(documents.map((document) => document.group_path))).sort() : user.group_paths ?? [];
  return userSpacesFromPaths(paths).map((space) => ({
    documentCount: documents.filter((document) => isDocumentInSpace(document.group_path, space.path)).length,
    name: space.name,
    path: space.path,
  }));
}

export default App;

function normalizeSearch(search: NavigateOptions["search"]) {
  if (!search) return "";
  const value = typeof search === "string" ? search.trim() : search.toString();
  if (!value) return "";
  return value.startsWith("?") ? value : `?${value}`;
}

function redirectTargetFromStoredPath(target: string | null): { route: RouteId; search: string } | null {
  if (!target || target === "/") return null;
  try {
    const url = new URL(target, window.location.origin);
    const route = routeFromLocation(url.pathname, url.search);
    if (!route || route === "login") return null;
    return { route: canonicalRoute(route), search: url.search };
  } catch {
    return null;
  }
}

function SessionTimeoutDialog({
  onLogout,
  onStaySignedIn,
  open,
  remainingSeconds,
  staySignedInError,
  staySignedInPending,
  timeoutMinutes,
}: SessionTimeoutDialogProps) {
  const progress = Math.max(0, Math.min(100, (remainingSeconds / Math.max(1, timeoutMinutes * 60)) * 100));
  return (
    <Modal
      closeButton={false}
      description={`No activity has reached the server for ${timeoutMinutes} minutes.`}
      icon={<Clock3 size={18} aria-hidden="true" />}
      onClose={() => undefined}
      open={open}
      size="sm"
      title="Session timeout"
    >
      <div className="grid gap-4">
        <div className="sv-panel p-4" role="status" aria-live="polite">
          <p className="sv-metadata">Time remaining</p>
          <p className="mt-2 text-headline-md text-on-surface">{formatIdleCountdown(remainingSeconds)}</p>
          <p className="mt-1 text-body-md text-on-surface-variant">
            Stay signed in to continue working, or sign out now.
          </p>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-surface-container-low" aria-hidden="true">
            <span
              className="block h-full rounded-full bg-warning-amber transition-[width] duration-200"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
        {staySignedInError ? (
          <InlineMessage tone="error">
            Unable to extend this session. Sign in again if the session has already expired.
          </InlineMessage>
        ) : null}
        <div className="flex flex-wrap justify-end gap-3">
          <button type="button" className="sv-action-secondary" onClick={onLogout} disabled={staySignedInPending}>
            Sign out
          </button>
          <button type="button" className="sv-action-primary" onClick={onStaySignedIn} disabled={staySignedInPending}>
            {staySignedInPending ? "Extending session" : "Stay signed in"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

type SessionTimeoutDialogProps = {
  onLogout: () => void;
  onStaySignedIn: () => void;
  open: boolean;
  remainingSeconds: number;
  staySignedInError: boolean;
  staySignedInPending: boolean;
  timeoutMinutes: number;
};
