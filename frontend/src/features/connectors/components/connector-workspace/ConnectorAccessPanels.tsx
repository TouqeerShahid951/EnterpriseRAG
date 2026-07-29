import { InlineMessage } from "@/components/layout/Common";
import { ConnectorEmptyState, ConnectorStatusPill } from "@/features/connectors/components/connector-workspace/ConnectorPrimitives";
import type { ClearanceLevel, ConnectorProfile, ConnectorSchemaCatalog } from "@/types/api";
import {
  catalogName,
  catalogScopeSummary,
  connectorSchemaAccessSummary,
  connectorTypeLabel,
  formatDateTime,
  latestConnectorCatalog,
  profileHealthLabel,
  profileHealthPillClass,
  profileTestDetail,
} from "@/features/connectors/utils/connectorPanelUtils";
import { clearanceLevelLabel } from "@/lib/auth/authz";

export function ConnectorLiveAccessPanel({ catalogsByProfile, connectorProfiles, isError, isLoading, onOpenCatalog }: ConnectorLiveAccessPanelProps) {
  const enabled = connectorProfiles.flatMap((profile) => {
    const current = latestConnectorCatalog(catalogsByProfile[profile.id] ?? []);
    return current?.status === "approved" ? [{ catalog: current, profile }] : [];
  });
  return (
    <section className="rounded-lg border border-surface-border bg-surface-container-low p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="sv-section-title">Live Access</h3>
        <p className="text-label-md text-secondary">{enabled.length} enabled</p>
      </div>
      {isError ? <InlineMessage tone="error">Unable to load Live DB access.</InlineMessage> : null}
      {isLoading ? <p className="text-body-md text-secondary">Loading Live DB access.</p> : null}
      {!isLoading && enabled.length === 0 ? (
        <ConnectorEmptyState
          detail="Review a schema and enable Live DB access before users can ask questions against a database connection."
          title="No Live DB access enabled"
        />
      ) : null}
      {!isLoading && enabled.length > 0 ? (
        <div className="sv-table-wrap connector-secondary-table-wrap">
          <table className="sv-table connector-secondary-table">
            <thead>
              <tr>
                <th>Connection</th>
                <th>Allowed Schema</th>
                <th>Knowledge Spaces</th>
                <th>Clearance</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {enabled.map(({ catalog, profile }) => (
                <tr key={catalog.id} className="sv-table-row">
                  <td data-label="Connection">
                    <strong className="block text-on-surface">{profile.name}</strong>
                    <small className="text-secondary">{connectorTypeLabel(profile.connector_type)}</small>
                  </td>
                  <td data-label="Allowed Schema">{connectorSchemaAccessSummary(catalog)}</td>
                  <td data-label="Knowledge Spaces">{catalogScopeSummary(catalog)}</td>
                  <td data-label="Clearance">{clearanceLevelLabel(catalog.clearance_level as ClearanceLevel)}</td>
                  <td data-label="Actions">
                    <button type="button" onClick={() => onOpenCatalog(profile, catalog)} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary">
                      Review Access
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

export function ConnectorDiagnosticsPanel({ catalogsByProfile, connectorProfiles, isError, isLoading, onProfileAction, pendingActionId, pendingActionType }: ConnectorDiagnosticsPanelProps) {
  return (
    <section className="rounded-lg border border-surface-border bg-surface-container-low p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="sv-section-title">Diagnostics</h3>
        <p className="text-label-md text-secondary">Tests, schema reads, and raw snapshots</p>
      </div>
      {isError ? <InlineMessage tone="error">Unable to load connector diagnostics.</InlineMessage> : null}
      {isLoading ? <p className="text-body-md text-secondary">Loading connector diagnostics.</p> : null}
      {!isLoading && connectorProfiles.length === 0 ? (
        <ConnectorEmptyState
          detail="Add a connection first. Diagnostics will show connection tests, schema read results, and raw schema snapshots."
          title="No diagnostics yet"
        />
      ) : null}
      {!isLoading && connectorProfiles.length > 0 ? (
        <div className="sv-table-wrap connector-secondary-table-wrap">
          <table className="sv-table connector-secondary-table">
            <thead>
              <tr>
                <th>Connection</th>
                <th>Last Test</th>
                <th>Current Review</th>
                <th>Latest Update</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {connectorProfiles.map((profile) => {
                const currentCatalog = latestConnectorCatalog(catalogsByProfile[profile.id] ?? []);
                return (
                  <tr key={profile.id} className="sv-table-row">
                    <td data-label="Connection">
                      <strong className="block text-on-surface">{profile.name}</strong>
                      <small className="text-secondary">{connectorTypeLabel(profile.connector_type)}</small>
                    </td>
                    <td data-label="Last Test">
                      <ConnectorStatusPill className={profileHealthPillClass(profile)} label={profileHealthLabel(profile)} />
                      <small className={profile.last_test_status === "failed" ? "mt-1 block text-error-red" : "mt-1 block text-secondary"}>{profileTestDetail(profile)}</small>
                    </td>
                    <td data-label="Current Review">{currentCatalog ? catalogName(currentCatalog, profile) : "No review prepared"}</td>
                    <td data-label="Latest Update">{currentCatalog ? formatDateTime(currentCatalog.updated_at ?? currentCatalog.created_at) : "No schema review"}</td>
                    <td data-label="Actions">
                      <span className="flex flex-wrap gap-2">
                        <button type="button" disabled={pendingActionId === profile.id} onClick={() => onProfileAction("test", profile.id)} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                          {pendingActionId === profile.id && pendingActionType === "test" ? "Testing" : "Test"}
                        </button>
                        <button type="button" disabled={pendingActionId === profile.id} onClick={() => onProfileAction("introspect", profile.id)} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                          {pendingActionId === profile.id && pendingActionType === "introspect" ? "Reading" : "Read Schema"}
                        </button>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

export type ConnectorLiveAccessPanelProps = {
  catalogsByProfile: Record<string, ConnectorSchemaCatalog[]>;
  connectorProfiles: ConnectorProfile[];
  isError: boolean;
  isLoading: boolean;
  onOpenCatalog: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog) => void;
};

export type ConnectorDiagnosticsPanelProps = {
  catalogsByProfile: Record<string, ConnectorSchemaCatalog[]>;
  connectorProfiles: ConnectorProfile[];
  isError: boolean;
  isLoading: boolean;
  onProfileAction: (action: "test" | "introspect", id: string) => void;
  pendingActionId: string | null;
  pendingActionType: "test" | "introspect" | null;
};
