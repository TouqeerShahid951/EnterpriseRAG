import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, ChevronLeft, ChevronRight, Database, Download, FileText, Search, ShieldCheck, SlidersHorizontal, UserRound, X } from "lucide-react";

import { adminApi, auditApi } from "@/lib/api/contracts";
import { canViewSpaceMetadata } from "@/lib/auth/authz";
import { InlineMessage } from "@/components/layout/Common";
import { PrudentiaWorkspace } from "@/components/layout/PrudentiaWorkspace";
import type { RouteId } from "@/routes/routes";
import type { User as AuthUser } from "@/types/api";
import {
  auditCategories,
} from "@/features/audit/utils/audit";
import { errorMessage } from "@/lib/utils/format";
import { flattenGroups, userSpacesFromPaths } from "@/lib/utils/groups";
import { AuditTable } from "@/features/audit/components/AuditEventTable";
import { AuditMetric, AuditSelect, AuditSkeleton } from "@/features/audit/components/AuditPagePrimitives";
import {
  PAGE_SIZE_OPTIONS,
  auditExportFilename,
  auditRequest,
  downloadBlob,
  emptyAuditSummary,
  initialAuditParam,
  initialLimitFromUrl,
  initialOffsetFromUrl,
  syncAuditUrl,
  useDebouncedText,
} from "@/features/audit/utils/auditPageState";


const TARGET_TYPE_OPTIONS = ["audit_log", "document", "user", "ingest_job", "folder_schedule", "generated_artifact", "query", "review_item", "workspace_ingest_config"];

export function PrudentiaAuditPage({ onLogout, onNavigate, user }: Props) {
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
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const debouncedSearch = useDebouncedText(search, 300);
  const canLoadDirectory = canViewSpaceMetadata(user);
  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, enabled: canLoadDirectory, retry: false });
  const spaceOptions = useMemo(
    () => (canLoadDirectory ? flattenGroups(groupsQuery.data?.items ?? []) : userSpacesFromPaths(user.group_paths)),
    [canLoadDirectory, groupsQuery.data?.items, user.group_paths],
  );
  const request = auditRequest({ actorQuery, category, createdFrom, createdTo, eventType, groupPath, limit, offset, search: debouncedSearch, targetId, targetType });
  const exportRequest = auditRequest({ actorQuery, category, createdFrom, createdTo, eventType, groupPath, limit, offset, search, targetId, targetType });
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

  async function exportCsv() {
    setExporting(true);
    setExportError(null);
    try {
      const blob = await auditApi.exportCsv(exportRequest);
      downloadBlob(blob, auditExportFilename());
    } catch (error) {
      setExportError(errorMessage(error, "Unable to export audit logs."));
    } finally {
      setExporting(false);
    }
  }

  return (
    <PrudentiaWorkspace activeRoute="activity-log" onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page" id="main-content">
        <div className="sv-page-inner sv-page-inner-workbench max-w-none">
          <header className="sv-page-header">
            <div>
              <p className="sv-eyebrow">Govern</p>
              <h1 className="sv-page-title">System Audit</h1>
              <p className="sv-page-subtitle">Investigate visible workspace activity by actor, target, Knowledge Space, event type, and time window.</p>
            </div>
          </header>

          {auditQuery.isError ? <InlineMessage tone="error">{errorMessage(auditQuery.error, "Unable to load audit events.")}</InlineMessage> : null}
          {groupsQuery.isError ? <InlineMessage tone="warning">{errorMessage(groupsQuery.error, "Unable to load Knowledge Space filters.")}</InlineMessage> : null}
          {exportError ? <InlineMessage tone="error">{exportError}</InlineMessage> : null}

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
                <button type="button" className="sv-action-secondary" disabled={exporting} onClick={() => void exportCsv()}>
                  <Download size={15} /> {exporting ? "Exporting" : "Export CSV"}
                </button>
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
                <input className="sv-input" value={actorQuery} onChange={(event) => resetOffset(setActorQuery, event.target.value)} placeholder="admin@prudentia.ai" />
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
    </PrudentiaWorkspace>
  );
}

type Props = {
  onLogout: () => void;
  onNavigate: (route: RouteId) => void;
  user: AuthUser;
};
