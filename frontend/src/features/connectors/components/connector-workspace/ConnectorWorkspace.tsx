import type { FormEvent } from "react";
import { CheckCircle2, Pencil, Plus } from "lucide-react";

import { InlineMessage } from "@/components/layout/Common";
import { Modal } from "@/components/layout/Modal";
import { ConnectorCatalogEditor } from "@/features/connectors/components/connector-workspace/ConnectorCatalogEditor";
import {
  ConnectorCatalogReadiness,
  ConnectorProfileCards,
  ConnectorProfileEditor,
  ConnectorProfilePanel,
} from "@/features/connectors/components/connector-workspace/ConnectorProfiles";
import { WORKSPACE_TIMEZONE } from "@/features/ingestion/state/folderIngest";
import type { ClearanceLevel, ConnectorProfile, ConnectorSchemaCatalog } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";
import type { UpdateConnectorSchemaCatalogRequest } from "@/lib/api/contracts";
import {
  connectorWorkspaceTabCount,
  connectorWorkspaceTabDetail,
  formatDateTime,
  latestConnectorCatalog,
  type AiDraftProgress,
  type ConnectorCatalogEditorState,
  type ConnectorMetricTone,
  type ConnectorProfileDraft,
  type ConnectorProfileEditorState,
  type ConnectorWorkspaceTab,
} from "@/features/connectors/utils/connectorPanelUtils";
import { ConnectorDiagnosticsPanel, ConnectorLiveAccessPanel } from "@/features/connectors/components/connector-workspace/ConnectorAccessPanels";


const connectorWorkspaceTabs: Array<{ id: ConnectorWorkspaceTab; label: string }> = [
  { id: "connections", label: "Connections" },
  { id: "schema_reviews", label: "Schema Reviews" },
  { id: "live_access", label: "Live Access" },
  { id: "diagnostics", label: "Diagnostics" },
];

export function ConnectorProfileSetup({
  onClose,
  onProfileAction,
  onProfileChange,
  onProfileSubmit,
  pendingProfileActionId,
  pendingProfileActionType,
  profileDraft,
  profileError,
  profileMutationError,
  profilesCreating,
  profilesLoading,
}: ConnectorProfileSetupProps) {
  return (
    <div className="space-y-5">
      <ConnectorProfilePanel
        draft={profileDraft}
        error={profileError}
        isCreating={profilesCreating}
        isLoading={profilesLoading}
        mutationError={profileMutationError}
        onChange={onProfileChange}
        onSubmit={onProfileSubmit}
        onProfileAction={onProfileAction}
        pendingActionId={pendingProfileActionId}
        pendingActionType={pendingProfileActionType}
        profiles={[]}
        showExisting={false}
      />
      <div className="flex justify-end">
        <button type="button" onClick={onClose} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-label-md font-bold text-on-surface hover:border-primary">
          Cancel
        </button>
      </div>
    </div>
  );
}

