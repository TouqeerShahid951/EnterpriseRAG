import { useEffect, useId, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Skeleton } from "@/components/layout/Common";
import { ingestStatusLabel } from "@/features/documents/utils/documentPageUtils";
import type { Document, DocumentIngestStatus } from "@/types/api";

type ContextMetricProps = {
  label: string;
  loading: boolean;
  tone?: "success";
  value: string;
};

type InspectorSectionProps = {
  children: ReactNode;
  defaultCollapsed?: boolean;
  resetKey?: string;
  title: string;
};

type EmptyStateProps = {
  action?: string;
  children?: string;
  onAction?: () => void;
  title: string;
};

type TextFieldProps = {
  autoComplete?: string;
  disabled?: boolean;
  helper?: string;
  label: string;
  onChange: (value: string) => void;
  required?: boolean;
  type?: string;
  value: string;
};

export function ContextMetric({ label, loading, tone, value }: ContextMetricProps) {
  return (
    <div className={tone === "success" ? "knowledge-context-metric knowledge-context-metric-success" : "knowledge-context-metric"} aria-busy={loading} data-cursor-glow>
      <span>{label}</span>
      {loading ? (
        <>
          <span className="sr-only">Loading {label.toLowerCase()}</span>
          <Skeleton className="mt-1 h-6 w-12" />
        </>
      ) : <strong>{value}</strong>}
    </div>
  );
}

export function DocumentStatePill({ document }: { document: Document }) {
  if (document.deleted_at) return <span className="sv-pill knowledge-status-failed">In Trash</span>;
  return document.is_current ? <span className="sv-pill sv-pill-success">Current</span> : <span className="sv-pill">Superseded</span>;
}

export function IngestStatusPill({ status }: { status: DocumentIngestStatus }) {
  const className = status === "cancelled" ? "sv-pill sv-pill-warning" : `sv-pill knowledge-status-${status}`;
  return <span className={className}>{ingestStatusLabel(status)}</span>;
}

export function InspectorSection({ children, defaultCollapsed = false, resetKey, title }: InspectorSectionProps) {
  const contentId = useId();
  const collapsible = defaultCollapsed;
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  useEffect(() => {
    if (collapsible) setCollapsed(defaultCollapsed);
  }, [collapsible, defaultCollapsed, resetKey]);

  return (
    <section className={collapsed ? "knowledge-inspector-section knowledge-inspector-section-collapsed" : "knowledge-inspector-section"}>
      {collapsible ? (
        <h3>
          <button
            type="button"
            className="knowledge-inspector-section-toggle"
            aria-controls={contentId}
            aria-expanded={!collapsed}
            onClick={() => setCollapsed((value) => !value)}
          >
            <span>{title}</span>
            {collapsed ? <ChevronRight size={15} aria-hidden="true" /> : <ChevronDown size={15} aria-hidden="true" />}
          </button>
        </h3>
      ) : (
        <h3>{title}</h3>
      )}
      <div id={collapsible ? contentId : undefined} className={collapsible ? "knowledge-inspector-section-body" : undefined} hidden={collapsible && collapsed}>
        {children}
      </div>
    </section>
  );
}

export function ChipList({ empty, values }: { empty: string; values: string[] }) {
  const unique = Array.from(new Set(values.filter(Boolean)));
  if (!unique.length) return <p className="text-body-md text-secondary">{empty}</p>;
  return (
    <div className="flex flex-wrap gap-2">
      {unique.slice(0, 16).map((value) => <span key={value} className="sv-pill">{value}</span>)}
    </div>
  );
}

export function KeyValueList({ empty, items }: { empty: string; items: Array<{ key: string; value: string }> }) {
  if (!items.length) return <p className="text-body-md text-secondary">{empty}</p>;
  return (
    <div className="space-y-2">
      {items.map((item, index) => (
        <div key={`${item.key}-${item.value}-${index}`} className="rounded-lg border border-surface-border bg-surface-card p-3 text-body-md">
          <span className="sv-metadata">{item.key}</span>
          <p className="mt-1 break-words font-semibold text-on-surface">{item.value}</p>
        </div>
      ))}
    </div>
  );
}

export function EmptyState({ action, children, onAction, title }: EmptyStateProps) {
  return (
    <div className="knowledge-empty-state">
      <h3>{title}</h3>
      <p>{children}</p>
      {action && onAction ? (
        <button type="button" onClick={onAction} className="sv-action-primary">
          {action}
        </button>
      ) : null}
    </div>
  );
}

export function SpaceOverviewSkeleton() {
  return (
    <div className="knowledge-space-overview-list p-4">
      {Array.from({ length: 6 }).map((_, index) => (
        <div key={index} className="knowledge-skeleton-row" />
      ))}
    </div>
  );
}

export function DocumentSkeleton() {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: 5 }).map((_, index) => (
        <div key={index} className="knowledge-skeleton-row" />
      ))}
    </div>
  );
}

export function TextField({ autoComplete, disabled, helper, label, onChange, required, type = "text", value }: TextFieldProps) {
  const id = label.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return (
    <label className="sv-field" htmlFor={id}>
      <span className="sv-label">{label}</span>
      <input autoComplete={autoComplete} className="sv-input" disabled={disabled} id={id} onChange={(event) => onChange(event.target.value)} required={required} type={type} value={value} />
      {helper ? <small className="text-secondary">{helper}</small> : null}
    </label>
  );
}

export function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="sv-metadata">{label}</span>
      <p className="mt-1 break-all rounded-lg border border-surface-border bg-surface-container-low p-3 text-body-md font-semibold text-on-surface">{value}</p>
    </div>
  );
}
