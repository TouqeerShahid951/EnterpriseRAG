import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { Clock3 } from "lucide-react";

import { isGlobalAdmin } from "./authz";
import { ChatKnowledgeSpaceControl, type ChatSpaceOption } from "./components/chat/ChatWorkspaceHeader";
import { InlineMessage, SessionLoading } from "./components/layout/Common";
import { Modal } from "./components/layout/Modal";
import { PrudentiaSidebarHeaderProvider } from "./components/layout/PrudentiaWorkspace";
import { PrudentiaLogin } from "./pages/PrudentiaLogin";
import { authenticatedRouteForUser, canAccessRoute, canonicalRoute, defaultRouteForUser, routeFromLocation, routePaths, routeTitles, type NavigateOptions, type RouteId } from "./routes";
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

const PrudentiaAccountPage = lazy(() => import("./pages/PrudentiaAccountPage").then((module) => ({ default: module.PrudentiaAccountPage })));
const PrudentiaAccessPage = lazy(() => import("./pages/PrudentiaAccessPage").then((module) => ({ default: module.PrudentiaAccessPage })));
const PrudentiaAuditPage = lazy(() => import("./pages/PrudentiaAuditPage").then((module) => ({ default: module.PrudentiaAuditPage })));
const PrudentiaChatPage = lazy(() => import("./pages/PrudentiaChatPage").then((module) => ({ default: module.PrudentiaChatPage })));
const PrudentiaDatabaseConnectorsPage = lazy(() => import("./pages/PrudentiaDatabaseConnectorsPage").then((module) => ({ default: module.PrudentiaDatabaseConnectorsPage })));
const PrudentiaDocumentOverviewPage = lazy(() => import("./pages/PrudentiaDocumentOverviewPage").then((module) => ({ default: module.PrudentiaDocumentOverviewPage })));
const PrudentiaDocumentsPage = lazy(() => import("./pages/PrudentiaDocumentsPage").then((module) => ({ default: module.PrudentiaDocumentsPage })));
const PrudentiaFolderSourcesPage = lazy(() => import("./pages/PrudentiaFolderSourcesPage").then((module) => ({ default: module.PrudentiaFolderSourcesPage })));
const PrudentiaIngestionHealthPage = lazy(() => import("./pages/PrudentiaIngestionHealthPage").then((module) => ({ default: module.PrudentiaIngestionHealthPage })));
const PrudentiaIngestionJobsPage = lazy(() => import("./pages/PrudentiaIngestionJobsPage").then((module) => ({ default: module.PrudentiaIngestionJobsPage })));
const PrudentiaOverviewPage = lazy(() => import("./pages/PrudentiaPlannedPage").then((module) => ({ default: module.PrudentiaOverviewPage })));
const PrudentiaRagEvaluationsPage = lazy(() => import("./pages/PrudentiaRagEvaluationsPage").then((module) => ({ default: module.PrudentiaRagEvaluationsPage })));
const PrudentiaReviewQueuePage = lazy(() => import("./pages/PrudentiaReviewQueuePage").then((module) => ({ default: module.PrudentiaReviewQueuePage })));
const PrudentiaSettingsPage = lazy(() => import("./pages/PrudentiaSettingsPage").then((module) => ({ default: module.PrudentiaSettingsPage })));
const SourceViewerPage = lazy(() => import("./pages/SourceViewerPage").then((module) => ({ default: module.SourceViewerPage })));
const PrudentiaUploadPage = lazy(() => import("./pages/PrudentiaUploadPage").then((module) => ({ default: module.PrudentiaUploadPage })));

