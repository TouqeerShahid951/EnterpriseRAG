import { DocumentRecoveryActivity } from "@/features/documents/components/DocumentRecoveryActivity";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Archive, CalendarClock, CheckCircle2, FileCheck2, FileClock, FilePlus2, FileSearch, FolderOpen, History, Hourglass, Trash2, Upload, XCircle } from "lucide-react";

import { documentsApi, ingestJobsApi } from "@/lib/api/contracts";
import { InlineMessage, Skeleton } from "@/components/layout/Common";
import { PrudentiaWorkspace } from "@/components/layout/PrudentiaWorkspace";
import { AttentionList, Empty, LifecycleStrip, OverviewStatus, PanelHeader, PanelSkeleton, RecentActivityList, SpaceList, StatusShortcutGrid, type LifecycleItem, type NextStep, type SpaceRow, type StatusShortcut } from "@/features/documents/components/DocumentOverviewPanels";
import { canAccessRoute, type NavigateOptions, type RouteId } from "@/routes/routes";
import type { DocumentIngestStatus, DocumentOverview, User as AuthUser } from "@/types/api";
import { UsageRing } from "@/components/charts/UsageRing";
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
    refetchInterval: (query) => query.state.data?.items.some((job) => isActiveJobStatus(job.status)) ? 2500 : 15000,
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
  const unknownCount = overview?.unknown_current ?? 0;
  const cancelledCount = overview?.cancelled_current ?? 0;
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
    processingCount, failedCount, reviewCount, unknownCount, cancelledCount,
  });
  const statusShortcuts = buildStatusShortcuts({ canViewDocuments, cancelledCount, unknownCount, failedCount, indexedCurrentCount, processingCount, reviewCount, user });
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
        <div className="sv-page-inner sv-page-inner-dashboard max-w-none overview-dashboard document-dashboard">
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
              <section className="document-dashboard-summary">
                <div className="document-dashboard-metrics" aria-label="Document workspace summary">
                  <Metric icon={FileSearch} detail="Visible library content" label="Library documents" loading={overviewQuery.isLoading} value={libraryDocuments} />
                  <Metric icon={FileCheck2} detail="Latest active versions" label="Current versions" loading={overviewQuery.isLoading} value={currentCount} tone="success" />
                  <Metric icon={Hourglass} detail="Queued or running" label="Active processing" loading={overviewQuery.isLoading} value={processingCount} />
                  <Metric icon={AlertTriangle} detail="Failed, review or unknown" label="Needs attention" loading={overviewQuery.isLoading} value={needsAttention} tone={needsAttention > 0 ? "warning" : "success"} />
                  <Metric icon={Trash2} detail="Deleted library items" label="Trash" loading={overviewQuery.isLoading} value={overview?.trash ?? 0} />
                </div>
                <div className="document-dashboard-readiness">
                  <section className="sv-panel overview-panel document-readiness-chart" aria-labelledby="document-readiness-title">
                    <header className="overview-panel-heading"><div><h2 id="document-readiness-title">Retrieval readiness</h2><p>Share of current documents indexed</p></div></header>
                    <div className="document-readiness-visual">
                      {overviewQuery.isLoading ? <Skeleton className="h-28 w-28" /> : <UsageRing value={currentCount ? indexedCurrentCount / currentCount * 100 : null} label="Current documents indexed" detail="indexed" tone="success" />}
                      <div><strong>{overviewQuery.isLoading ? "—" : indexedCurrentCount.toLocaleString()}</strong><p>of {overviewQuery.isLoading ? "—" : currentCount.toLocaleString()} current documents</p><small>Based on recorded ingestion status</small></div>
                    </div>
                  </section>
                {overviewQuery.isLoading ? <section className="sv-panel"><PanelSkeleton rows={2} /></section> : <OverviewStatus
                  nextStep={nextStep}
                  onNavigate={onNavigate}
                />}
                </div>
                <div className="sv-panel document-state-panel">
                <header className="overview-panel-heading"><div><h2>Current document states</h2><p>Each current document appears in exactly one category. Select a state to inspect it.</p></div><span className="overview-status">{overviewQuery.isLoading ? "Loading" : `${currentCount} total`}</span></header>
                <p className="px-4 py-2 text-label-md text-secondary">All documents visible to your account · Current versions only · {overviewQuery.dataUpdatedAt ? `Updated ${new Date(overviewQuery.dataUpdatedAt).toLocaleTimeString()}` : "Loading snapshot"}</p>
                <StatusShortcutGrid total={currentCount} loading={overviewQuery.isLoading} onNavigate={onNavigate} shortcuts={statusShortcuts} />
                </div>
                <section className="sv-panel document-lifecycle-panel" aria-label="Version and retention overview"><LifecycleStrip loading={overviewQuery.isLoading} onNavigate={onNavigate} items={lifecycleItems} /></section>
              </section>

              {canViewJobs ? <DocumentRecoveryActivity onNavigate={onNavigate} /> : null}

              <div className="document-dashboard-panels">
                <section className="sv-panel overflow-hidden">
                  <PanelHeader actionIcon={FileSearch} actionLabel="Open Attention" actionRoute="documents" actionSearch="?lifecycle=current&ingest=attention" countLabel={overviewQuery.isLoading ? "Loading" : `${attentionDocs.length} of ${needsAttention} affected`} description="Inspect the cause and follow the next recovery step." onNavigate={onNavigate} title="Needs attention" />
                  {overviewQuery.isLoading ? <PanelSkeleton /> : attentionDocs.length ? <AttentionList documents={attentionDocs} onNavigate={onNavigate} canViewJobs={canViewJobs} /> : <Empty icon={CheckCircle2} title="No document issues" text="The visible current library has no failed, unknown, or review-required documents." />}
                </section>
                {canViewJobs ? (
                  <section className="sv-panel overflow-hidden">
                    <PanelHeader actionIcon={History} actionLabel="Open Activity" actionRoute="ingestion-jobs" countLabel={recentActivityQuery.isLoading ? "Loading" : `${recentActivityQuery.data?.items.length ?? 0} latest`} description="Latest confirmed ingestion outcomes across visible spaces." onNavigate={onNavigate} title="Recent Activity" />
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

function Metric({ detail, icon: Icon, label, loading, tone, value }: { detail: string; icon: typeof FileSearch; label: string; loading: boolean; tone?: "success" | "warning"; value: number }) {
  return <div className="sv-panel overview-summary-card" data-tone={tone} aria-busy={loading}>
    <span className="overview-summary-icon" aria-hidden="true"><Icon size={19} /></span><p className="overview-summary-label">{label}</p>
    {loading ? <Skeleton className="my-3 h-9 w-16" /> : <p className="overview-summary-value">{value.toLocaleString()}</p>}
    <p className="overview-caption">{detail}</p>
  </div>;
}

export function buildNextStep({ canOpenFolderSources, canUpload, canViewJobs, documentsCount, indexedCurrentCount, needsAttention, processingCount, failedCount, reviewCount, unknownCount, cancelledCount }: NextStepInput): NextStep {
  if (needsAttention > 0) {
    const filter = failedCount === needsAttention ? "failed" : reviewCount === needsAttention ? "human_review" : unknownCount === needsAttention ? "unknown" : "attention";
    return { detail: `${failedCount} failed · ${reviewCount} awaiting human review · ${unknownCount} unknown. ${processingCount} processing; ${cancelledCount} cancelled.`, primaryLabel: filter === "failed" ? "Investigate failures" : filter === "human_review" ? "Inspect review documents" : filter === "unknown" ? "Inspect unknown states" : "Inspect affected documents", primaryRoute: "documents", primarySearch: `?lifecycle=current&ingest=${filter}`, secondaryLabel: canViewJobs ? "Open Activity" : undefined, secondaryRoute: canViewJobs ? "ingestion-jobs" : undefined, title: filter === "failed" ? `${failedCount} document${failedCount === 1 ? "" : "s"} failed ingestion` : "Ingestion attention needed", tone: "warning" };
  }
  if (processingCount > 0) return { detail: `${processingCount} current document${processingCount === 1 ? " is" : "s are"} still moving into the library.`, primaryLabel: canViewJobs ? "Track Activity" : "Open Processing", primaryRoute: canViewJobs ? "ingestion-jobs" : "documents", primarySearch: canViewJobs ? "?status=processing" : "?ingest=processing", secondaryLabel: "Open Documents", secondaryRoute: "documents", secondarySearch: "?ingest=processing", title: "Intake is running", tone: "active" };
  if (cancelledCount > 0) return { title: "Ingestion cancelled", detail: `${cancelledCount} current document${cancelledCount === 1 ? " has" : "s have"} cancelled ingestion. ${indexedCurrentCount} indexed; no failed or review-required documents.`, primaryLabel: "Inspect cancelled documents", primaryRoute: "documents", primarySearch: "?lifecycle=current&ingest=cancelled", tone: "empty" };
  if (documentsCount === 0) return { detail: canOpenFolderSources ? "Start intake by adding files or setting up a folder source." : canUpload ? "Start intake by adding files to a writable Knowledge Space." : "Browse Knowledge Spaces to confirm where library content should appear.", primaryLabel: canUpload ? "Add Files" : "Open Knowledge Spaces", primaryRoute: canUpload ? "upload" : "knowledge-spaces", secondaryLabel: canOpenFolderSources ? "Folder Sources" : undefined, secondaryRoute: canOpenFolderSources ? "document-extraction" : undefined, title: "Library is empty", tone: "empty" };
  return { detail: `${indexedCurrentCount} current document${indexedCurrentCount === 1 ? " is" : "s are"} indexed and ready for library work.`, primaryLabel: "Open Indexed", primaryRoute: "documents", primarySearch: "?lifecycle=current&ingest=indexed", secondaryLabel: "Manage Spaces", secondaryRoute: "knowledge-spaces", title: "No ingestion issues detected", tone: "success" };
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

function buildStatusShortcuts({ canViewDocuments, cancelledCount, unknownCount, failedCount, indexedCurrentCount, processingCount, reviewCount, user }: StatusShortcutInput): StatusShortcut[] {
  const shortcuts: StatusShortcut[] = [
    { detail: "current and searchable", icon: CheckCircle2, label: "Indexed", route: "documents", search: "?lifecycle=current&ingest=indexed", tone: "success", value: indexedCurrentCount },
    { detail: "current queued library items", icon: Hourglass, label: "Processing", route: "documents", search: "?lifecycle=current&ingest=processing", tone: "active", value: processingCount },
    { detail: "human review required", icon: AlertTriangle, label: "Needs Review", route: "documents", search: "?lifecycle=current&ingest=human_review", tone: reviewCount > 0 ? "warning" : undefined, value: reviewCount },
    { detail: "ingestion status unavailable", icon: AlertTriangle, label: "Unknown", route: "documents", search: "?lifecycle=current&ingest=unknown", tone: unknownCount > 0 ? "warning" : undefined, value: unknownCount },
    { detail: "stopped without completion", icon: XCircle, label: "Cancelled", route: "documents", search: "?lifecycle=current&ingest=cancelled", value: cancelledCount },
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
type NextStepInput = { failedCount: number; reviewCount: number; unknownCount: number; cancelledCount: number; canOpenFolderSources: boolean; canUpload: boolean; canViewJobs: boolean; documentsCount: number; indexedCurrentCount: number; needsAttention: number; processingCount: number };
type StatusShortcutInput = { cancelledCount: number; unknownCount: number; canViewDocuments: boolean; failedCount: number; indexedCurrentCount: number; processingCount: number; reviewCount: number; user: AuthUser };