export function ConnectorOverview({
  activeTab,
  catalogsByProfile,
  catalogsError,
  catalogsLoading,
  catalogEditor,
  catalogSaveError,
  catalogSaving,
  clearanceOptions,
  connectorProfiles,
  draftCreationError,
  enrichmentProgress,
  isProfilesError,
  isProfilesLoading,
  onCatalogEditorClose,
  onCatalogSave,
  onContinueAiDraft,
  onCreateAiDraft,
  onDeleteProfile,
  onEditProfile,
  onOpenCatalog,
  onProfileEditCancel,
  onProfileEditChange,
  onProfileEditSubmit,
  onProfileAction,
  onStartSetup,
  onTabChange,
  pendingAiDraftProfileId,
  pendingDeleteProfileId,
  pendingProfileActionId,
  pendingProfileActionType,
  profileEditError,
  profileEditor,
  profileMutationError,
  profileSaving,
  writableSpacePaths,
}: ConnectorOverviewProps) {
  const catalogEntries = connectorProfiles.flatMap((profile) => {
    const current = latestConnectorCatalog(catalogsByProfile[profile.id] ?? []);
    return current ? [{ catalog: current, profile }] : [];
  });
  const catalogs = catalogEntries.map(({ catalog }) => catalog);
  const approvedCatalogCount = catalogs.filter((catalog) => catalog.status === "approved").length;
  const pendingReviewCount = Math.max(connectorProfiles.length - catalogEntries.length, 0);
  const needsReviewCount = connectorProfiles.length - approvedCatalogCount;
  const failedTestCount = connectorProfiles.filter((profile) => profile.last_test_status === "failed").length;
  const latestCatalog = catalogs
    .map((catalog) => catalog.updated_at ?? catalog.created_at)
    .filter((value): value is string => Boolean(value))
    .sort()
    .reverse()[0] ?? null;

  return (
    <div className="space-y-5">
      <div className="connector-workflow-bar">
        <div className="connector-workflow-copy">
          <p className="sv-label">Connector workflow</p>
          <h2 id="database-connectors-workspace-title" className="sv-section-title">Connect, review, enable</h2>
          <p className="mt-1 text-body-md text-on-surface-variant">Add read-only credentials, read the schema, choose allowed tables and joins, then make the review available to Live DB answers.</p>
          <p className="connector-workflow-path">Connect / Review schema / Enable Live DB</p>
        </div>
        <div className="connector-workflow-actions">
          <button type="button" onClick={onStartSetup} className="sv-action-primary">
            <Plus size={16} />
            Add Connection
          </button>
          <span className="connector-timezone-note">Timezone: {WORKSPACE_TIMEZONE}</span>
        </div>
      </div>

      <dl className="connector-overview-grid">
        <ConnectorOverviewMetric label="Connections" value={isProfilesLoading ? "Loading" : `${connectorProfiles.length} configured`} detail="Encrypted SQL Server and PostgreSQL credentials" />
        <ConnectorOverviewMetric
          detail={pendingReviewCount > 0 ? `${pendingReviewCount} connection${pendingReviewCount === 1 ? "" : "s"} need review` : "All saved connections have a review"}
          label="Schema Review"
          tone={pendingReviewCount > 0 ? "warning" : "success"}
          value={catalogsLoading ? "Loading" : `${catalogEntries.length} ready`}
        />
        <ConnectorOverviewMetric
          detail={needsReviewCount > 0 ? `${needsReviewCount} connection${needsReviewCount === 1 ? "" : "s"} not live yet` : "Available to Live DB answers"}
          label="Live DB"
          tone={approvedCatalogCount > 0 ? "success" : "neutral"}
          value={catalogsLoading ? "Loading" : `${approvedCatalogCount} enabled`}
        />
        <ConnectorOverviewMetric
          detail={latestCatalog ? `Latest review ${formatDateTime(latestCatalog)}` : "Run tests and schema reads from Connections"}
          label="Diagnostics"
          tone={failedTestCount > 0 ? "danger" : "success"}
          value={failedTestCount > 0 ? `${failedTestCount} issue${failedTestCount === 1 ? "" : "s"}` : "Clear"}
        />
      </dl>

      <ConnectorWorkspaceTabs
        counts={{
          connections: connectorProfiles.length,
          diagnostics: failedTestCount,
          liveAccess: approvedCatalogCount,
          schemaReviews: catalogEntries.length,
        }}
        onChange={onTabChange}
        value={activeTab}
      />

      {activeTab === "connections" ? (
        <section className="connector-table-section">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="sv-section-title">Connections</h3>
            <p className="text-label-md text-secondary">{connectorProfiles.length} saved</p>
          </div>
          {isProfilesError ? <InlineMessage tone="error">Unable to load database connections.</InlineMessage> : null}
          <ConnectorProfileCards
            catalogsByProfile={catalogsByProfile}
            emptyMessage="No database connections yet. Add a connection, then read schema to prepare Live DB access."
            isLoading={isProfilesLoading}
            onCreateAiDraft={onCreateAiDraft}
            onDeleteProfile={onDeleteProfile}
            onEditProfile={onEditProfile}
            onOpenCatalog={onOpenCatalog}
            onProfileAction={onProfileAction}
            pendingDeleteProfileId={pendingDeleteProfileId}
            pendingAiDraftProfileId={pendingAiDraftProfileId}
            pendingActionId={pendingProfileActionId}
            pendingActionType={pendingProfileActionType}
            profiles={connectorProfiles}
            writableSpacePaths={writableSpacePaths}
          />
          {!profileEditor && profileMutationError ? <InlineMessage tone="error">{errorMessage(profileMutationError, "Unable to manage database connection.")}</InlineMessage> : null}
          {draftCreationError ? <InlineMessage tone="error">{errorMessage(draftCreationError, "Unable to prepare a database access review.")}</InlineMessage> : null}
        </section>
      ) : null}

      {activeTab === "schema_reviews" ? (
        <ConnectorCatalogReadiness
          catalogsByProfile={catalogsByProfile}
          connectorProfiles={connectorProfiles}
          isError={catalogsError}
          isLoading={catalogsLoading}
          onCreateAiDraft={onCreateAiDraft}
          onOpenCatalog={onOpenCatalog}
          pendingAiDraftProfileId={pendingAiDraftProfileId}
          writableSpacePaths={writableSpacePaths}
        />
      ) : null}

      {activeTab === "live_access" ? (
        <ConnectorLiveAccessPanel
          catalogsByProfile={catalogsByProfile}
          connectorProfiles={connectorProfiles}
          isError={catalogsError}
          isLoading={catalogsLoading}
          onOpenCatalog={onOpenCatalog}
        />
      ) : null}

      {activeTab === "diagnostics" ? (
        <ConnectorDiagnosticsPanel
          catalogsByProfile={catalogsByProfile}
          connectorProfiles={connectorProfiles}
          isError={isProfilesError || catalogsError}
          isLoading={isProfilesLoading || catalogsLoading}
          onProfileAction={onProfileAction}
          pendingActionId={pendingProfileActionId}
          pendingActionType={pendingProfileActionType}
        />
      ) : null}
      <Modal
        description="Update the saved connection details. Replacement credentials are optional."
        icon={<Pencil size={18} />}
        onClose={onProfileEditCancel}
        open={Boolean(profileEditor)}
        size="lg"
        title="Edit Connection"
      >
        {profileEditor ? (
          <ConnectorProfileEditor
            draft={profileEditor.draft}
            error={profileEditError}
            isSaving={profileSaving}
            mutationError={profileMutationError}
            onCancel={onProfileEditCancel}
            onChange={onProfileEditChange}
            onSubmit={onProfileEditSubmit}
            profile={profileEditor.profile}
          />
        ) : null}
      </Modal>
      <Modal
        description="Choose the tables, columns, and joins Live DB may use. AI descriptions remain editable."
        icon={<CheckCircle2 size={18} />}
        onClose={onCatalogEditorClose}
        open={Boolean(catalogEditor)}
        size="lg"
        title="Database Access Review"
      >
        {catalogEditor ? (
          enrichmentProgress?.catalogId === catalogEditor.catalog.id ? (
            <ConnectorSchemaEnrichmentProgress progress={enrichmentProgress} />
          ) : (
            <ConnectorCatalogEditor
              catalog={catalogEditor.catalog}
              clearanceOptions={clearanceOptions}
              isSaving={catalogSaving}
              mutationError={catalogSaveError}
              onClose={onCatalogEditorClose}
              onContinueAiEnrichment={() => onContinueAiDraft(catalogEditor.profile, catalogEditor.catalog)}
              onSave={(request) => onCatalogSave(catalogEditor.profile, catalogEditor.catalog, request)}
              profile={catalogEditor.profile}
              writableSpacePaths={writableSpacePaths}
            />
          )
        ) : null}
      </Modal>
    </div>
  );
}

