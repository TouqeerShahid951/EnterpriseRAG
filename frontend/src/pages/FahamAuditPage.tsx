import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, Database, FileText, ShieldCheck, UserRound } from "lucide-react";

import { auditApi } from "../api/contracts";
import { EmptyPanel, InlineMessage } from "../components/layout/Common";
import { FahamBasicPage } from "../components/layout/FahamWorkspace";
import type { RouteId } from "../routes";
import type { AuditEvent, User as AuthUser } from "../types/api";
import { errorMessage, formatDateTime } from "../utils/format";

export function FahamAuditPage({ onLogout, onNavigate, user }: Props) {
  const auditQuery = useQuery({ queryKey: ["audit-log"], queryFn: auditApi.list, retry: false });
  const events = auditQuery.data?.items ?? [];
  const eventTypeCount = useMemo(() => new Set(events.map((event) => event.event_type)).size, [events]);
  const documentEventCount = events.filter((event) => event.target_type === "document" || typeof event.payload.doc_id === "string").length;
  const actorCount = useMemo(() => new Set(events.map((event) => event.actor_id).filter(Boolean)).size, [events]);

  return (
    <FahamBasicPage
      activeRoute="activity-log"
      onLogout={onLogout}
      onNavigate={onNavigate}
      title="System Audit"
      subtitle="Append-only activity for visible Knowledge Spaces, document mutations, ingestion status, and authentication events."
      user={user}
    >
      <div className="grid gap-3 md:grid-cols-3">
        <AuditMetric icon={<Activity size={17} />} label="Visible events" value={auditQuery.isLoading ? "..." : String(events.length)} />
        <AuditMetric icon={<FileText size={17} />} label="Document events" value={auditQuery.isLoading ? "..." : String(documentEventCount)} />
        <AuditMetric icon={<ShieldCheck size={17} />} label="Event types" value={auditQuery.isLoading ? "..." : String(eventTypeCount)} detail={actorCount ? `${actorCount} actors` : undefined} />
      </div>

      <section className="sv-card mt-5 overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-border p-4">
          <div>
            <h2 className="sv-section-title">Audit Trail</h2>
            <p className="text-body-md text-on-surface-variant">Newest visible events first.</p>
          </div>
          <span className="sv-pill">{auditQuery.isLoading ? "Loading" : `${events.length} events`}</span>
        </div>

        {auditQuery.isError ? <InlineMessage tone="error">{errorMessage(auditQuery.error, "Unable to load audit events.")}</InlineMessage> : null}
        {auditQuery.isLoading ? <EmptyPanel>Loading audit events.</EmptyPanel> : null}

        {!auditQuery.isLoading && events.length > 0 ? (
          <div className="sv-table-wrap">
            <table className="sv-table">
              <thead>
                <tr>
                  <th>Event</th>
                  <th>Target</th>
                  <th>Actor</th>
                  <th>Payload</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id} className="sv-table-row">
                    <td>
                      <strong className="block text-on-surface">{event.event_type}</strong>
                      <small className="text-secondary">{event.id}</small>
                    </td>
                    <td>
                      <TargetSummary event={event} />
                    </td>
                    <td>
                      <span className="flex items-center gap-2 text-body-md text-on-surface">
                        <UserRound size={15} className="text-secondary" />
                        {event.actor_id ?? "System"}
                      </span>
                    </td>
                    <td>
                      <PayloadSummary payload={event.payload} />
                    </td>
                    <td className="text-secondary">{formatDateTime(event.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {!auditQuery.isLoading && events.length === 0 ? <EmptyPanel>No visible audit events yet.</EmptyPanel> : null}
      </section>
    </FahamBasicPage>
  );
}

function AuditMetric({ detail, icon, label, value }: { detail?: string; icon: JSX.Element; label: string; value: string }) {
  return (
    <div className="sv-metric">
      <div className="flex items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">{icon}</span>
        <span>
          <span className="block text-label-md text-secondary">{label}</span>
          <strong className="text-body-lg text-on-surface">{value}</strong>
          {detail ? <small className="block text-secondary">{detail}</small> : null}
        </span>
      </div>
    </div>
  );
}

function TargetSummary({ event }: { event: AuditEvent }) {
  if (!event.target_type && !event.target_id) return <span className="text-secondary">Workspace</span>;
  return (
    <span className="flex items-start gap-2 text-body-md text-on-surface">
      <Database size={15} className="mt-0.5 shrink-0 text-secondary" />
      <span className="min-w-0">
        <strong className="block">{event.target_type ?? "target"}</strong>
        {event.target_id ? <small className="block break-all text-secondary">{event.target_id}</small> : null}
      </span>
    </span>
  );
}

function PayloadSummary({ payload }: { payload: Record<string, unknown> }) {
  const entries = Object.entries(payload);
  if (entries.length === 0) return <span className="text-secondary">No payload</span>;
  return (
    <div className="flex max-w-xl flex-wrap gap-1.5">
      {entries.slice(0, 5).map(([key, value]) => (
        <span key={key} className="sv-pill">
          {key}: {formatPayloadValue(value)}
        </span>
      ))}
      {entries.length > 5 ? <span className="sv-pill">+{entries.length - 5}</span> : null}
    </div>
  );
}

function formatPayloadValue(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

type Props = {
  onLogout: () => void;
  onNavigate: (route: RouteId) => void;
  user: AuthUser;
};
