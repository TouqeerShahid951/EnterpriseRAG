import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { Clock3 } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { isGlobalAdmin } from "@/lib/auth/authz";
import { adminApi } from "@/lib/api/contracts";
import { BrandProvider, defaultBranding } from "@/components/brand/BrandContext";
import { ChatKnowledgeSpaceControl, type ChatSpaceOption } from "@/features/chat/components/ChatWorkspaceHeader";
import { InlineMessage, SessionLoading } from "@/components/layout/Common";
import { Modal } from "@/components/layout/Modal";
import { PrudentiaSidebarHeaderProvider } from "@/components/layout/PrudentiaWorkspace";
import { PrudentiaLogin } from "@/features/auth/pages/PrudentiaLogin";
import { authenticatedRouteForUser, canAccessRoute, canonicalRoute, defaultRouteForUser, routeFromLocation, routePaths, routeTitles, type NavigateOptions, type RouteId } from "@/routes/routes";
import { formatIdleCountdown } from "@/features/auth/state/authSessionTiming";
import { useAuthSession } from "@/features/auth/state/useAuthSession";
import { useChatSession } from "@/features/chat/state/useChatSession";
import {
  useDocumentCatalogSummary,
  useDocumentInventory,
} from "@/features/documents/state/useDocumentInventory";
import { usePdfUpload } from "@/features/upload/state/usePdfUpload";
import { ABBREVIATION_GLOSSARY_DOC_TYPE } from "@/features/upload/state/pdfUploadBatch";
import { readStoredBoolean, writeStoredBoolean } from "@/lib/utils/uiPreferences";
import type { DocumentGroupCount, User as AuthUser } from "@/types/api";
import { isDocumentInSpace, userSpacesFromPaths } from "@/lib/utils/groups";
import { readableForeground, readableThemeColor } from "@/lib/utils/themeContrast";
import "@/styles.css";

const THEME_STORAGE_KEY = "Prudentia-theme-light";
const TYPE_SIZES = {
  h1: { compact: "1.375rem", standard: "1.5rem", large: "1.75rem" },
  h2: { compact: "0.875rem", standard: "0.95rem", large: "1.125rem" },
  body: { compact: "0.8125rem", standard: "0.875rem", large: "1rem" },
} as const;
const TYPE_WEIGHTS = { semibold: "600", bold: "700", extrabold: "800" } as const;
const DOCUMENT_INVENTORY_ROUTES = new Set<RouteId>([
  "abbreviation-glossary",
  "chat",
  "evaluations",
  "upload",
]);
const UPLOAD_JOB_ROUTES = new Set<RouteId>([
  "abbreviation-glossary",
  "upload",
]);

const PrudentiaAccountPage = lazy(() => import("@/features/auth/pages/PrudentiaAccountPage").then((module) => ({ default: module.PrudentiaAccountPage })));
const PrudentiaAccessPage = lazy(() => import("@/features/access/pages/PrudentiaAccessPage").then((module) => ({ default: module.PrudentiaAccessPage })));
const PrudentiaAuditPage = lazy(() => import("@/features/audit/pages/PrudentiaAuditPage").then((module) => ({ default: module.PrudentiaAuditPage })));
const PrudentiaChatPage = lazy(() => import("@/features/chat/pages/PrudentiaChatPage").then((module) => ({ default: module.PrudentiaChatPage })));
const PrudentiaSourceManagementPage = lazy(() => import("@/features/connectors/pages/PrudentiaSourceManagementPage").then((module) => ({ default: module.PrudentiaSourceManagementPage })));
const PrudentiaDocumentOverviewPage = lazy(() => import("@/features/documents/pages/PrudentiaDocumentOverviewPage").then((module) => ({ default: module.PrudentiaDocumentOverviewPage })));
const PrudentiaDocumentsPage = lazy(() => import("@/features/documents/pages/PrudentiaDocumentsPage").then((module) => ({ default: module.PrudentiaDocumentsPage })));
const PrudentiaIngestionHealthPage = lazy(() => import("@/features/ingestion/pages/PrudentiaIngestionHealthPage").then((module) => ({ default: module.PrudentiaIngestionHealthPage })));
const PrudentiaIngestionJobsPage = lazy(() => import("@/features/ingestion/pages/PrudentiaIngestionJobsPage").then((module) => ({ default: module.PrudentiaIngestionJobsPage })));
const PrudentiaOverviewPage = lazy(() => import("@/features/overview/pages/PrudentiaPlannedPage").then((module) => ({ default: module.PrudentiaOverviewPage })));
const PrudentiaAnalyticsPage = lazy(() => import("@/features/analytics/pages/PrudentiaAnalyticsPage").then((module) => ({ default: module.PrudentiaAnalyticsPage })));
const PrudentiaRagEvaluationsPage = lazy(() => import("@/features/evaluations/pages/PrudentiaRagEvaluationsPage").then((module) => ({ default: module.PrudentiaRagEvaluationsPage })));
const PrudentiaReviewQueuePage = lazy(() => import("@/features/review-queue/pages/PrudentiaReviewQueuePage").then((module) => ({ default: module.PrudentiaReviewQueuePage })));
const PrudentiaSettingsPage = lazy(() => import("@/features/settings/pages/PrudentiaSettingsPage").then((module) => ({ default: module.PrudentiaSettingsPage })));
const SourceViewerPage = lazy(() => import("@/features/source-viewer/pages/SourceViewerPage").then((module) => ({ default: module.SourceViewerPage })));
const PrudentiaUploadPage = lazy(() => import("@/features/upload/pages/PrudentiaUploadPage").then((module) => ({ default: module.PrudentiaUploadPage })));