function ConnectorSchemaEnrichmentProgress({ progress }: { progress: AiDraftProgress }) {
  const percent = progress.total === 0 ? 100 : Math.round((progress.completed / progress.total) * 100);
  return (
    <section className="space-y-4" aria-live="polite" aria-busy="true">
      <div>
        <p className="sv-label">Enriching schema</p>
        <h3 className="mt-1 text-body-lg font-extrabold text-on-surface">
          {progress.completed} of {progress.total} tables processed
        </h3>
        <p className="mt-1 text-body-md text-on-surface-variant">
          {progress.currentTable ? `Generating descriptions for ${progress.currentTable}.` : "Saving the latest table metadata."}
        </p>
      </div>
      <div>
        <div className="h-2 overflow-hidden rounded bg-surface-container-high" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label="Schema enrichment progress">
          <div className="h-full bg-primary transition-[width] duration-200" style={{ width: `${percent}%` }} />
        </div>
        <div className="mt-2 flex items-center justify-between gap-3 text-label-md text-secondary">
          <span>{percent}% complete</span>
          <span>{progress.failed > 0 ? `${progress.failed} failed` : "Each table is saved as it completes"}</span>
        </div>
      </div>
      <p className="rounded-md border border-surface-border bg-surface px-3 py-2 text-body-md text-on-surface-variant">
        You may close this window. Enrichment will continue, and completed tables will remain saved.
      </p>
    </section>
  );
}

