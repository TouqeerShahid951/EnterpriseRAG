import { useEffect, useState } from "react";
import type { AuditEventListRequest } from "@/lib/api/contracts";
import type { AuditEvent, AuditSummary } from "@/types/api";

export const PAGE_SIZE_OPTIONS = [25, 50, 100, 250];

export function auditRequest(state: AuditRequestState): AuditEventListRequest {
  return {
    search: state.search || undefined,
    category: state.category || undefined,
    event_type: state.eventType || undefined,
    actor_id: state.actorQuery || undefined,
    target_type: state.targetType || undefined,
    target_id: state.targetId || undefined,
    group_path: state.groupPath || undefined,
    created_from: state.createdFrom ? `${state.createdFrom}T00:00:00Z` : undefined,
    created_to: state.createdTo ? `${state.createdTo}T23:59:59Z` : undefined,
    limit: state.limit,
    offset: state.offset,
  };
}

export function eventGroupPath(event: AuditEvent): string | null {
  const value = event.payload.group_path;
  return typeof value === "string" && value ? value : null;
}

export function eventLinks(event: AuditEvent): Array<{ href: string; label: string }> {
  const links: Array<{ href: string; label: string }> = [];
  const docId = event.target_type === "document" ? event.target_id : typeof event.payload.doc_id === "string" ? event.payload.doc_id : null;
  const jobId = event.target_type === "ingest_job" ? event.target_id : typeof event.payload.job_id === "string" ? event.payload.job_id : null;
  if (docId) links.push({ href: `/documents?doc=${encodeURIComponent(docId)}`, label: "Open document" });
  if (jobId) links.push({ href: `/ingestion-jobs?job_q=${encodeURIComponent(jobId)}`, label: "Open activity" });
  return links;
}

export function emptyAuditSummary(): AuditSummary {
  return {
    total: 0,
    document_events: 0,
    auth_events: 0,
    system_events: 0,
    actor_count: 0,
    event_type_count: 0,
    category_counts: {},
    target_type_counts: {},
    event_type_counts: {},
  };
}

export function initialAuditParam(name: string) {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get(name)?.trim() ?? "";
}

export function useDebouncedText(value: string, delayMs: number) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [delayMs, value]);
  return debounced;
}

export function initialLimitFromUrl() {
  const value = Number.parseInt(initialAuditParam("limit"), 10);
  return PAGE_SIZE_OPTIONS.includes(value) ? value : 50;
}

export function initialOffsetFromUrl() {
  const value = Number.parseInt(initialAuditParam("offset"), 10);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

export function syncAuditUrl(state: AuditUrlState) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.delete("search");
  setUrlParam(url.searchParams, "audit_q", state.search.trim());
  setUrlParam(url.searchParams, "category", state.category);
  setUrlParam(url.searchParams, "event_type", state.eventType);
  setUrlParam(url.searchParams, "actor", state.actorQuery.trim());
  setUrlParam(url.searchParams, "target_type", state.targetType);
  setUrlParam(url.searchParams, "target_id", state.targetId.trim());
  setUrlParam(url.searchParams, "space", state.groupPath);
  setUrlParam(url.searchParams, "created_from", state.createdFrom);
  setUrlParam(url.searchParams, "created_to", state.createdTo);
  setUrlParam(url.searchParams, "limit", state.limit !== 50 ? String(state.limit) : "");
  setUrlParam(url.searchParams, "offset", state.offset > 0 ? String(state.offset) : "");
  setUrlParam(url.searchParams, "event", state.selectedEventId ?? "");
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== current) window.history.replaceState(window.history.state, "", next);
}

function setUrlParam(params: URLSearchParams, key: string, value: string) {
  if (value) params.set(key, value);
  else params.delete(key);
}

export function downloadBlob(blob: Blob, filename: string) {
  if (typeof document === "undefined") return;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function auditExportFilename() {
  return `audit-log-${new Date().toISOString().slice(0, 10)}.csv`;
}

export type AuditRequestState = {
  actorQuery: string;
  category: string;
  createdFrom: string;
  createdTo: string;
  eventType: string;
  groupPath: string;
  limit: number;
  offset: number;
  search: string;
  targetId: string;
  targetType: string;
};

export type AuditUrlState = AuditRequestState & { selectedEventId: string | null };
