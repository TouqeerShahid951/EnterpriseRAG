import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, ChevronLeft, ChevronRight, Copy, Database, ExternalLink, FileText, Search, ShieldCheck, SlidersHorizontal, UserRound, X } from "lucide-react";

import { adminApi, auditApi, type AuditEventListRequest } from "../api/contracts";
import { canViewSpaceMetadata } from "../authz";
import { InlineMessage, Skeleton } from "../components/layout/Common";
import { FahamWorkspace } from "../components/layout/FahamWorkspace";
import type { RouteId } from "../routes";
import type { AuditEvent, AuditSummary, User as AuthUser } from "../types/api";
import {
  actorDisplay,
  auditCategories,
  auditCategory,
  auditCategoryLabel,
  auditImpactSummary,
  formatPayloadValue,
  payloadSummary,
  targetDisplay,
} from "../utils/audit";
import { errorMessage, formatDateTime } from "../utils/format";
import { flattenGroups, userSpacesFromPaths } from "../utils/groups";

const PAGE_SIZE_OPTIONS = [25, 50, 100, 250];
const TARGET_TYPE_OPTIONS = ["document", "user", "ingest_job", "folder_schedule", "generated_artifact", "query", "review_item", "workspace_ingest_config"];

export function FahamAuditPage({ onLogout, onNavigate, user }: Props) {
  const [search, setSearch] = useState(() => initialAuditParam("audit_q") || initialAuditParam("search"));
  const [category, setCategory] = useState(() => initialAuditParam("category"));
  const [eventType, setEventType] = useState(() => initialAuditParam("event_type"));
  const [actorQuery, setActorQuery] = useState(() => initialAuditParam("actor"));
  const [targetType, setTargetType] = useState(() => initialAuditParam("target_type"));
  const [targetId, setTargetId] = useState(() => initialAuditParam("target_id"));
  const [groupPath, setGroupPath] = useState(() => initialAuditParam("space"));
  const [createdFrom, setCreatedFrom] = useState(() => initialAuditParam("created_from"));
  const [createdTo, setCreatedTo] = useState(() => initialAuditParam("created_to"));
  const [limit, setLimit] = useState(() => initialLimitFromUrl());
  const [offset, setOffset] = useState(() => initialOffsetFromUrl());
  const [selectedEventId, setSelectedEventId] = useState<string | null>(() => initialAuditParam("event") || null);
  const canLoadDirectory = canViewSpaceMetadata(user);
  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, enabled: canLoadDirectory, retry: false });
  const spaceOptions = useMemo(
    () => (canLoadDirectory ? flattenGroups(groupsQuery.data?.items ?? []) : userSpacesFromPaths(user.group_paths)),
    [canLoadDirectory, groupsQuery.data?.items, user.group_paths],
  );
  const request = auditRequest({ actorQuery, category, createdFrom, createdTo, eventType, groupPath, limit, offset, search, targetId, targetType });
  const auditQuery = useQuery({
    queryKey: ["audit-log", request],
    queryFn: () => auditApi.list(request),
    retry: false,
    staleTime: 4000,
  });
  const events = auditQuery.data?.items ?? [];
  const summary = auditQuery.data?.summary ?? emptyAuditSummary();
  const total = auditQuery.data?.total ?? 0;
  const firstItem = total === 0 ? 0 : offset + 1;
  const lastItem = Math.min(offset + events.length, total);
  const selectedEvent = events.find((event) => event.id === selectedEventId) ?? null;
  const activeFilterCount = [search, category, eventType, actorQuery, targetType, targetId, groupPath, createdFrom, createdTo].filter(Boolean).length;
  const eventTypeOptions = useMemo(
    () => [...new Set([eventType, ...Object.keys(summary.event_type_counts), ...events.map((event) => event.event_type)].filter(Boolean))].sort(),
    [eventType, events, summary.event_type_counts],
  );

  useEffect(() => {
    syncAuditUrl({ actorQuery, category, createdFrom, createdTo, eventType, groupPath, limit, offset, search, selectedEventId, targetId, targetType });
  }, [actorQuery, category, createdFrom, createdTo, eventType, groupPath, limit, offset, search, selectedEventId, targetId, targetType]);

  function resetOffset<T>(setter: (value: T) => void, value: T) {
    setOffset(0);
    setter(value);
  }

  function clearFilters() {
    setSearch("");
    setCategory("");
    setEventType("");
    setActorQuery("");
    setTargetType("");
    setTargetId("");
    setGroupPath("");
    setCreatedFrom("");
    setCreatedTo("");
    setOffset(0);
    setSelectedEventId(null);
  }

  function toggleSelectedEvent(eventId: string) {
    setSelectedEventId((current) => (current === eventId ? null : eventId));
  }

  return (
    <FahamWorkspace activeRoute="activity-log" onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page" id="main-content">
        <div className="sv-page-inner max-w-none">
          <header className="sv-page-header">
            <div>
              <p className="sv-eyebrow">Govern</p>
              <h1 className="sv-page-title">System Audit</h1>
              <p className="sv-page-subtitle">Investigate visible workspace activity by actor, target, Knowledge Space, event type, and time window.</p>
            </div>
          </header>

          {auditQuery.isError ? <InlineMessage tone="error">{errorMessage(auditQuery.error, "Unable to load audit events.")}</InlineMessage> : null}
          {groupsQuery.isError ? <InlineMessage tone="warning">{errorMessage(groupsQuery.error, "Unable to load Knowledge Space filters.")}</InlineMessage> : null}

          <section className="sv-panel audit-toolbar" aria-label="Audit workbench controls">
            <div className="audit-toolbar-top">
              <div className="audit-summary-strip" aria-label="Audit summary">
                <AuditMetric icon={<Activity size={15} />} label="Matching" loading={auditQuery.isLoading} value={summary.total} />
                <AuditMetric icon={<FileText size={15} />} label="Documents" loading={auditQuery.isLoading} value={summary.document_events} />
                <AuditMetric icon={<ShieldCheck size={15} />} label="Auth/system" loading={auditQuery.isLoading} value={summary.auth_events + summary.system_events} />
                <AuditMetric icon={<UserRound size={15} />} label="Actors" loading={auditQuery.isLoading} value={summary.actor_count} />
                <AuditMetric icon={<Database size={15} />} label="Types" loading={auditQuery.isLoading} value={summary.event_type_count} />
              </div>
              <div className="audit-toolbar-actions">
                <button type="button" className="sv-action-secondary" onClick={() => auditQuery.refetch()}>
                  <Activity size={15} /> Refresh
                </button>
                <button type="button" className="sv-action-secondary" onClick={clearFilters}>
                  <X size={15} /> Reset
                </button>
              </div>
            </div>

            <div className="audit-primary-filters">
              <label className="knowledge-tree-search audit-search">
                <Search size={16} aria-hidden="true" />
                <span className="sr-only">Search audit events</span>
                <input value={search} onChange={(event) => resetOffset(setSearch, event.target.value)} placeholder="Search event, email, ID, document, or payload" />
              </label>
              <AuditSelect label="Category" value={category} onChange={(value) => resetOffset(setCategory, value)} options={auditCategories} />
              <AuditSelect label="Event Type" value={eventType} onChange={(value) => resetOffset(setEventType, value)} options={eventTypeOptions} />
              <div className="audit-date-range">
                <label className="sv-field">
                  <span className="sv-label">From</span>
                  <input type="date" className="sv-input" value={createdFrom} onChange={(event) => resetOffset(setCreatedFrom, event.target.value)} />
                </label>
                <label className="sv-field">
                  <span className="sv-label">To</span>
                  <input type="date" className="sv-input" value={createdTo} onChange={(event) => resetOffset(setCreatedTo, event.target.value)} />
                </label>
              </div>
            </div>

            <details className="audit-advanced-filters">
              <summary>
                <span><SlidersHorizontal size={15} /> More filters</span>
                <small>{activeFilterCount > 0 ? `${activeFilterCount} active` : "Optional"}</small>
              </summary>
              <div className="audit-advanced-filter-grid">
                <AuditSelect label="Target Type" value={targetType} onChange={(value) => resetOffset(setTargetType, value)} options={TARGET_TYPE_OPTIONS} />
              <label className="sv-field">
                <span className="sv-label">Actor ID or Email</span>
                <input className="sv-input" value={actorQuery} onChange={(event) => resetOffset(setActorQuery, event.target.value)} placeholder="admin@example.test" />
              </label>
              <label className="sv-field">
                <span className="sv-label">Target ID</span>
                <input className="sv-input" value={targetId} onChange={(event) => resetOffset(setTargetId, event.target.value)} placeholder="document or user id" />
              </label>
              <AuditSelect label="Knowledge Space" value={groupPath} onChange={(value) => resetOffset(setGroupPath, value)} options={spaceOptions.map((space) => space.path)} />
              <label className="sv-field">
                <span className="sv-label">Page Size</span>
                <select
                  className="sv-select"
                  value={String(limit)}
                  onChange={(event) => {
                    setOffset(0);
                    setLimit(Number(event.target.value));
                  }}
                >
                  {PAGE_SIZE_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
                </select>
              </label>
              </div>
            </details>
          </section>

          <div className="audit-workbench">
            <section className="sv-panel overflow-hidden audit-events-panel">
              <div className="ingest-job-list-header">
                <div>
                  <h2 className="sv-section-title">Audit Trail</h2>
                  <p>{auditQuery.isLoading ? "Loading events" : `${firstItem}-${lastItem} of ${total}`}</p>
                </div>
                <div className="ingest-job-pagination">
                  <button type="button" className="sv-action-secondary" disabled={offset === 0 || auditQuery.isLoading} onClick={() => setOffset(Math.max(0, offset - limit))}>
                    <ChevronLeft size={15} /> Previous
                  </button>
                  <button type="button" className="sv-action-secondary" disabled={offset + limit >= total || auditQuery.isLoading} onClick={() => setOffset(offset + limit)}>
                    Next <ChevronRight size={15} />
                  </button>
                </div>
              </div>

              {auditQuery.isLoading ? <AuditSkeleton /> : null}
              {!auditQuery.isLoading && events.length === 0 ? (
                <div className="knowledge-empty-state">
                  <ShieldCheck size={22} />
                  <h3>No audit events match these filters</h3>
                  <p>Adjust the filters or widen the date range to continue the investigation.</p>
                </div>
              ) : null}
              {!auditQuery.isLoading && events.length > 0 ? (
                <AuditTable events={events} onToggle={toggleSelectedEvent} selectedEventId={selectedEvent?.id ?? selectedEventId} />
              ) : null}
            </section>
          </div>
        </div>
      </main>
    </FahamWorkspace>
  );
}