function ConnectorOverviewMetric({ detail, label, tone = "neutral", value }: ConnectorOverviewMetricProps) {
  return (
    <div className={`connector-overview-metric connector-overview-metric-${tone}`}>
      <dt className="text-label-md font-bold uppercase tracking-wide text-secondary">{label}</dt>
      <dd className="mt-2 text-body-lg font-extrabold text-on-surface">{value}</dd>
      <p className="mt-1 text-label-md text-on-surface-variant">{detail}</p>
    </div>
  );
}

function ConnectorWorkspaceTabs({ counts, onChange, value }: ConnectorWorkspaceTabsProps) {
  return (
    <div className="knowledge-inspector-tabs" role="tablist" aria-label="Database connector sections">
      {connectorWorkspaceTabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={value === tab.id}
          className={value === tab.id ? "knowledge-inspector-tab-active" : "knowledge-inspector-tab"}
          onClick={() => onChange(tab.id)}
        >
          <span>{tab.label}</span>
          <span className="connector-tab-count" aria-hidden="true">{connectorWorkspaceTabCount(tab.id, counts)}</span>
          <span className="sr-only">, {connectorWorkspaceTabDetail(tab.id, counts)}</span>
        </button>
      ))}
    </div>
  );
}

export type ConnectorProfileSetupProps = {
  connectorProfiles: ConnectorProfile[];
  onClose: () => void;
  onProfileAction: (action: "test" | "introspect", id: string) => void;
  onProfileChange: (patch: Partial<ConnectorProfileDraft>) => void;
  onProfileSubmit: (event: FormEvent<HTMLFormElement>) => void;
  pendingProfileActionId: string | null;
  pendingProfileActionType: "test" | "introspect" | null;
  profileDraft: ConnectorProfileDraft;
  profileError: string | null;
  profileMutationError: unknown;
  profilesCreating: boolean;
  profilesLoading: boolean;
};

export type ConnectorOverviewProps = {
  activeTab: ConnectorWorkspaceTab;
  catalogsByProfile: Record<string, ConnectorSchemaCatalog[]>;
  catalogsError: boolean;
  catalogsLoading: boolean;
  catalogEditor: ConnectorCatalogEditorState | null;
  catalogSaveError: unknown;
  catalogSaving: boolean;
  clearanceOptions: ClearanceLevel[];
  connectorProfiles: ConnectorProfile[];
  draftCreationError: unknown;
  enrichmentProgress: AiDraftProgress | null;
  isProfilesError: boolean;
  isProfilesLoading: boolean;
  onCatalogEditorClose: () => void;
  onCatalogSave: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog, request: UpdateConnectorSchemaCatalogRequest) => void;
  onContinueAiDraft: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog) => void;
  onCreateAiDraft: (profile: ConnectorProfile) => void;
  onDeleteProfile: (profile: ConnectorProfile) => void;
  onEditProfile: (profile: ConnectorProfile) => void;
  onOpenCatalog: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog) => void;
  onProfileEditCancel: () => void;
  onProfileEditChange: (patch: Partial<ConnectorProfileDraft>) => void;
  onProfileEditSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onProfileAction: (action: "test" | "introspect", id: string) => void;
  onStartSetup: () => void;
  onTabChange: (tab: ConnectorWorkspaceTab) => void;
  pendingAiDraftProfileId: string | null;
  pendingDeleteProfileId: string | null;
  pendingProfileActionId: string | null;
  pendingProfileActionType: "test" | "introspect" | null;
  profileEditError: string | null;
  profileEditor: ConnectorProfileEditorState | null;
  profileMutationError: unknown;
  profileSaving: boolean;
  writableSpacePaths: string[];
};

type ConnectorOverviewMetricProps = {
  detail: string;
  label: string;
  tone?: ConnectorMetricTone;
  value: string;
};

type ConnectorWorkspaceTabsProps = {
  counts: {
    connections: number;
    diagnostics: number;
    liveAccess: number;
    schemaReviews: number;
  };
  onChange: (tab: ConnectorWorkspaceTab) => void;
  value: ConnectorWorkspaceTab;
};
