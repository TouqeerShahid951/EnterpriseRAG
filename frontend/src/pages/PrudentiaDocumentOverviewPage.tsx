import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Archive, CalendarClock, CheckCircle2, FileCheck2, FileClock, FileSearch, FolderOpen, History, Hourglass, Trash2, Upload, XCircle } from "lucide-react";

import { documentsApi, ingestJobsApi } from "../api/contracts";
import { InlineMessage, Skeleton } from "../components/layout/Common";
import { PrudentiaWorkspace } from "../components/layout/PrudentiaWorkspace";
import { AttentionList, Empty, LifecycleStrip, OverviewStatus, PanelHeader, PanelSkeleton, RecentActivityList, SpaceList, StatusShortcutGrid, type LifecycleItem, type NextStep, type SpaceRow, type StatusShortcut } from "./document/DocumentOverviewPanels";
import { canAccessRoute, type NavigateOptions, type RouteId } from "../routes";
import { isUploadTerminalStatus } from "../state/uploadJobProgress";
import type { Document, DocumentIngestStatus, User as AuthUser } from "../types/api";
import type { UploadBatchItemView } from "../types/chat";
import { errorMessage } from "../utils/format";

const EXPIRING_SOON_DAYS = 30;

export function PrudentiaDocumentOverviewPage({ documents, documentsLoading, onLogout, onNavigate, uploadJobs, user }: Props) {
  const canViewJobs = canAccessRoute(user, "ingestion-jobs");
  const canViewDocuments = canAccessRoute(user, "documents");
  const trashQuery = useQuery({
    queryKey: ["documents", "list", "deleted"],
    queryFn: () => documentsApi.list({ state: "deleted" }),
    enabled: canAccessRoute(user, "document-trash"),
    staleTime: 15000,
    retry: false,
  });
  const jobsSummaryQuery = useQuery({
    queryKey: ["ingest-jobs", "summary"],
    queryFn: () => ingestJobsApi.summary(),
    enabled: canViewJobs,
    refetchInterval: 5000,
    staleTime: 4000,
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
  const spaceRows = useMemo(() => summarizeSpaces(documents), [documents]);
  const attentionDocuments = documents.filter((doc) => isAttentionStatus(doc.ingest_status));
  const attentionDocs = attentionDocuments.slice(0, 5);
  const activeBrowserJobs = uploadJobs.filter((item) => item.requestState !== "failed" && !isUploadTerminalStatus(item.job?.status)).length;
  const failedBrowserJobs = uploadJobs.filter((item) => item.requestState === "failed" || item.job?.status === "failed").length;
  const summary = jobsSummaryQuery.data;
  const activeJobs = (summary?.active ?? 0) + activeBrowserJobs;
  const needsAttention = attentionDocuments.length + failedBrowserJobs;
  const currentCount = documents.filter((doc) => doc.is_current).length;
  const supersededCount = documents.length - currentCount;
  const indexedCurrentCount = documents.filter((doc) => doc.is_current && doc.ingest_status === "complete").length;
  const processingCount = documents.filter((doc) => isProcessingStatus(doc.ingest_status)).length + activeBrowserJobs;
  const reviewCount = documents.filter((doc) => doc.ingest_status === "human_review").length;
  const failedCount = documents.filter((doc) => doc.ingest_status === "failed").length + failedBrowserJobs;
  const expiringSoonCount = documents.filter((doc) => doc.is_current && isExpiringSoon(doc.expiry_date)).length;
  const trashCount = trashQuery.data?.total ?? 0;
  const nextStep = buildNextStep({
    activeJobs,
    canOpenFolderSources: canAccessRoute(user, "document-extraction"),
    canUpload: canAccessRoute(user, "upload"),
    canViewJobs,
    documentsCount: documents.length,
    indexedCurrentCount,
    needsAttention,
  });
  const statusShortcuts = buildStatusShortcuts({ canViewJobs, canViewDocuments, failedCount, indexedCurrentCount, processingCount, reviewCount, user });
  const lifecycleItems = buildLifecycleItems({ currentCount, expiringSoonCount, supersededCount, trashCount, user });
  return (
    <PrudentiaWorkspace activeRoute="document-overview" onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page" id="main-content">
        <div className="sv-page-inner max-w-none">
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

          {jobsSummaryQuery.isError ? <InlineMessage tone="warning">{errorMessage(jobsSummaryQuery.error, "Ingestion summary could not be loaded.")}</InlineMessage> : null}
          {trashQuery.isError ? <InlineMessage tone="warning">{errorMessage(trashQuery.error, "Trash count could not be loaded.")}</InlineMessage> : null}
          {recentActivityQuery.isError ? <InlineMessage tone="warning">{errorMessage(recentActivityQuery.error, "Recent activity could not be loaded.")}</InlineMessage> : null}

          <section className="sv-panel overflow-hidden">
            <div className="knowledge-job-metrics" aria-label="Document workspace summary">
              <Metric label="Active documents" loading={documentsLoading} value={documents.length} />
              <Metric label="Current versions" loading={documentsLoading} value={currentCount} tone="success" />
              <Metric label="Active processing" loading={jobsSummaryQuery.isLoading && canViewJobs} value={activeJobs} />
              <Metric label="Needs attention" loading={documentsLoading} value={needsAttention} tone={needsAttention > 0 ? "warning" : "success"} />
              <Metric label="Trash" loading={trashQuery.isLoading} value={trashCount} />
            </div>
            <OverviewStatus
              indexedCurrentCount={indexedCurrentCount}
              needsAttention={needsAttention}
              nextStep={nextStep}
              onNavigate={onNavigate}
              processingCount={processingCount}
            />
            <StatusShortcutGrid loading={documentsLoading || (canViewJobs && jobsSummaryQuery.isLoading)} onNavigate={onNavigate} shortcuts={statusShortcuts} />
            <LifecycleStrip loading={documentsLoading || trashQuery.isLoading} onNavigate={onNavigate} items={lifecycleItems} />
          </section>

          <div className={canViewJobs ? "mt-6 grid gap-6 xl:grid-cols-3" : "mt-6 grid gap-6 lg:grid-cols-2"}>
            <section className="sv-panel overflow-hidden">
              <PanelHeader actionIcon={FileSearch} actionLabel="Open Attention" actionRoute="documents" actionSearch="?ingest=active" countLabel={documentsLoading ? "Loading" : `${attentionDocs.length} shown`} description="Failed, unknown, and review-required documents appear here first." onNavigate={onNavigate} title="Needs Attention" />
              {documentsLoading ? <PanelSkeleton /> : attentionDocs.length ? <AttentionList documents={attentionDocs} onNavigate={onNavigate} /> : <Empty icon={CheckCircle2} title="No document issues" text="The visible library has no failed, unknown, or review-required document status." />}
            </section>
            {canViewJobs ? (
              <section className="sv-panel overflow-hidden">
                <PanelHeader actionIcon={History} actionLabel="Open Activity" actionRoute="ingestion-jobs" countLabel={recentActivityQuery.isLoading ? "Loading" : `${recentActivityQuery.data?.items.length ?? 0} latest`} description="Latest intake, folder, restore, and reingestion runs across visible spaces." onNavigate={onNavigate} title="Recent Activity" />
                <RecentActivityList isLoading={recentActivityQuery.isLoading} jobs={recentActivityQuery.data?.items ?? []} onNavigate={onNavigate} />
              </section>
            ) : null}
            <section className="sv-panel overflow-hidden">
              <PanelHeader actionIcon={FolderOpen} actionLabel="Open Spaces" actionRoute="knowledge-spaces" countLabel={`${spaceRows.length} spaces`} description="Spaces are ranked by attention items first, then document volume." onNavigate={onNavigate} title="Library by Space" />
              {documentsLoading ? <PanelSkeleton /> : spaceRows.length ? <SpaceList rows={spaceRows.slice(0, 6)} onNavigate={onNavigate} /> : <Empty icon={FolderOpen} actionLabel={canAccessRoute(user, "upload") ? "Add Files" : "Open Spaces"} actionRoute={canAccessRoute(user, "upload") ? "upload" : "knowledge-spaces"} onNavigate={onNavigate} title="No documents yet" text="Add files or open Knowledge Spaces to prepare the library." />}
            </section>
          </div>
        </div>
      </main>
    </PrudentiaWorkspace>
  );
}

function Metric({ label, loading, tone, value }: { label: string; loading: boolean; tone?: "success" | "warning"; value: number }) {
  const className = tone === "success" ? "knowledge-context-metric knowledge-context-metric-success" : "knowledge-context-metric";
  return <div className={className} data-tone={tone}><span>{label}</span>{loading ? <Skeleton className="mt-1 h-6 w-12" /> : <strong>{value}</strong>}</div>;
}

function buildNextStep({ activeJobs, canOpenFolderSources, canUpload, canViewJobs, documentsCount, indexedCurrentCount, needsAttention }: NextStepInput): NextStep {
  if (needsAttention > 0) return { detail: `${needsAttention} item${needsAttention === 1 ? "" : "s"} need review before the library is fully healthy.`, primaryLabel: "Review Documents", primaryRoute: "documents", primarySearch: "?ingest=active", secondaryLabel: canViewJobs ? "Open Activity" : undefined, secondaryRoute: canViewJobs ? "ingestion-jobs" : undefined, secondarySearch: canViewJobs ? "?status=failed" : undefined, title: "Attention needed", tone: "warning" };
  if (activeJobs > 0) return { detail: `${activeJobs} processing run${activeJobs === 1 ? " is" : "s are"} still moving into the library.`, primaryLabel: canViewJobs ? "Track Activity" : "Open Processing", primaryRoute: canViewJobs ? "ingestion-jobs" : "documents", primarySearch: canViewJobs ? "?status=processing" : "?ingest=processing", secondaryLabel: "Open Documents", secondaryRoute: "documents", secondarySearch: "?ingest=processing", title: "Intake is running", tone: "active" };
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

function buildStatusShortcuts({ canViewDocuments, canViewJobs, failedCount, indexedCurrentCount, processingCount, reviewCount, user }: StatusShortcutInput): StatusShortcut[] {
  const shortcuts: StatusShortcut[] = [
    { detail: "current and searchable", icon: CheckCircle2, label: "Indexed", route: "documents", search: "?lifecycle=current&ingest=indexed", tone: "success", value: indexedCurrentCount },
    { detail: canViewJobs ? "live intake runs" : "queued library items", icon: Hourglass, label: "Processing", route: canViewJobs ? "ingestion-jobs" : "documents", search: canViewJobs ? "?status=processing" : "?ingest=processing", tone: "active", value: processingCount },
    { detail: "human review required", icon: AlertTriangle, label: "Needs Review", route: "documents", search: "?ingest=human_review", tone: reviewCount > 0 ? "warning" : undefined, value: reviewCount },
    { detail: canViewJobs ? "failed intake runs" : "failed documents", icon: XCircle, label: "Failed", route: canViewJobs ? "ingestion-jobs" : "documents", search: canViewJobs ? "?status=failed" : "?ingest=failed", tone: failedCount > 0 ? "warning" : undefined, value: failedCount },
  ];
  return shortcuts.filter((item) => (item.route === "documents" ? canViewDocuments : canAccessRoute(user, item.route)));
}

function summarizeSpaces(documents: Document[]): SpaceRow[] {
  const rows = new Map<string, SpaceRow>();
  documents.forEach((doc) => {
    const row = rows.get(doc.group_path) ?? { attention: 0, count: 0, path: doc.group_path };
    row.count += 1;
    if (isAttentionStatus(doc.ingest_status)) row.attention += 1;
    rows.set(doc.group_path, row);
  });
  return [...rows.values()].sort((left, right) => right.attention - left.attention || right.count - left.count || left.path.localeCompare(right.path));
}

function isActiveJobStatus(status: DocumentIngestStatus) {
  return status === "scheduled" || status === "queued" || status === "processing";
}

function isAttentionStatus(status: DocumentIngestStatus) {
  return status === "failed" || status === "human_review" || status === "cancelled" || status === "unknown";
}

function isExpiringSoon(value: string | null) {
  if (!value) return false;
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return false;
  const now = Date.now();
  return timestamp >= now && timestamp <= now + EXPIRING_SOON_DAYS * 24 * 60 * 60 * 1000;
}

function isProcessingStatus(status: DocumentIngestStatus) {
  return status === "scheduled" || status === "queued" || status === "processing";
}

type Props = { documents: Document[]; documentsLoading: boolean; onLogout: () => void; onNavigate: (route: RouteId, options?: NavigateOptions) => void; uploadJobs: UploadBatchItemView[]; user: AuthUser };
type LifecycleInput = { currentCount: number; expiringSoonCount: number; supersededCount: number; trashCount: number; user: AuthUser };
type NextStepInput = { activeJobs: number; canOpenFolderSources: boolean; canUpload: boolean; canViewJobs: boolean; documentsCount: number; indexedCurrentCount: number; needsAttention: number };
type StatusShortcutInput = { canViewDocuments: boolean; canViewJobs: boolean; failedCount: number; indexedCurrentCount: number; processingCount: number; reviewCount: number; user: AuthUser };
