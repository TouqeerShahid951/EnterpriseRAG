import { useEffect, useState } from "react";
import { Copy, Database, ExternalLink, FileText, UserRound, X } from "lucide-react";
import type { AuditEvent } from "@/types/api";
import {
  actorDisplay,
  auditCategory,
  auditCategoryLabel,
  auditImpactSummary,
  formatPayloadValue,
  payloadSummary,
  targetDisplay,
} from "@/features/audit/utils/audit";
import { eventGroupPath, eventLinks } from "@/features/audit/utils/auditPageState";
import { formatDateTime } from "@/lib/utils/format";

export function AuditTable({ events, onToggle, selectedEventId }: { events: AuditEvent[]; onToggle: (eventId: string) => void; selectedEventId: string | null }) {
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
          <button type="button" className="Prudentia-icon-button" onClick={onCopy} title={`Copy ${label}`}>
            <Copy size={14} />
            <span className="sr-only">{copied ? "Copied" : `Copy ${label}`}</span>
          </button>
        ) : null}
      </dd>
    </div>
  );
}