function App() {
  const [activeRoute, setActiveRoute] = useState<RouteId>(() => routeFromLocation() ?? "chat");
  const [isLightModePreference, setIsLightMode] = useState(() => readStoredBoolean(THEME_STORAGE_KEY, false));
  const auth = useAuthSession();
  const brandingQuery = useQuery({ queryKey: ["branding"], queryFn: adminApi.getBranding, retry: false });
  const branding = brandingQuery.data ?? defaultBranding;
  const isLightMode = branding.theme_mode === "light" || (branding.theme_mode === "user" && isLightModePreference);
  const resolvedRoute = auth.currentUser ? authenticatedRouteForUser(auth.currentUser, routeFromLocation()) : activeRoute;
  const chat = useChatSession(auth.currentUser, resolvedRoute === "chat");
  const requestedChatSessionId = new URLSearchParams(location.search).get("sessionId");
  const inventory = useDocumentInventory(auth.currentUser, DOCUMENT_INVENTORY_ROUTES.has(resolvedRoute));
  const documentSummary = useDocumentCatalogSummary(auth.currentUser, resolvedRoute !== "source-viewer");
  const pdfUpload = usePdfUpload(
    auth.currentUser,
    UPLOAD_JOB_ROUTES.has(resolvedRoute),
    resolvedRoute === "abbreviation-glossary" ? ABBREVIATION_GLOSSARY_DOC_TYPE : null,
  );

  useEffect(() => {
    sessionStorage.removeItem("agenticrag:stale-chunk-reload");
  }, []);
  const sidebarSpaceOptions = useMemo(
    () => knowledgeSpaceOptions(auth.currentUser, documentSummary.groups),
    [auth.currentUser, documentSummary.groups],
  );
  const sidebarDocumentCount = useMemo(
    () => documentCountInActiveSpace(
      documentSummary.groups,
      documentSummary.total,
      chat.activeSpacePath,
    ),
    [chat.activeSpacePath, documentSummary.groups, documentSummary.total],
  );

  useLayoutEffect(() => {
    document.documentElement.classList.toggle("light", isLightMode);
    document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute("content", isLightMode ? "#ECEBF0" : branding.background_color);
    if (branding.theme_mode === "user") writeStoredBoolean(THEME_STORAGE_KEY, isLightMode);
  }, [branding.background_color, branding.theme_mode, isLightMode]);

  useLayoutEffect(() => {
    document.documentElement.style.setProperty("--color-brand-primary", branding.primary_color);
    document.documentElement.style.setProperty("--color-primary-action", branding.primary_color);
    document.documentElement.style.setProperty("--color-primary", readableThemeColor(branding.primary_color, isLightMode ? "light" : "dark"));
    document.documentElement.style.setProperty("--color-brand-accent", readableThemeColor(branding.accent_color, isLightMode ? "light" : "dark"));
    document.documentElement.style.setProperty("--focus-ring", readableThemeColor(branding.accent_color, isLightMode ? "light" : "dark"));
    document.documentElement.style.setProperty("--color-brand-background", branding.background_color);
    document.documentElement.style.setProperty("--color-on-primary", readableForeground(branding.primary_color));
    document.documentElement.style.setProperty("--font-size-ui-page-title", TYPE_SIZES.h1[branding.h1_size]);
    document.documentElement.style.setProperty("--font-weight-ui-page-title", TYPE_WEIGHTS[branding.h1_weight]);
    setOptionalStyle("--color-heading-h1", branding.h1_color ? readableThemeColor(branding.h1_color, isLightMode ? "light" : "dark") : null);
    document.documentElement.style.setProperty("--font-size-ui-section", TYPE_SIZES.h2[branding.h2_size]);
    document.documentElement.style.setProperty("--font-weight-ui-section", TYPE_WEIGHTS[branding.h2_weight]);
    setOptionalStyle("--color-heading-h2", branding.h2_color ? readableThemeColor(branding.h2_color, isLightMode ? "light" : "dark") : null);
    document.documentElement.style.setProperty("--font-size-ui-body", TYPE_SIZES.body[branding.body_size]);
    return () => {
      document.documentElement.style.removeProperty("--color-brand-primary");
      document.documentElement.style.removeProperty("--color-primary-action");
      document.documentElement.style.removeProperty("--color-primary");
      document.documentElement.style.removeProperty("--color-brand-accent");
      document.documentElement.style.removeProperty("--focus-ring");
      document.documentElement.style.removeProperty("--color-brand-background");
      document.documentElement.style.removeProperty("--color-on-primary");
      document.documentElement.style.removeProperty("--font-size-ui-page-title");
      document.documentElement.style.removeProperty("--font-weight-ui-page-title");
      document.documentElement.style.removeProperty("--color-heading-h1");
      document.documentElement.style.removeProperty("--font-size-ui-section");
      document.documentElement.style.removeProperty("--font-weight-ui-section");
      document.documentElement.style.removeProperty("--color-heading-h2");
      document.documentElement.style.removeProperty("--font-size-ui-body");
    };
  }, [branding.accent_color, branding.background_color, branding.body_size, branding.h1_color, branding.h1_size, branding.h1_weight, branding.h2_color, branding.h2_size, branding.h2_weight, branding.primary_color, isLightMode]);

  useEffect(() => {
    const routeTitle = auth.currentUser ? routeTitles[resolvedRoute] : "Sign in";
    document.title = `${routeTitle} | ${branding.app_name}`;
    document.querySelector<HTMLMetaElement>('meta[name="application-name"]')?.setAttribute("content", branding.app_name);
    if (branding.logo_url) {
      document.querySelector<HTMLLinkElement>('link[rel="icon"]')?.setAttribute("href", branding.logo_url);
      document.querySelector<HTMLLinkElement>('link[rel="apple-touch-icon"]')?.setAttribute("href", branding.logo_url);
    }
    if (!auth.currentUser) return;

    const focusMainContent = window.requestAnimationFrame(() => {
      const main = document.getElementById("main-content");
      if (!main) return;
      main.setAttribute("tabindex", "-1");
      main.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(focusMainContent);
  }, [auth.currentUser, branding.app_name, branding.logo_url, resolvedRoute]);

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

  useEffect(() => {
    if (resolvedRoute === "chat" && requestedChatSessionId && requestedChatSessionId !== chat.activeSessionId) {
      chat.loadChatSession(requestedChatSessionId);
    }
  }, [chat.activeSessionId, requestedChatSessionId, resolvedRoute]);

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

  if (auth.currentUserQuery.isLoading) return <BrandProvider value={branding}><SessionLoading /></BrandProvider>;
  if (!auth.currentUser) return <BrandProvider value={branding}><PrudentiaLogin onAuthChanged={handleAuthChanged} sessionExpired={auth.sessionExpired} /></BrandProvider>;

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
        <BrandProvider value={branding}>
          <div className="app-route-stage">
            <Suspense fallback={<RouteLoading label="Loading source viewer" />}>
              <SourceViewerPage />
            </Suspense>
          </div>
        </BrandProvider>
        {sessionTimeoutDialog}
      </>
    );
  }

  const sidebarHeaderContent = (
    <ChatKnowledgeSpaceControl
      activeSpacePath={chat.activeSpacePath}
      allowAllSpaces={isGlobalAdmin(user)}
      documentCount={sidebarDocumentCount}
      documentsLoading={documentSummary.summaryQuery.isLoading}
      onActiveSpaceChange={chat.changeActiveSpacePath}
      spaceSwitchDisabled={resolvedRoute === "chat" && chat.hasPendingGeneration}
      spaces={sidebarSpaceOptions}
    />
  );

  return (
    <BrandProvider value={branding}>
    <PrudentiaSidebarHeaderProvider
      isLightMode={isLightMode}
      onToggleTheme={branding.theme_mode === "user" ? () => setIsLightMode((value) => !value) : undefined}
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
            onChooseQuerySource={chat.chooseQuerySource}
            onExpandSourceSearch={chat.expandSourceSearch}
            onLogout={handleLogout}
            onNavigate={navigate}
            onQuestionChange={chat.setQuestion}
            onQuestionSubmit={chat.handleQuestionSubmit}
            onCancelReply={chat.cancelReply}
            onReplyToTurn={chat.replyToTurn}
            onReset={chat.resetChat}
            onRetryArtifactJob={chat.retryArtifactJob}
            onSelectSource={chat.setSelectedSource}
            onSelectedQuerySourceChange={chat.setSelectedQuerySourceId}
            onSourceModeChange={chat.setSourceMode}
            question={chat.question}
            replyTarget={chat.replyTarget}
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
            selectedSourceTurnId={chat.selectedSourceTurnId}
            sourceMode={chat.sourceMode}
            user={user}
          />
        ) : null}
        {resolvedRoute === "knowledge-spaces" ? <PrudentiaDocumentsPage onLogout={handleLogout} onNavigate={navigate} user={user} view="spaces" /> : null}
        {resolvedRoute === "document-overview" ? <PrudentiaDocumentOverviewPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {resolvedRoute === "documents" ? <PrudentiaDocumentsPage onLogout={handleLogout} onNavigate={navigate} user={user} view="documents" /> : null}
        {resolvedRoute === "document-trash" ? <PrudentiaDocumentsPage onLogout={handleLogout} onNavigate={navigate} user={user} view="trash" /> : null}
        {resolvedRoute === "upload" || resolvedRoute === "abbreviation-glossary" ? <PrudentiaUploadPage batchItems={pdfUpload.batchItems} cancelingJobId={pdfUpload.cancelingJobId} currentDocuments={inventory.documents} currentUser={user} mode={resolvedRoute === "abbreviation-glossary" ? "glossary" : "documents"} onCancelIngestJob={pdfUpload.cancelJob} onClearUploadJobs={pdfUpload.clearUploadJobs} onLogout={handleLogout} onNavigate={navigate} onPdfDraftChange={pdfUpload.updatePdfDraft} onPdfSubmit={pdfUpload.onPdfSubmit} pdfDraft={pdfUpload.pdfDraft} selectionError={pdfUpload.selectionError} uploadPending={pdfUpload.uploadMutation.isPending} /> : null}
        {resolvedRoute === "document-extraction" ? <PrudentiaSourceManagementPage onLogout={handleLogout} onNavigate={navigate} user={user} variant="folder_sources" /> : null}
        {resolvedRoute === "database-connectors" ? <PrudentiaSourceManagementPage onLogout={handleLogout} onNavigate={navigate} user={user} variant="database_connectors" /> : null}
        {resolvedRoute === "ingestion-jobs" ? <PrudentiaIngestionJobsPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {resolvedRoute === "ingestion-health" ? <PrudentiaIngestionHealthPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {resolvedRoute === "review" ? <PrudentiaReviewQueuePage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {resolvedRoute === "access" ? <PrudentiaAccessPage currentUser={user} onAuthChanged={auth.authChanged} onLogout={handleLogout} onNavigate={navigate} /> : null}
        {resolvedRoute === "account" ? <PrudentiaAccountPage currentUser={user} isLoggingOut={auth.logoutMutation.isPending} onAuthChanged={auth.authChanged} onLogout={handleLogout} onNavigate={navigate} /> : null}
        {resolvedRoute === "settings" ? <PrudentiaSettingsPage currentUser={user} onLogout={handleLogout} onNavigate={navigate} /> : null}

        {resolvedRoute === "overview" ? <PrudentiaOverviewPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
        {resolvedRoute === "operational-analytics" ? <PrudentiaAnalyticsPage onLogout={handleLogout} onNavigate={navigate} user={user} /> : null}
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
    </BrandProvider>
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

function documentCountInActiveSpace(
  groups: DocumentGroupCount[],
  total: number,
  activeSpacePath: string | null,
): number {
  if (!activeSpacePath) return total;
  return groups
    .filter((group) => isDocumentInSpace(group.group_path, activeSpacePath))
    .reduce((count, group) => count + group.count, 0);
}

function knowledgeSpaceOptions(
  user: AuthUser | null,
  groups: DocumentGroupCount[],
): ChatSpaceOption[] {
  if (!user) return [];
  const paths = isGlobalAdmin(user)
    ? groups.map((group) => group.group_path)
    : user.group_paths ?? [];
  return userSpacesFromPaths(paths).map((space) => ({
    documentCount: groups
      .filter((group) => isDocumentInSpace(group.group_path, space.path))
      .reduce((count, group) => count + group.count, 0),
    name: space.name,
    path: space.path,
  }));
}

function setOptionalStyle(name: string, value: string | null) {
  if (value) document.documentElement.style.setProperty(name, value);
  else document.documentElement.style.removeProperty(name);
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