function AuditMetric({ icon, label, loading, value }: { icon: JSX.Element; label: string; loading: boolean; value: number }) {
  return (
    <div className="audit-metric" aria-busy={loading}>
      <span>{icon}</span>
      <div>
        <p>{label}</p>
        {loading ? <Skeleton className="mt-1 h-4 w-10" /> : <strong>{value}</strong>}
      </div>
    </div>
  );
}

function AuditSelect({ label, onChange, options, value }: { label: string; onChange: (value: string) => void; options: string[]; value: string }) {
  return (
    <label className="sv-field">
      <span className="sv-label">{label}</span>
      <select className="sv-select" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">All {label}</option>
        {options.map((option) => <option key={option} value={option}>{option.startsWith("/") ? option : auditCategoryLabel(option)}</option>)}
      </select>
    </label>
  );
}

function AuditTable({ events, onToggle, selectedEventId }: { events: AuditEvent[]; onToggle: (eventId: string) => void; selectedEventId: string | null }) {
  return (
    <div className="sv-table-wrap">
      <table className="sv-table audit-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Event</th>
            <th>Actor</th>
            <th>Target</th>
            <th>Space / Source</th>
            <th>Inspect</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <AuditRow event={event} isSelected={selectedEventId === event.id} key={event.id} onToggle={onToggle} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AuditRow({ event, isSelected, onToggle }: { event: AuditEvent; isSelected: boolean; onToggle: (eventId: string) => void }) {
  const actor = actorDisplay(event);
  const target = targetDisplay(event);
  const detailId = `audit-detail-${event.id}`;

  return (
    <>
      <tr className="sv-table-row audit-table-row" aria-selected={isSelected}>
        <td data-label="Time" className="text-secondary">{formatDateTime(event.created_at)}</td>
        <td data-label="Event">
          <button type="button" className="audit-event-button" aria-controls={detailId} aria-expanded={isSelected} onClick={() => onToggle(event.id)}>
            <strong>{event.event_type}</strong>
            <small>{auditCategoryLabel(auditCategory(event))} | {event.id}</small>
            <span>{auditImpactSummary(event)}</span>
          </button>
        </td>
        <td data-label="Actor">
          <IdentityCell icon={<UserRound size={15} />} label={actor.label} detail={actor.detail} unresolved={actor.unresolved} />
        </td>
        <td data-label="Target">
          <IdentityCell icon={<Database size={15} />} label={target.label} detail={target.detail} unresolved={target.unresolved} />
        </td>
        <td data-label="Space / Source">
          <span className="audit-source">{eventGroupPath(event) ?? event.target_type ?? "workspace"}</span>
        </td>
        <td data-label="Inspect">
          <button
            type="button"
            className={isSelected ? "sv-action-secondary audit-row-detail-button audit-row-detail-button-active" : "sv-action-secondary audit-row-detail-button"}
            aria-controls={detailId}
            aria-expanded={isSelected}
            onClick={() => onToggle(event.id)}
          >
            {isSelected ? <X size={14} /> : <FileText size={14} />}
            {isSelected ? "Close" : "Details"}
          </button>
        </td>
      </tr>
      {isSelected ? (
        <tr className="audit-detail-row">
          <td colSpan={6}>
            <div id={detailId}>
              <AuditDetails event={event} />
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

function IdentityCell({ detail, icon, label, unresolved }: { detail?: string; icon: JSX.Element; label: string; unresolved?: boolean }) {
  return (
    <span className={unresolved ? "audit-identity audit-identity-unresolved" : "audit-identity"}>
      {icon}
      <span>
        <strong>{label}</strong>
        {detail ? <small>{detail}</small> : null}
      </span>
    </span>
  );
}

function AuditDetails({ event }: { event: AuditEvent }) {
  const [copied, setCopied] = useState<string | null>(null);
  useEffect(() => setCopied(null), [event?.id]);

  const actor = actorDisplay(event);
  const target = targetDisplay(event);
  const links = eventLinks(event);

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(value);
    } catch {
      setCopied(null);
    }
  }

  return (
    <section className="audit-details-panel" aria-label={`Details for ${event.event_type}`}>
      <div className="audit-details-header">
        <div>
          <span className="sv-pill">{auditCategoryLabel(auditCategory(event))}</span>
          <h3>{event.event_type}</h3>
          <p>{auditImpactSummary(event)}</p>
        </div>
        {links.length > 0 ? (
          <div className="audit-link-list">
            {links.map((link) => (
              <a key={link.href} href={link.href} className="sv-action-secondary">
                <ExternalLink size={14} /> {link.label}
              </a>
            ))}
          </div>
        ) : null}
      </div>

      <dl className="audit-detail-list">
        <AuditFact label="Created" value={formatDateTime(event.created_at)} />
        <AuditFact label="Event ID" value={event.id} onCopy={() => copy(event.id)} copied={copied === event.id} />
        <AuditFact label="Actor" value={actor.label} detail={actor.detail} onCopy={event.actor_id ? () => copy(event.actor_id ?? "") : undefined} copied={copied === event.actor_id} />
        <AuditFact label="Target" value={target.label} detail={target.detail} onCopy={event.target_id ? () => copy(event.target_id ?? "") : undefined} copied={copied === event.target_id} />
        <AuditFact label="Source Space" value={eventGroupPath(event) ?? "Not set"} />
      </dl>

      <div className="audit-payload">
        <div>
          <h3>Payload</h3>
          <p>{payloadSummary(event.payload)}</p>
        </div>
        <dl>
          {Object.entries(event.payload).map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{formatPayloadValue(value)}</dd>
            </div>
          ))}
        </dl>
        {Object.keys(event.payload).length === 0 ? <p className="text-secondary">No payload fields recorded.</p> : null}
        <details className="audit-payload-json">
          <summary>Raw JSON</summary>
          <pre>{JSON.stringify(event.payload, null, 2)}</pre>
        </details>
      </div>
    </section>
  );
}

function AuditFact({ copied, detail, label, onCopy, value }: { copied?: boolean; detail?: string; label: string; onCopy?: () => void; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        <span>
          <strong>{value}</strong>
          {detail ? <small>{detail}</small> : null}
        </span>
        {onCopy ? (
          <button type="button" className="faham-icon-button" onClick={onCopy} title={`Copy ${label}`}>
            <Copy size={14} />
            <span className="sr-only">{copied ? "Copied" : `Copy ${label}`}</span>
          </button>
        ) : null}
      </dd>
    </div>
  );
}

function AuditSkeleton() {
  return <div className="grid gap-2 p-4">{Array.from({ length: 7 }, (_, index) => <div className="knowledge-skeleton-row" key={index} />)}</div>;
}

function auditRequest(state: AuditRequestState): AuditEventListRequest {
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

function eventGroupPath(event: AuditEvent): string | null {
  const value = event.payload.group_path;
  return typeof value === "string" && value ? value : null;
}

function eventLinks(event: AuditEvent): Array<{ href: string; label: string }> {
  const links: Array<{ href: string; label: string }> = [];
  const docId = event.target_type === "document" ? event.target_id : typeof event.payload.doc_id === "string" ? event.payload.doc_id : null;
  const jobId = event.target_type === "ingest_job" ? event.target_id : typeof event.payload.job_id === "string" ? event.payload.job_id : null;
  if (docId) links.push({ href: `/documents?doc=${encodeURIComponent(docId)}`, label: "Open document" });
  if (jobId) links.push({ href: `/ingestion-jobs?job_q=${encodeURIComponent(jobId)}`, label: "Open activity" });
  return links;
}

function emptyAuditSummary(): AuditSummary {
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

function initialAuditParam(name: string) {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get(name)?.trim() ?? "";
}

function initialLimitFromUrl() {
  const value = Number.parseInt(initialAuditParam("limit"), 10);
  return PAGE_SIZE_OPTIONS.includes(value) ? value : 50;
}

function initialOffsetFromUrl() {
  const value = Number.parseInt(initialAuditParam("offset"), 10);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function syncAuditUrl(state: AuditUrlState) {
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

type AuditRequestState = {
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

type AuditUrlState = AuditRequestState & { selectedEventId: string | null };

type Props = {
  onLogout: () => void;
  onNavigate: (route: RouteId) => void;
  user: AuthUser;
};
