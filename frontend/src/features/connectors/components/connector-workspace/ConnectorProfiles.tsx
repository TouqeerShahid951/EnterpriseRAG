import { CheckCircle2, Database, Loader2, MoreHorizontal, Pencil, Search, Trash2 } from "lucide-react";

import { InlineMessage } from "@/components/layout/Common";
import { ConnectorEmptyState, ConnectorStatusPill } from "@/features/connectors/components/connector-workspace/ConnectorPrimitives";
import { clearanceLevelLabel } from "@/lib/auth/authz";
import type { ClearanceLevel, ConnectorProfile, ConnectorSchemaCatalog } from "@/types/api";
import {
  catalogAccessPillClass,
  catalogAccessStateLabel,
  catalogAccessStateHint,
  catalogReviewLabel,
  catalogReviewPillClass,
  catalogScopeSummary,
  connectorSchemaAccessSummary,
  connectorTypeLabel,
  formatDateTime,
  latestConnectorCatalog,
  nextConnectorAction,
  profileEndpointSummary,
  profileHealthLabel,
  profileHealthPillClass,
  normalizeCatalogJson,
  profileTestDetail,
  schemaCatalogAllowedRelationships,
  schemaCatalogReviewStats,
} from "@/features/connectors/utils/connectorPanelUtils";
export { ConnectorProfileEditor, ConnectorProfilePanel } from "@/features/connectors/components/connector-workspace/ConnectorProfileForms";


