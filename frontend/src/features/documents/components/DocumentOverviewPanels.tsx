import { Activity, AlertTriangle, CheckCircle2, Clock3, FilePlus2, FolderOpen, History, type LucideIcon } from "lucide-react";

import { clearanceLevelLabel } from "@/lib/auth/authz";
import type { NavigateOptions, RouteId } from "@/routes/routes";
import type { Document, DocumentIngestStatus, IngestJob, UploadJobState } from "@/types/api";
import { formatDateTime } from "@/lib/utils/format";

type NavigateToRoute = (route: RouteId, options?: NavigateOptions) => void;

export function AttentionList({ documents, onNavigate }: { documents: Array<Pick<Document, "group_path" | "id" | "ingest_status" | "title">>; onNavigate: NavigateToRoute }) {
  return (
    <div className="knowledge-action-list p-4">
      {documents.map((doc) => (
        <button type="button" key={doc.id} onClick={() => onNavigate("documents", { search: `?doc=${encodeURIComponent(doc.id)}` })}>
          <span>
            <strong>{doc.title}</strong>
            <small className="block text-secondary">{doc.group_path}</small>
          </span>
          <IngestStatusBadge status={doc.ingest_status} />
        </button>
      ))}
    </div>
  );
}

export function Empty({ actionLabel, actionRoute, actionSearch, icon: Icon, onNavigate, text, title }: EmptyProps) {
  return (
    <div className="knowledge-empty-state">
      {Icon ? <Icon size={20} aria-hidden="true" /> : null}
      <h3>{title}</h3>
      <p>{text}</p>
      {actionLabel && actionRoute && onNavigate ? (
        <button type="button" onClick={() => onNavigate(actionRoute, { search: actionSearch })} className="sv-action-secondary">
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

export function LifecycleStrip({ items, loading, onNavigate }: LifecycleStripProps) {
  if (!items.length) return null;
  return (
    <section className="knowledge-lifecycle-strip" aria-label="Document lifecycle shortcuts">
      {items.map((item) => {
        const Icon = item.icon;
        const content = (
          <>
            <span className="knowledge-lifecycle-icon"><Icon size={15} aria-hidden="true" /></span>
            <span className="knowledge-lifecycle-copy">
              <span>{item.label}</span>
              <small>{item.detail}</small>
            </span>
            {loading ? <CountSkeleton label={item.label} /> : <strong>{item.value}</strong>}
          </>
        );
        return item.route ? (
          <button type="button" data-tone={item.tone} key={item.label} onClick={() => onNavigate(item.route!, { search: item.search })}>
            {content}
          </button>
        ) : (
          <div data-tone={item.tone} key={item.label}>{content}</div>
        );
      })}
    </section>
  );
}

export function OverviewStatus({ indexedCurrentCount, needsAttention, nextStep, onNavigate, processingCount }: OverviewStatusProps) {
  const StatusIcon = statusIcon(nextStep.tone);
  return (
    <section className="knowledge-overview-status" data-tone={nextStep.tone}>
      <div className="knowledge-overview-status-main">
        <p className="sv-metadata">Recommended next step</p>
        <h2><StatusIcon size={19} /> {nextStep.title}</h2>
        <p>{nextStep.detail}</p>
        <div className="knowledge-overview-status-actions">
          <button type="button" onClick={() => onNavigate(nextStep.primaryRoute, { search: nextStep.primarySearch })} className="sv-action-primary">{nextStep.primaryLabel}</button>
          {nextStep.secondaryRoute ? <button type="button" onClick={() => onNavigate(nextStep.secondaryRoute!, { search: nextStep.secondarySearch })} className="sv-action-secondary">{nextStep.secondaryLabel}</button> : null}
        </div>
      </div>
      <div className="knowledge-overview-flow" aria-label="Document library readiness">
        <FlowMetric icon={CheckCircle2} label="Indexed current" value={indexedCurrentCount} />
        <FlowMetric icon={Activity} label="Processing" value={processingCount} />
        <FlowMetric icon={AlertTriangle} label="Attention" tone={needsAttention > 0 ? "warning" : "success"} value={needsAttention} />
      </div>
    </section>
  );
}

export function PanelHeader({ actionIcon: ActionIcon, actionLabel, actionRoute, actionSearch, countLabel, description, onNavigate, title }: PanelHeaderProps) {
  return (
    <div className="knowledge-job-block-header">
      <div>
        <h2 className="sv-section-title">{title}</h2>
        <p>{description}</p>
      </div>
      <div className="knowledge-panel-actions">
        <span className="sv-pill">{countLabel}</span>
        <button type="button" onClick={() => onNavigate(actionRoute, { search: actionSearch })} className="sv-action-secondary"><ActionIcon size={15} /> {actionLabel}</button>
      </div>
    </div>
  );
}

export function PanelSkeleton({ rows = 4 }: { rows?: number }) {
  return <div className="grid gap-2 p-4">{Array.from({ length: rows }, (_, index) => <div className="knowledge-skeleton-row" key={index} />)}</div>;
}

export function RecentActivityList({ isLoading, jobs, onNavigate }: RecentActivityListProps) {
  if (isLoading) return <PanelSkeleton rows={4} />;
  if (!jobs.length) return <Empty icon={History} title="No recent activity" text="Upload, folder, restore, and reingestion runs will appear here after intake starts." />;
  return (
    <div className="knowledge-activity-list p-4">
      {jobs.map((job) => (
        <button type="button" key={job.job_id} onClick={() => onNavigate("ingestion-jobs", { search: `?job_q=${encodeURIComponent(job.job_id)}` })}>
          <span className="knowledge-activity-main">
            <strong>{job.document_title}</strong>
            <small>{job.group_path} - {clearanceLevelLabel(job.clearance_level)} - {labelize(job.origin)} - {formatDateTime(job.created_at)}</small>
          </span>
          <span className="knowledge-activity-meta">
            <IngestStatusBadge status={job.status} warnings={job.warnings} />
            <small><Clock3 size={12} /> {job.progress_pct}%</small>
          </span>
        </button>
      ))}
    </div>
  );
}

export function SpaceList({ rows, onNavigate }: { rows: SpaceRow[]; onNavigate: NavigateToRoute }) {
  return (
    <div className="knowledge-action-list p-4">
      {rows.map((row) => (
        <button type="button" key={row.path} onClick={() => onNavigate("knowledge-spaces", { search: `?space=${encodeURIComponent(row.path)}` })}>
          <span>
            <strong>{row.path}</strong>
            <small className="block text-secondary">{row.count} documents - {row.attention} attention</small>
          </span>
          <span className="knowledge-row-trailing">
            <span className={row.attention > 0 ? "sv-pill sv-pill-warning" : "sv-pill sv-pill-success"}>{row.attention > 0 ? "Needs review" : "Healthy"}</span>
            <FolderOpen size={16} />
          </span>
        </button>
      ))}
    </div>
  );
}

export function StatusShortcutGrid({ loading, onNavigate, shortcuts }: StatusShortcutGridProps) {
  if (!shortcuts.length) return null;
  return (
    <section className="knowledge-status-shortcuts" aria-label="Document status shortcuts">
      {shortcuts.map((shortcut) => {
        const Icon = shortcut.icon;
        return (
          <button type="button" data-tone={shortcut.tone} key={shortcut.label} onClick={() => onNavigate(shortcut.route, { search: shortcut.search })}>
            <span className="knowledge-status-shortcut-icon"><Icon size={15} aria-hidden="true" /></span>
            <span>
              <strong>{shortcut.label}</strong>
              <small>{shortcut.detail}</small>
            </span>
            {loading ? <CountSkeleton label={shortcut.label} /> : <b>{shortcut.value}</b>}
          </button>
        );
      })}
    </section>
  );
}

function CountSkeleton({ label }: { label: string }) {
  return (
    <span className="knowledge-count-skeleton">
      <span className="sr-only">Loading {label.toLowerCase()}</span>
    </span>
  );
}

function FlowMetric({ icon: Icon, label, tone, value }: { icon: LucideIcon; label: string; tone?: "success" | "warning"; value: number }) {
  return <div data-tone={tone}><span><Icon size={13} /> {label}</span><strong>{value}</strong></div>;
}

function IngestStatusBadge({ status, warnings = [] }: { status: DocumentIngestStatus | UploadJobState; warnings?: string[] }) {
  const className = status === "complete" && warnings.length > 0
    ? "sv-pill sv-pill-warning"
    : status === "complete"
      ? "sv-pill sv-pill-success"
      : status === "failed"
        ? "sv-pill knowledge-status-failed"
        : status === "cancelled"
          ? "sv-pill sv-pill-warning"
        : status === "human_review"
          ? "sv-pill knowledge-status-human_review"
          : status === "unknown"
            ? "sv-pill knowledge-status-unknown"
            : "sv-pill knowledge-status-processing";
  return <span className={className}>{status === "complete" && warnings.length > 0 ? "Indexed with warnings" : ingestStatusLabel(status)}</span>;
}

function statusIcon(tone: NextStep["tone"]): LucideIcon {
  if (tone === "warning") return AlertTriangle;
  if (tone === "active") return Activity;
  if (tone === "empty") return FilePlus2;
  return CheckCircle2;
}

function ingestStatusLabel(status: DocumentIngestStatus | UploadJobState) {
  if (status === "human_review") return "Needs review";
  if (status === "processing") return "Processing";
  if (status === "scheduled") return "Scheduled";
  if (status === "queued") return "Queued";
  if (status === "cancelled") return "Cancelled";
  if (status === "failed") return "Failed";
  if (status === "unknown") return "Unknown";
  return "Indexed";
}

function labelize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

type EmptyProps = { actionLabel?: string; actionRoute?: RouteId; actionSearch?: string; icon?: LucideIcon; onNavigate?: NavigateToRoute; text: string; title: string };
export type LifecycleItem = { detail: string; icon: LucideIcon; label: string; route?: RouteId; search?: string; tone?: "active" | "success" | "warning"; value: number };
type LifecycleStripProps = { items: LifecycleItem[]; loading: boolean; onNavigate: NavigateToRoute };
export type NextStep = { detail: string; primaryLabel: string; primaryRoute: RouteId; primarySearch?: string; secondaryLabel?: string; secondaryRoute?: RouteId; secondarySearch?: string; title: string; tone: "active" | "empty" | "success" | "warning" };
type OverviewStatusProps = { indexedCurrentCount: number; needsAttention: number; nextStep: NextStep; onNavigate: NavigateToRoute; processingCount: number };
type PanelHeaderProps = { actionIcon: LucideIcon; actionLabel: string; actionRoute: RouteId; actionSearch?: string; countLabel: string; description: string; onNavigate: NavigateToRoute; title: string };
type RecentActivityListProps = { isLoading: boolean; jobs: IngestJob[]; onNavigate: NavigateToRoute };
export type SpaceRow = { attention: number; count: number; path: string };
export type StatusShortcut = { detail: string; icon: LucideIcon; label: string; route: RouteId; search?: string; tone?: "active" | "success" | "warning"; value: number };
type StatusShortcutGridProps = { loading: boolean; onNavigate: NavigateToRoute; shortcuts: StatusShortcut[] };
