import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Archive, CalendarClock, CheckCircle2, FileCheck2, FileClock, FilePlus2, FileSearch, FolderOpen, History, Hourglass, Trash2, Upload, XCircle } from "lucide-react";

import { documentsApi, ingestJobsApi } from "@/lib/api/contracts";
import { InlineMessage, Skeleton } from "@/components/layout/Common";
import { PrudentiaWorkspace } from "@/components/layout/PrudentiaWorkspace";
import { AttentionList, Empty, LifecycleStrip, OverviewStatus, PanelHeader, PanelSkeleton, RecentActivityList, SpaceList, StatusShortcutGrid, type LifecycleItem, type NextStep, type SpaceRow, type StatusShortcut } from "@/features/documents/components/DocumentOverviewPanels";
import { canAccessRoute, type NavigateOptions, type RouteId } from "@/routes/routes";
import type { DocumentIngestStatus, DocumentOverview, User as AuthUser } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";

const EXPIRING_SOON_DAYS = 30;

export function PrudentiaDocumentOverviewPage({ onLogout, onNavigate, user }: Props) {
  const canViewJobs = canAccessRoute(user, "ingestion-jobs");
  const canViewDocuments = canAccessRoute(user, "documents");
  const overviewQuery = useQuery({
    queryKey: ["documents", "overview"],
    queryFn: documentsApi.overview,
    refetchInterval: (query) => query.state.data?.processing_current ? 3000 : 15000,
    staleTime: 3000,
    retry: false,
  });
  const recentActivityQuery = useQuery({
    queryKey: ["ingest-jobs", "recent", "overview"],
    queryFn: () => ingestJobsApi.list({ limit: 5, offset: 0 }),
    enabled: canViewJobs,
    refetchInterval: (query) => query.state.data?.items.some((job) => isActiveJobStatus(job.status)) ? 2500 : false,
    staleTime: 4000,
    retry: false,
  });
  const overview = overviewQuery.data;
  const libraryDocuments = overview?.library_documents ?? 0;
  const currentCount = overview?.current_versions ?? 0;
  const indexedCurrentCount = overview?.indexed_current ?? 0;
  const processingCount = overview?.processing_current ?? 0;
  const reviewCount = overview?.review_current ?? 0;
  const failedCount = overview?.failed_current ?? 0;
  const needsAttention = overview?.needs_attention ?? 0;
  const attentionDocs = overview?.attention_documents ?? [];
  const spaceRows = overviewSpaces(overview);
  const canUpload = canAccessRoute(user, "upload");
  const canOpenFolderSources = canAccessRoute(user, "document-extraction");
  const canOpenSpaces = canAccessRoute(user, "knowledge-spaces");
  const isGenuinelyEmpty = isDocumentWorkspaceEmpty({
    jobHistoryKnown: !canViewJobs || recentActivityQuery.isSuccess,
    jobHistoryTotal: recentActivityQuery.data?.total ?? 0,
    overviewKnown: overviewQuery.isSuccess,
    libraryDocuments,
    trash: overview?.trash ?? 0,
  });
  const nextStep = buildNextStep({
    canOpenFolderSources,
    canUpload,
    canViewJobs,
    documentsCount: libraryDocuments,
    indexedCurrentCount,
    needsAttention,
    processingCount,
  });
  const statusShortcuts = buildStatusShortcuts({ canViewDocuments, failedCount, indexedCurrentCount, processingCount, reviewCount, user });
  const lifecycleItems = buildLifecycleItems({
    currentCount,
    expiringSoonCount: overview?.expiring_soon_current ?? 0,
    supersededCount: overview?.superseded_versions ?? 0,
    trashCount: overview?.trash ?? 0,
    user,
  });
  return (
    <PrudentiaWorkspace activeRoute="document-overview" onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page" id="main-content">
        <div className="sv-page-inner sv-page-inner-dashboard max-w-none">
          <header className="sv-page-header">
            <div>
              <p className="sv-eyebrow">Document Library</p>
              <h1 className="sv-page-title">Document Overview</h1>
              <p className="sv-page-subtitle">Move documents through intake, then manage searchable library content from one organized workspace.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {canAccessRoute(user, "upload") ? <button type="button" onClick={() => onNavigate("upload")} className="sv-action-primary"><Upload size={16} /> Add Files</button> : null}
              {canViewJobs ? <button type="button" onClick={() => onNavigate("ingestion-jobs")} className="sv-action-secondary"><FileClock size={16} /> Activity</button> : null}
            </div>
          </header>

          {recentActivityQuery.isError ? <InlineMessage tone="warning">{errorMessage(recentActivityQuery.error, "Recent activity could not be loaded.")}</InlineMessage> : null}

          {overviewQuery.isError ? (
            <section className="sv-panel p-6" role="alert">
              <AlertTriangle className="text-error" size={22} aria-hidden="true" />
              <h2 className="mt-3 text-headline-sm text-on-surface">Document overview unavailable</h2>
              <p className="mt-2 text-body-md text-on-surface-variant">{errorMessage(overviewQuery.error, "The document snapshot could not be loaded.")}</p>
              <button type="button" className="sv-action-secondary mt-4" onClick={() => void overviewQuery.refetch()}>Retry</button>
            </section>
          ) : isGenuinelyEmpty ? (
            <DocumentEmptyWorkspace
              canOpenFolderSources={canOpenFolderSources}
              canOpenSpaces={canOpenSpaces}
              canUpload={canUpload}
              onNavigate={onNavigate}
            />
          ) : (
            <>
              <section className="sv-panel overflow-hidden">
                <div className="knowledge-job-metrics" aria-label="Document workspace summary">
                  <Metric label="Library documents" loading={overviewQuery.isLoading} value={libraryDocuments} />
                  <Metric label="Current versions" loading={overviewQuery.isLoading} value={currentCount} tone="success" />
                  <Metric label="Active processing" loading={overviewQuery.isLoading} value={processingCount} />
                  <Metric label="Needs attention" loading={overviewQuery.isLoading} value={needsAttention} tone={needsAttention > 0 ? "warning" : "success"} />
                  <Metric label="Trash" loading={overviewQuery.isLoading} value={overview?.trash ?? 0} />
                </div>
                <OverviewStatus
                  indexedCurrentCount={indexedCurrentCount}
                  needsAttention={needsAttention}
                  nextStep={nextStep}
                  onNavigate={onNavigate}
                  processingCount={processingCount}
                />
                <StatusShortcutGrid loading={overviewQuery.isLoading} onNavigate={onNavigate} shortcuts={statusShortcuts} />
                <LifecycleStrip loading={overviewQuery.isLoading} onNavigate={onNavigate} items={lifecycleItems} />
              </section>

              <div className={canViewJobs ? "mt-4 grid gap-4 xl:grid-cols-3" : "mt-4 grid gap-4 lg:grid-cols-2"}>
                <section className="sv-panel overflow-hidden">
                  <PanelHeader actionIcon={FileSearch} actionLabel="Open Attention" actionRoute="documents" actionSearch="?ingest=active" countLabel={overviewQuery.isLoading ? "Loading" : `${attentionDocs.length} shown`} description="Current failed, unknown, and review-required documents appear here." onNavigate={onNavigate} title="Needs Attention" />
                  {overviewQuery.isLoading ? <PanelSkeleton /> : attentionDocs.length ? <AttentionList documents={attentionDocs} onNavigate={onNavigate} /> : <Empty icon={CheckCircle2} title="No document issues" text="The visible current library has no failed, unknown, or review-required documents." />}
                </section>
                {canViewJobs ? (
                  <section className="sv-panel overflow-hidden">
                    <PanelHeader actionIcon={History} actionLabel="Open Activity" actionRoute="ingestion-jobs" countLabel={recentActivityQuery.isLoading ? "Loading" : `${recentActivityQuery.data?.items.length ?? 0} latest`} description="Latest intake, folder, restore, and reingestion runs across visible spaces." onNavigate={onNavigate} title="Recent Activity" />
                    <RecentActivityList isLoading={recentActivityQuery.isLoading} jobs={recentActivityQuery.data?.items ?? []} onNavigate={onNavigate} />
                  </section>
                ) : null}
                <section className="sv-panel overflow-hidden">
                  <PanelHeader actionIcon={FolderOpen} actionLabel="Open Spaces" actionRoute="knowledge-spaces" countLabel={`${spaceRows.length} spaces`} description="Spaces are ranked by attention items first, then document volume." onNavigate={onNavigate} title="Library by Space" />
                  {overviewQuery.isLoading ? <PanelSkeleton /> : spaceRows.length ? <SpaceList rows={spaceRows.slice(0, 6)} onNavigate={onNavigate} /> : <Empty icon={FolderOpen} actionLabel={canUpload ? "Add Files" : "Open Spaces"} actionRoute={canUpload ? "upload" : "knowledge-spaces"} onNavigate={onNavigate} title="No documents yet" text="Add files or open Knowledge Spaces to prepare the library." />}
                </section>
              </div>
            </>
          )}
        </div>
      </main>
    </PrudentiaWorkspace>
  );
}

