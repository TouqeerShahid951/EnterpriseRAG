import { useEffect, useMemo, useState } from "react";

import { isGlobalAdmin } from "./authz";
import { ChatKnowledgeSpaceControl, type ChatSpaceOption } from "./components/chat/ChatWorkspaceHeader";
import { FahamSidebarHeaderProvider } from "./components/layout/FahamWorkspace";
import { FahamAccountPage } from "./pages/FahamAccountPage";
import { FahamAccessPage } from "./pages/FahamAccessPage";
import { FahamAuditPage } from "./pages/FahamAuditPage";
import { FahamChatPage } from "./pages/FahamChatPage";
import { FahamDocumentOverviewPage } from "./pages/FahamDocumentOverviewPage";
import { FahamDocumentsPage } from "./pages/FahamDocumentsPage";
import { FahamFolderSourcesPage } from "./pages/FahamFolderSourcesPage";
import { FahamIngestionHealthPage } from "./pages/FahamIngestionHealthPage";
import { FahamIngestionJobsPage } from "./pages/FahamIngestionJobsPage";
import { FahamLogin } from "./pages/FahamLogin";
import { FahamOverviewPage } from "./pages/FahamPlannedPage";
import { FahamRagEvaluationsPage } from "./pages/FahamRagEvaluationsPage";
import { FahamReviewQueuePage } from "./pages/FahamReviewQueuePage";
import { FahamSettingsPage } from "./pages/FahamSettingsPage";
import { SourceViewerPage } from "./pages/SourceViewerPage";
import { FahamUploadPage } from "./pages/FahamUploadPage";
import { canAccessRoute, canonicalRoute, defaultRouteForUser, routeFromLocation, routePaths, type NavigateOptions, type RouteId } from "./routes";
import { SessionLoading } from "./components/layout/Common";
import { useAuthSession } from "./state/useAuthSession";
import { useChatSession } from "./state/useChatSession";
import { useDocumentInventory } from "./state/useDocumentInventory";
import { usePdfUpload } from "./state/usePdfUpload";
import type { Document, User as AuthUser } from "./types/api";
import { isDocumentInSpace, userSpacesFromPaths } from "./utils/groups";
import "./styles.css";