export function ConnectorProfileCards({ catalogsByProfile = {}, emptyMessage, isLoading, onDeleteProfile, onEditProfile, onOpenCatalog, onProfileAction, onViewLiveAccess, pendingActionId, pendingActionType, pendingDeleteProfileId, profiles }: ConnectorProfileCardsProps) {
  if (isLoading) return <p className="mt-3 text-body-md text-secondary">Loading database connections.</p>;
  if (profiles.length === 0) {
    return emptyMessage ? (
      <p className="mt-3 rounded-md border border-surface-border bg-surface p-3 text-body-md text-on-surface-variant">{emptyMessage}</p>
    ) : null;
  }
  return (
    <div className="sv-table-wrap connector-profile-table-wrap mt-3">
      <table className="sv-table connector-profile-table">
        <thead>
          <tr>
            <th>Connection</th>
            <th>Health</th>
            <th>Schema Review</th>
            <th>Live DB</th>
            <th className="connector-actions-column">Actions</th>
          </tr>
        </thead>
        <tbody>
          {profiles.map((profile) => {
            const currentCatalog = latestConnectorCatalog(catalogsByProfile[profile.id] ?? []);
            return (
              <tr key={profile.id} className="sv-table-row">
                <td className="align-top" data-label="Connection">
                  <div className="connector-identity-cell">
                    <strong className="block text-on-surface">{profile.name}</strong>
                    <span className="text-label-md font-bold text-on-surface-variant">{connectorTypeLabel(profile.connector_type)}</span>
                    <small className="text-secondary">{profileEndpointSummary(profile)}</small>
                  </div>
                </td>
                <td className="align-top" data-label="Health">
                  <div className="connector-status-stack">
                    <ConnectorStatusPill className={profileHealthPillClass(profile)} label={profileHealthLabel(profile)} minWidth="7.25rem" />
                    <small className={profile.last_test_status === "failed" ? "block text-error-red" : "block text-secondary"}>{profileTestDetail(profile)}</small>
                  </div>
                </td>
                <td className="align-top" data-label="Schema Review">
                  {currentCatalog ? (
                    <ConnectorSchemaProgress catalog={currentCatalog} />
                  ) : (
                    <div className="connector-status-stack">
                      <ConnectorStatusPill className="sv-pill sv-pill-warning" label="Needs review" minWidth="8.5rem" />
                      <small className="block text-secondary">Read schema, then prepare review</small>
                    </div>
                  )}
                </td>
                <td className="align-top" data-label="Live DB">
                  <div className="connector-status-stack">
                    <ConnectorStatusPill className={catalogAccessPillClass(currentCatalog?.status ?? "draft")} label={catalogAccessStateLabel(currentCatalog?.status ?? "draft")} minWidth="7.25rem" />
                    <small className="block text-secondary">{catalogAccessStateHint(currentCatalog?.status ?? "draft")}</small>
                  </div>
                </td>
                <td className="connector-actions-cell align-top" data-label="Actions">
                  <ConnectorRowActions
                    catalog={currentCatalog}
                    onDeleteProfile={onDeleteProfile}
                    onEditProfile={onEditProfile}
                    onOpenCatalog={onOpenCatalog}
                    onProfileAction={onProfileAction}
                    onViewLiveAccess={onViewLiveAccess}
                    pendingActionId={pendingActionId}
                    pendingActionType={pendingActionType}
                    pendingDeleteProfileId={pendingDeleteProfileId}
                    profile={profile}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ConnectorSchemaProgress({ catalog }: { catalog: ConnectorSchemaCatalog }) {
  const catalogJson = normalizeCatalogJson(catalog.catalog_json);
  const stats = schemaCatalogReviewStats(catalogJson);
  const relationships = catalogJson.relationships ?? [];
  const allowedRelationships = schemaCatalogAllowedRelationships(relationships);
  const totalItems = stats.totalTables + stats.totalColumns + relationships.length;
  const allowedItems = stats.allowedTables + stats.allowedColumns + allowedRelationships;
  const percent = totalItems === 0 ? 0 : Math.round((allowedItems / totalItems) * 100);

  return (
    <div className="connector-schema-progress">
      <div className="connector-schema-progress-header">
        <ConnectorStatusPill className={catalogReviewPillClass(catalog.status)} label={catalogReviewLabel(catalog.status)} minWidth="8.5rem" />
        <span className="text-label-md font-bold text-on-surface">{percent}% allowed</span>
      </div>
      <div
        aria-label={`Schema access coverage ${percent}%`}
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={percent}
        className="connector-schema-progress-track"
        role="progressbar"
      >
        <span style={{ width: `${percent}%` }} />
      </div>
      <small className="block text-secondary">{connectorSchemaAccessSummary(catalog)}</small>
    </div>
  );
}

function ConnectorRowActions({
  catalog,
  onDeleteProfile,
  onEditProfile,
  onOpenCatalog,
  onProfileAction,
  onViewLiveAccess,
  pendingActionId,
  pendingActionType,
  pendingDeleteProfileId,
  profile,
}: ConnectorRowActionsProps) {
  const nextAction = nextConnectorAction(profile, catalog);
  const profileActionPending = pendingActionId === profile.id;
  const primaryPending = profileActionPending && (
    (nextAction === "test" && pendingActionType === "test")
    || (nextAction === "read_schema" && pendingActionType === "introspect")
  );
  const primaryLabel = primaryPending
    ? nextAction === "test" ? "Testing" : "Reading schema"
    : nextAction === "test" ? "Test Connection"
      : nextAction === "read_schema" ? "Read Schema"
        : nextAction === "live" ? "View Live Access"
          : "Review Access";

  function runPrimaryAction() {
    if (nextAction === "test") return onProfileAction("test", profile.id);
    if (nextAction === "read_schema") return onProfileAction("introspect", profile.id);
    if (nextAction === "live") return onViewLiveAccess(profile);
    if (catalog) onOpenCatalog(profile, catalog);
  }

  return (
    <div className="connector-row-actions">
      <button
        type="button"
        id={`connector-primary-action-${profile.id}`}
        disabled={profileActionPending}
        onClick={runPrimaryAction}
        className="sv-action-secondary connector-row-primary-action"
      >
        {primaryPending ? <Loader2 className="animate-spin" size={14} /> : nextAction === "read_schema" ? <Search size={14} /> : nextAction === "live" ? <Database size={14} /> : <CheckCircle2 size={14} />}
        {primaryLabel}
      </button>
      <details className="connector-row-menu">
        <summary aria-label={`More actions for ${profile.name}`} title="More actions">
          <MoreHorizontal size={16} />
        </summary>
        <div className="connector-row-menu-items">
          <button type="button" onClick={() => onEditProfile(profile)}>
            <Pencil size={14} />
            Edit
          </button>
          <button type="button" disabled={profileActionPending} onClick={() => onProfileAction("test", profile.id)}>
            {profileActionPending && pendingActionType === "test" ? <Loader2 className="animate-spin" size={14} /> : <CheckCircle2 size={14} />}
            {profileActionPending && pendingActionType === "test" ? "Testing" : "Test"}
          </button>
          <button
            type="button"
            disabled={profileActionPending || profile.last_test_status !== "ok"}
            onClick={() => onProfileAction("introspect", profile.id)}
            title={profile.last_test_status === "ok" ? undefined : "Test the connection successfully before reading its schema."}
          >
            {profileActionPending && pendingActionType === "introspect" ? <Loader2 className="animate-spin" size={14} /> : <Search size={14} />}
            {profileActionPending && pendingActionType === "introspect" ? "Reading" : "Read Schema"}
          </button>
          <button type="button" disabled={pendingDeleteProfileId === profile.id} onClick={() => onDeleteProfile(profile)} className="connector-row-menu-danger">
            {pendingDeleteProfileId === profile.id ? <Loader2 className="animate-spin" size={14} /> : <Trash2 size={14} />}
            {pendingDeleteProfileId === profile.id ? "Deleting" : "Delete"}
          </button>
        </div>
      </details>
    </div>
  );
}

export function ConnectorCatalogReadiness({ catalogsByProfile, connectorProfiles, isError, isLoading, onOpenCatalog, onProfileAction, pendingActionId, pendingActionType }: ConnectorCatalogReadinessProps) {
  const rows = connectorProfiles.map((profile) => {
    const current = latestConnectorCatalog(catalogsByProfile[profile.id] ?? []);
    return { catalog: current, profile };
  });
  const reviewCount = rows.filter(({ catalog }) => Boolean(catalog)).length;
  const approved = rows.filter(({ catalog }) => catalog?.status === "approved");
  return (
    <section className="rounded-lg border border-surface-border bg-surface-container-low p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="sv-section-title">Schema Reviews</h3>
        <p className="text-label-md text-secondary">{approved.length} enabled</p>
      </div>
      {isError ? <InlineMessage tone="error">Unable to load database access reviews.</InlineMessage> : null}
      {isLoading ? <p className="text-body-md text-secondary">Loading database access reviews.</p> : null}
      {!isLoading && connectorProfiles.length === 0 ? (
        <ConnectorEmptyState
          detail="Add a connection first. After schema is read, prepare a review to choose tables, columns, and joins."
          title="No connections to review"
        />
      ) : null}
      {!isLoading && connectorProfiles.length > 0 ? (
        <div className="sv-table-wrap connector-secondary-table-wrap">
          <table className="sv-table connector-secondary-table">
            <thead>
              <tr>
                <th>Connection</th>
                <th>Review State</th>
                <th>Allowed Schema</th>
                <th>Access Scope</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ catalog, profile }) => (
                <tr key={profile.id} className="sv-table-row">
                  <td data-label="Connection">
                    <strong className="block text-on-surface">{profile.name}</strong>
                    <small className="text-secondary">{connectorTypeLabel(profile.connector_type)}</small>
                  </td>
                  <td data-label="Review State">
                    {catalog ? (
                      <ConnectorStatusPill className={catalogReviewPillClass(catalog.status)} label={catalogReviewLabel(catalog.status)} />
                    ) : (
                      <ConnectorStatusPill className="sv-pill sv-pill-warning" label="Needs review" />
                    )}
                  </td>
                  <td data-label="Allowed Schema">{catalog ? connectorSchemaAccessSummary(catalog) : "No schema review prepared"}</td>
                  <td data-label="Access Scope">{catalog ? `${catalogScopeSummary(catalog)} - ${clearanceLevelLabel(catalog.clearance_level as ClearanceLevel)}` : "Choose owner space during review"}</td>
                  <td data-label="Updated">{catalog ? formatDateTime(catalog.updated_at ?? catalog.created_at) : "Not prepared"}</td>
                  <td data-label="Actions">
                    {catalog ? (
                      <button type="button" onClick={() => onOpenCatalog(profile, catalog)} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary">
                        Review Access
                      </button>
                    ) : (
                      <button
                        type="button"
                        disabled={pendingActionId === profile.id}
                        onClick={() => onProfileAction(profile.last_test_status === "ok" ? "introspect" : "test", profile.id)}
                        className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50"
                      >
                        <span className="inline-flex items-center gap-1">
                          {pendingActionId === profile.id ? <Loader2 className="animate-spin" size={14} /> : profile.last_test_status === "ok" ? <Search size={14} /> : <CheckCircle2 size={14} />}
                          {pendingActionId === profile.id
                            ? pendingActionType === "test" ? "Testing" : "Reading schema"
                            : profile.last_test_status === "ok" ? "Read Schema" : "Test Connection"}
                        </span>
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {reviewCount === 0 ? <p className="mt-3 text-label-md text-secondary">No reviews are prepared yet. Test a connection, then read its schema to start the guided review.</p> : null}
        </div>
      ) : null}
    </section>
  );
}

export type ConnectorProfileCardsProps = {
  catalogsByProfile?: Record<string, ConnectorSchemaCatalog[]>;
  emptyMessage: string;
  isLoading: boolean;
  onDeleteProfile: (profile: ConnectorProfile) => void;
  onEditProfile: (profile: ConnectorProfile) => void;
  onOpenCatalog: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog) => void;
  onProfileAction: (action: "test" | "introspect", id: string) => void;
  onViewLiveAccess: (profile: ConnectorProfile) => void;
  pendingDeleteProfileId: string | null;
  pendingActionId: string | null;
  pendingActionType: "test" | "introspect" | null;
  profiles: ConnectorProfile[];
};

type ConnectorRowActionsProps = {
  catalog: ConnectorSchemaCatalog | null;
  onDeleteProfile: (profile: ConnectorProfile) => void;
  onEditProfile: (profile: ConnectorProfile) => void;
  onOpenCatalog: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog) => void;
  onProfileAction: (action: "test" | "introspect", id: string) => void;
  onViewLiveAccess: (profile: ConnectorProfile) => void;
  pendingActionId: string | null;
  pendingActionType: "test" | "introspect" | null;
  pendingDeleteProfileId: string | null;
  profile: ConnectorProfile;
};

export type ConnectorCatalogReadinessProps = {
  catalogsByProfile: Record<string, ConnectorSchemaCatalog[]>;
  connectorProfiles: ConnectorProfile[];
  isError: boolean;
  isLoading: boolean;
  onOpenCatalog: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog) => void;
  onProfileAction: (action: "test" | "introspect", id: string) => void;
  pendingActionId: string | null;
  pendingActionType: "test" | "introspect" | null;
};