function DocumentEmptyWorkspace({ canOpenFolderSources, canOpenSpaces, canUpload, onNavigate }: DocumentEmptyWorkspaceProps) {
  const primaryRoute: RouteId | null = canUpload ? "upload" : canOpenSpaces ? "knowledge-spaces" : null;
  const secondaryRoute: RouteId | null = canOpenFolderSources ? "document-extraction" : canUpload && canOpenSpaces ? "knowledge-spaces" : null;

  return (
    <section className="sv-panel document-overview-empty-state overflow-hidden" aria-labelledby="document-empty-title">
      <div className="grid gap-8 p-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(18rem,0.85fr)] lg:p-8">
        <div className="max-w-2xl">
          <span className="mb-5 flex h-12 w-12 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
            <FilePlus2 size={22} aria-hidden="true" />
          </span>
          <p className="sv-eyebrow">Library setup</p>
          <h2 id="document-empty-title" className="mt-2 text-headline-md text-on-surface">Build your searchable evidence library</h2>
          <p className="mt-3 text-body-lg text-on-surface-variant">
            The library is empty for your current access scope. Add the first trusted source and Prudentia will track it from ingestion through retrieval readiness.
          </p>
          {primaryRoute ? (
            <div className="mt-6 flex flex-wrap gap-3">
              <button type="button" className="sv-action-primary" onClick={() => onNavigate(primaryRoute)}>
                {canUpload ? <Upload size={16} aria-hidden="true" /> : <FolderOpen size={16} aria-hidden="true" />}
                {canUpload ? "Add first files" : "Open Knowledge Spaces"}
              </button>
              {secondaryRoute ? (
                <button type="button" className="sv-action-secondary" onClick={() => onNavigate(secondaryRoute)}>
                  {secondaryRoute === "document-extraction" ? "Set up a folder source" : "Browse Knowledge Spaces"}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
        <ol className="document-overview-empty-steps border-t border-surface-border pt-2 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0" aria-label="Library setup steps">
          <SetupStep index="1" title="Confirm ownership" detail="Choose the Knowledge Space that should own the source and its access boundary." />
          <SetupStep index="2" title="Add trusted material" detail="Upload files or configure a governed folder source for recurring intake." />
          <SetupStep index="3" title="Verify retrieval readiness" detail="Follow ingestion activity until the source is indexed, then test it in Query Intelligence." />
        </ol>
      </div>
    </section>
  );
}

function SetupStep({ detail, index, title }: { detail: string; index: string; title: string }) {
  return (
    <li className="flex gap-4 border-b border-surface-border py-4 first:pt-2 last:border-b-0 last:pb-0">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-primary/30 text-label-md font-semibold text-primary" aria-hidden="true">{index}</span>
      <span>
        <strong className="block text-headline-sm text-on-surface">{title}</strong>
        <span className="mt-1 block text-body-md text-on-surface-variant">{detail}</span>
      </span>
    </li>
  );
}

export function isDocumentWorkspaceEmpty({ jobHistoryKnown, jobHistoryTotal, libraryDocuments, overviewKnown, trash }: DocumentWorkspaceEmptyInput) {
  return overviewKnown
    && jobHistoryKnown
    && libraryDocuments === 0
    && jobHistoryTotal === 0
    && trash === 0;
}

function Metric({ label, loading, tone, value }: { label: string; loading: boolean; tone?: "success" | "warning"; value: number }) {
  const className = tone === "success" ? "knowledge-context-metric knowledge-context-metric-success" : "knowledge-context-metric";
  return <div className={className} data-tone={tone}><span>{label}</span>{loading ? <Skeleton className="mt-1 h-6 w-12" /> : <strong>{value}</strong>}</div>;
}

function buildNextStep({ canOpenFolderSources, canUpload, canViewJobs, documentsCount, indexedCurrentCount, needsAttention, processingCount }: NextStepInput): NextStep {
  if (needsAttention > 0) return { detail: `${needsAttention} current document${needsAttention === 1 ? " needs" : "s need"} review before the library is fully healthy.`, primaryLabel: "Review Documents", primaryRoute: "documents", primarySearch: "?ingest=active", secondaryLabel: canViewJobs ? "Open Activity" : undefined, secondaryRoute: canViewJobs ? "ingestion-jobs" : undefined, title: "Attention needed", tone: "warning" };
  if (processingCount > 0) return { detail: `${processingCount} current document${processingCount === 1 ? " is" : "s are"} still moving into the library.`, primaryLabel: canViewJobs ? "Track Activity" : "Open Processing", primaryRoute: canViewJobs ? "ingestion-jobs" : "documents", primarySearch: canViewJobs ? "?status=processing" : "?ingest=processing", secondaryLabel: "Open Documents", secondaryRoute: "documents", secondarySearch: "?ingest=processing", title: "Intake is running", tone: "active" };
  if (documentsCount === 0) return { detail: canOpenFolderSources ? "Start intake by adding files or setting up a folder source." : canUpload ? "Start intake by adding files to a writable Knowledge Space." : "Browse Knowledge Spaces to confirm where library content should appear.", primaryLabel: canUpload ? "Add Files" : "Open Knowledge Spaces", primaryRoute: canUpload ? "upload" : "knowledge-spaces", secondaryLabel: canOpenFolderSources ? "Folder Sources" : undefined, secondaryRoute: canOpenFolderSources ? "document-extraction" : undefined, title: "Library is empty", tone: "empty" };
  return { detail: `${indexedCurrentCount} current document${indexedCurrentCount === 1 ? " is" : "s are"} indexed and ready for library work.`, primaryLabel: "Open Indexed", primaryRoute: "documents", primarySearch: "?lifecycle=current&ingest=indexed", secondaryLabel: "Manage Spaces", secondaryRoute: "knowledge-spaces", title: "Library ready", tone: "success" };
}

function buildLifecycleItems({ currentCount, expiringSoonCount, supersededCount, trashCount, user }: LifecycleInput): LifecycleItem[] {
  const items: LifecycleItem[] = [
    { detail: "latest active versions", icon: FileCheck2, label: "Current", route: "documents", search: "?lifecycle=current", tone: "success", value: currentCount },
    { detail: "replaced versions retained", icon: Archive, label: "Superseded", route: "documents", search: "?lifecycle=superseded", value: supersededCount },
    { detail: `${EXPIRING_SOON_DAYS}-day review window`, icon: CalendarClock, label: "Expiring soon", route: "documents", tone: expiringSoonCount > 0 ? "warning" : undefined, value: expiringSoonCount },
    { detail: "deleted library items", icon: Trash2, label: "In Trash", route: "document-trash", tone: trashCount > 0 ? "warning" : undefined, value: trashCount },
  ];
  return items.filter((item) => !item.route || canAccessRoute(user, item.route));
}

function buildStatusShortcuts({ canViewDocuments, failedCount, indexedCurrentCount, processingCount, reviewCount, user }: StatusShortcutInput): StatusShortcut[] {
  const shortcuts: StatusShortcut[] = [
    { detail: "current and searchable", icon: CheckCircle2, label: "Indexed", route: "documents", search: "?lifecycle=current&ingest=indexed", tone: "success", value: indexedCurrentCount },
    { detail: "current queued library items", icon: Hourglass, label: "Processing", route: "documents", search: "?lifecycle=current&ingest=processing", tone: "active", value: processingCount },
    { detail: "human review required", icon: AlertTriangle, label: "Needs Review", route: "documents", search: "?ingest=human_review", tone: reviewCount > 0 ? "warning" : undefined, value: reviewCount },
    { detail: "current failed documents", icon: XCircle, label: "Failed", route: "documents", search: "?lifecycle=current&ingest=failed", tone: failedCount > 0 ? "warning" : undefined, value: failedCount },
  ];
  return shortcuts.filter((item) => (item.route === "documents" ? canViewDocuments : canAccessRoute(user, item.route)));
}

function overviewSpaces(overview: DocumentOverview | undefined): SpaceRow[] {
  return (overview?.spaces ?? [])
    .map((space) => ({
      attention: space.failed_current + space.review_current + space.unknown_current,
      count: space.library_documents,
      path: space.group_path,
    }))
    .sort((left, right) => right.attention - left.attention || right.count - left.count || left.path.localeCompare(right.path));
}

function isActiveJobStatus(status: DocumentIngestStatus) {
  return status === "scheduled" || status === "queued" || status === "processing";
}

type Props = { onLogout: () => void; onNavigate: (route: RouteId, options?: NavigateOptions) => void; user: AuthUser };
type DocumentEmptyWorkspaceProps = { canOpenFolderSources: boolean; canOpenSpaces: boolean; canUpload: boolean; onNavigate: Props["onNavigate"] };
type DocumentWorkspaceEmptyInput = { jobHistoryKnown: boolean; jobHistoryTotal: number; libraryDocuments: number; overviewKnown: boolean; trash: number };
type LifecycleInput = { currentCount: number; expiringSoonCount: number; supersededCount: number; trashCount: number; user: AuthUser };
type NextStepInput = { canOpenFolderSources: boolean; canUpload: boolean; canViewJobs: boolean; documentsCount: number; indexedCurrentCount: number; needsAttention: number; processingCount: number };
type StatusShortcutInput = { canViewDocuments: boolean; failedCount: number; indexedCurrentCount: number; processingCount: number; reviewCount: number; user: AuthUser };