function App() {
  const [activeRoute, setActiveRoute] = useState<RouteId>(() => routeFromLocation() ?? "chat");
  const [isLightMode, setIsLightMode] = useState(false);
  const auth = useAuthSession();
  const chat = useChatSession(auth.currentUser);
  const inventory = useDocumentInventory(auth.currentUser);
  const pdfUpload = usePdfUpload();
  const sidebarSpaceOptions = useMemo(() => knowledgeSpaceOptions(auth.currentUser, inventory.documents), [auth.currentUser, inventory.documents]);
  const sidebarDocumentCount = useMemo(
    () => documentsInActiveSpace(inventory.documents, chat.activeSpacePath).length,
    [chat.activeSpacePath, inventory.documents],
  );

  useEffect(() => {
    document.documentElement.classList.toggle("light", isLightMode);
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

  function handleAuthChanged() {
    auth.authChanged();
    navigate("overview", { replace: true });
  }

  function handleLogout() {
    auth.logoutMutation.mutate(undefined, { onSettled: () => navigate("login", { replace: true }) });
  }

  if (auth.currentUserQuery.isLoading) return <SessionLoading />;
  if (!auth.currentUser) return <FahamLogin onAuthChanged={handleAuthChanged} />;

  const user = auth.currentUser;
  if (activeRoute === "source-viewer") {
    return <div className="app-route-stage"><SourceViewerPage /></div>;
  }

  const sidebarHeaderContent = (
    <ChatKnowledgeSpaceControl
      activeSpacePath={chat.activeSpacePath}
      allowAllSpaces={isGlobalAdmin(user)}
      documentCount={sidebarDocumentCount}
      documentsLoading={inventory.documentsQuery.isLoading}
      onActiveSpaceChange={chat.changeActiveSpacePath}
      spaceSwitchDisabled={activeRoute === "chat" && chat.hasPendingTurn}
      spaces={sidebarSpaceOptions}
    />
  );

  return (
    <FahamSidebarHeaderProvider
      isLightMode={isLightMode}
      onToggleTheme={() => setIsLightMode((value) => !value)}
      value={sidebarHeaderContent}
    >
      <a className="skip-link" href="#main-content">Skip to content</a>

      <div className="app-route-stage" key={activeRoute}>
        {activeRoute === "chat" ? (
          <FahamChatPage
            activeSessionId={chat.activeSessionId}
            activeSpacePath={chat.activeSpacePath}
            addScopedDocument={chat.addScopedDocument}
            cancelPendingTurn={chat.cancelPendingTurn}
            chatTurns={chat.chatTurns}
            currentDocuments={inventory.currentDocuments}
            deleteChatSession={chat.deleteChatSession}
            documents={inventory.documents}
            documentsLoading={inventory.documentsQuery.isLoading}
            hasPendingTurn={chat.hasPendingTurn}
            latestResponse={chat.latestResponse}
            loadChatSession={chat.loadChatSession}
            loadMoreSavedSessions={chat.loadMoreSavedSessions}
            loadingSessionId={chat.loadingSessionId}
            onActiveSpaceChange={chat.changeActiveSpacePath}
            onCancelArtifactJob={chat.cancelArtifactJob}
            onClarifyArtifactJob={chat.clarifyArtifactJob}
            onLogout={handleLogout}
            onNavigate={navigate}
            onQuestionChange={chat.setQuestion}
            onQuestionSubmit={chat.handleQuestionSubmit}
            onReset={chat.resetChat}
            onRetryArtifactJob={chat.retryArtifactJob}
            onSelectSource={chat.setSelectedSource}
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
            selectedSource={chat.selectedSource}
            user={user}
          />
        ) : null}
        {activeRoute === "knowledge-spaces" ? <FahamDocumentsPage onLogout={handleLogout} onNavigate={navigate} uploadJobs={pdfUpload.batchItems} user={user} view="spaces" /> : null}
        {activeRoute === "document-overview" ? <FahamDocumentOverviewPage documents={inventory.documents} documentsLoading={inventory.documentsQuery.isLoading} onLogout={handleLogout} onNavigate={navigate} uploadJobs={pdfUpload.batchItems} user={user} /> : null}
        {activeRoute === "documents" ? <FahamDocumentsPage onLogout={handleLogout} onNavigate={navigate} user={user} view="documents" /> : null}
        {activeRoute === "document-trash" ? <FahamDocumentsPage onLogout={handleLogout} onNavigate={navigate} user={user} view="trash" /> : null}
        {activeRoute === "upload" ? <FahamUploadPage batchItems={pdfUpload.batchItems} cancelingJobId={pdfUpload.cancelingJobId} currentDocuments={inventory.documents} currentUser={user} onCancelIngestJob={pdfUpload.cancelJob} onLogout={handleLogout} onNavigate={navigate} onPdfDraftChange={pdfUpload.updatePdfDraft} onPdfSubmit={pdfUpload.onPdfSubmit} pdfDraft={pdfUpload.pdfDraft} selectionError={pdfUpload.selectionError} uploadPending={pdfUpload.uploadMutation.isPending} /> : null}
        {activeRoute === "document-extraction" ? <FahamFolderSourcesPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {activeRoute === "ingestion-jobs" ? <FahamIngestionJobsPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {activeRoute === "ingestion-health" ? <FahamIngestionHealthPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {activeRoute === "review" ? <FahamReviewQueuePage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {activeRoute === "access" ? <FahamAccessPage currentUser={user} onAuthChanged={auth.authChanged} onLogout={handleLogout} onNavigate={navigate} /> : null}
        {activeRoute === "account" ? <FahamAccountPage currentUser={user} isLoggingOut={auth.logoutMutation.isPending} onAuthChanged={auth.authChanged} onLogout={handleLogout} onNavigate={navigate} /> : null}
        {activeRoute === "settings" ? <FahamSettingsPage currentUser={user} onLogout={handleLogout} onNavigate={navigate} /> : null}

        {activeRoute === "overview" ? <FahamOverviewPage documents={inventory.documents} documentsLoading={inventory.documentsQuery.isLoading} onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {activeRoute === "activity-log" ? <FahamAuditPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {activeRoute === "evaluations" ? <FahamRagEvaluationsPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
      </div>
    </FahamSidebarHeaderProvider>
  );
}

function documentsInActiveSpace(documents: Document[], activeSpacePath: string | null): Document[] {
  if (!activeSpacePath) return documents;
  return documents.filter((document) => isDocumentInSpace(document.group_path, activeSpacePath));
}

function knowledgeSpaceOptions(user: AuthUser | null, documents: Document[]): ChatSpaceOption[] {
  if (!user) return [];
  const paths = isGlobalAdmin(user) ? Array.from(new Set(documents.map((document) => document.group_path))).sort() : user.group_paths;
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