function App() {
  const [activeRoute, setActiveRoute] = useState<RouteId>(() => routeFromLocation() ?? "chat");
  const [isLightMode, setIsLightMode] = useState(() => readStoredBoolean(THEME_STORAGE_KEY, false));
  const auth = useAuthSession();
  const resolvedRoute = auth.currentUser ? authenticatedRouteForUser(auth.currentUser, routeFromLocation()) : activeRoute;
  const chat = useChatSession(auth.currentUser);
  const inventory = useDocumentInventory(auth.currentUser);
  const pdfUpload = usePdfUpload(auth.currentUser);
  const sidebarSpaceOptions = useMemo(() => knowledgeSpaceOptions(auth.currentUser, inventory.documents), [auth.currentUser, inventory.documents]);
  const sidebarDocumentCount = useMemo(
    () => documentsInActiveSpace(inventory.documents, chat.activeSpacePath).length,
    [chat.activeSpacePath, inventory.documents],
  );

  useLayoutEffect(() => {
    document.documentElement.classList.toggle("light", isLightMode);
    document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute("content", isLightMode ? "#f1f1f4" : "#101016");
    writeStoredBoolean(THEME_STORAGE_KEY, isLightMode);
  }, [isLightMode]);

  useEffect(() => {
    const routeTitle = auth.currentUser ? routeTitles[resolvedRoute] : "Sign in";
    document.title = `${routeTitle} | Prudentia AI`;
    if (!auth.currentUser) return;

    const focusMainContent = window.requestAnimationFrame(() => {
      const main = document.getElementById("main-content");
      if (!main) return;
      main.setAttribute("tabindex", "-1");
      main.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(focusMainContent);
  }, [auth.currentUser, resolvedRoute]);

  useEffect(() => {
    const handlePopState = () => setActiveRoute(routeFromLocation() ?? "chat");
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (auth.currentUserQuery.isLoading) return;
    if (!auth.currentUser) return navigate("login", { replace: true });
    if (activeRoute !== resolvedRoute || location.pathname !== routePaths[resolvedRoute]) {
      navigate(resolvedRoute, { replace: true });
    }
  }, [activeRoute, auth.currentUser, auth.currentUserQuery.isLoading, resolvedRoute]);

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

  if (resolvedRoute === "source-viewer") {
    return (
      <>
        <div className="app-route-stage">
          <Suspense fallback={<RouteLoading label="Loading source viewer" />}>
            <SourceViewerPage />
          </Suspense>
        </div>
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
      spaceSwitchDisabled={resolvedRoute === "chat" && chat.hasPendingGeneration}
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
      <div className="sr-only" aria-live="polite" aria-atomic="true">{routeTitles[resolvedRoute]}</div>

      <div className="app-route-stage" key={resolvedRoute}>
        <Suspense fallback={<RouteLoading label={`Loading ${routeTitles[resolvedRoute]}`} />}>
        {resolvedRoute === "chat" ? (
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
        {resolvedRoute === "knowledge-spaces" ? <PrudentiaDocumentsPage onLogout={handleLogout} onNavigate={navigate} uploadJobs={pdfUpload.batchItems} user={user} view="spaces" /> : null}
        {resolvedRoute === "document-overview" ? <PrudentiaDocumentOverviewPage documents={inventory.documents} documentsLoading={inventory.documentsQuery.isLoading} onLogout={handleLogout} onNavigate={navigate} uploadJobs={pdfUpload.batchItems} user={user} /> : null}
        {resolvedRoute === "documents" ? <PrudentiaDocumentsPage onLogout={handleLogout} onNavigate={navigate} user={user} view="documents" /> : null}
        {resolvedRoute === "document-trash" ? <PrudentiaDocumentsPage onLogout={handleLogout} onNavigate={navigate} user={user} view="trash" /> : null}
        {resolvedRoute === "upload" ? <PrudentiaUploadPage batchItems={pdfUpload.batchItems} cancelingJobId={pdfUpload.cancelingJobId} currentDocuments={inventory.documents} currentUser={user} onCancelIngestJob={pdfUpload.cancelJob} onClearUploadJobs={pdfUpload.clearUploadJobs} onLogout={handleLogout} onNavigate={navigate} onPdfDraftChange={pdfUpload.updatePdfDraft} onPdfSubmit={pdfUpload.onPdfSubmit} pdfDraft={pdfUpload.pdfDraft} selectionError={pdfUpload.selectionError} uploadPending={pdfUpload.uploadMutation.isPending} /> : null}
        {resolvedRoute === "document-extraction" ? <PrudentiaFolderSourcesPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {resolvedRoute === "database-connectors" ? <PrudentiaDatabaseConnectorsPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {resolvedRoute === "ingestion-jobs" ? <PrudentiaIngestionJobsPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {resolvedRoute === "ingestion-health" ? <PrudentiaIngestionHealthPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {resolvedRoute === "review" ? <PrudentiaReviewQueuePage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {resolvedRoute === "access" ? <PrudentiaAccessPage currentUser={user} onAuthChanged={auth.authChanged} onLogout={handleLogout} onNavigate={navigate} /> : null}
        {resolvedRoute === "account" ? <PrudentiaAccountPage currentUser={user} isLoggingOut={auth.logoutMutation.isPending} onAuthChanged={auth.authChanged} onLogout={handleLogout} onNavigate={navigate} /> : null}
        {resolvedRoute === "settings" ? <PrudentiaSettingsPage currentUser={user} onLogout={handleLogout} onNavigate={navigate} /> : null}

        {resolvedRoute === "overview" ? <PrudentiaOverviewPage documents={inventory.documents} documentsLoading={inventory.documentsQuery.isLoading} onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {resolvedRoute === "activity-log" ? <PrudentiaAuditPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {resolvedRoute === "evaluations" ? (
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
        </Suspense>
      </div>
      {sessionTimeoutDialog}
    </PrudentiaSidebarHeaderProvider>
  );
}

function RouteLoading({ label }: { label: string }) {
  return (
    <main className="route-loading" id="main-content" tabIndex={-1} aria-busy="true" aria-label={label}>
      <div className="route-loading-inner" role="status">
        <span className="sv-skeleton h-5 w-40" />
        <span className="sv-skeleton h-3 w-64" />
        <span className="sv-skeleton h-32 w-full" />
        <span className="sr-only">{label}</span>
      </div>
    </main>
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
