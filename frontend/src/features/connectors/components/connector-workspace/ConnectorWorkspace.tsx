import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { CheckCircle2, Database, Loader2, Pencil, Plus, Search } from "lucide-react";

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
  connectorFlowStep,
  connectorTypeLabel,
  formatDateTime,
  latestConnectorCatalog,
  profileEndpointSummary,
  profileTestDetail,
  type AiDraftProgress,
  type ConnectorCatalogEditorState,
  type ConnectorFlowStep,
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

const connectorFlowSteps = ["Connection", "Verify", "Schema", "Review", "Live"];

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
  enrichmentProgress,
  guidedProfileId,
  isProfilesError,
  isProfilesLoading,
  onCatalogEditorClose,
  onCatalogSave,
  onContinueAiDraft,
  onDeleteProfile,
  onEditProfile,
  onGuidedProfileChange,
  onOpenCatalog,
  onProfileEditCancel,
  onProfileEditChange,
  onProfileEditSubmit,
  onProfileAction,
  onStartSetup,
  onTabChange,
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
  const untestedCount = connectorProfiles.filter((profile) => profile.last_test_status === null).length;
  const diagnosticIssueCount = failedTestCount + untestedCount;
  const aggregateFlowStep = connectorProfiles.length === 0
    ? 0
    : diagnosticIssueCount > 0
      ? 1
      : pendingReviewCount > 0
        ? 2
        : needsReviewCount > 0
          ? 3
          : 4;
  const guidedProfile = connectorProfiles.find((profile) => profile.id === guidedProfileId) ?? null;
  const guidedCatalog = guidedProfile ? latestConnectorCatalog(catalogsByProfile[guidedProfile.id] ?? []) : null;
  const guidedCurrentStep = guidedProfile ? connectorFlowStep(guidedProfile, guidedCatalog) : null;
  const [guidedStep, setGuidedStep] = useState<0 | ConnectorFlowStep>(0);
  const latestCatalog = catalogs
    .map((catalog) => catalog.updated_at ?? catalog.created_at)
    .filter((value): value is string => Boolean(value))
    .sort()
    .reverse()[0] ?? null;

  useEffect(() => {
    if (!guidedProfile || guidedCurrentStep === null) return;
    setGuidedStep(guidedCurrentStep);
    onTabChange(connectorTabForFlowStep(guidedCurrentStep));
    focusGuidedAction(guidedProfile.id);
  }, [guidedCurrentStep, guidedProfile?.id, onTabChange]);

  const displayedCurrentFlowStep = guidedCurrentStep ?? aggregateFlowStep;

  function showGuidedStep(step: number) {
    if (!guidedProfile || guidedCurrentStep === null || step > guidedCurrentStep) return;
    const nextStep = step as 0 | ConnectorFlowStep;
    setGuidedStep(nextStep);
    onTabChange(connectorTabForFlowStep(nextStep));
    focusGuidedAction(guidedProfile.id);
  }

  return (
    <div className="space-y-5">
      <div className="connector-workflow-bar">
        <div className="connector-workflow-copy">
          <p className="sv-label">Connector workflow</p>
          <h2 id="database-connectors-workspace-title" className="sv-section-title">Connect, verify, review, enable</h2>
          <p className="mt-1 text-body-md text-on-surface-variant">
            {guidedProfile
              ? `Guiding ${guidedProfile.name}. Successful actions advance automatically; completed stages remain available.`
              : "Choose a connection to begin its guided setup. AI metadata stays editable and access always requires human approval."}
          </p>
          <ol className="connector-workflow-steps" aria-label="Database connector setup steps">
            {connectorFlowSteps.map((step, index) => {
              const state = index < displayedCurrentFlowStep ? "complete" : index === displayedCurrentFlowStep ? "current" : "upcoming";
              const available = Boolean(guidedProfile) && guidedCurrentStep !== null && index <= guidedCurrentStep;
              return (
                <li key={step} data-state={state} data-selected={guidedProfile && guidedStep === index ? "true" : undefined} aria-current={index === displayedCurrentFlowStep ? "step" : undefined}>
                  <button type="button" className="connector-workflow-step-button" disabled={!available} onClick={() => showGuidedStep(index)} aria-pressed={guidedProfile ? guidedStep === index : undefined}>
                    <span aria-hidden="true">{index < displayedCurrentFlowStep ? "✓" : index + 1}</span>
                    <strong>
                      {step}
                      <span className="sr-only"> — {state}{available ? ", available" : ""}</span>
                    </strong>
                  </button>
                </li>
              );
            })}
          </ol>
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
          value={catalogsLoading ? "Loading" : `${catalogEntries.length} prepared`}
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
          tone={failedTestCount > 0 ? "danger" : untestedCount > 0 ? "warning" : "success"}
          value={failedTestCount > 0 ? `${failedTestCount} failed` : untestedCount > 0 ? `${untestedCount} untested` : "Clear"}
        />
      </dl>

      {guidedProfile ? (
        <ConnectorGuidedStage
          catalog={guidedCatalog}
          onEditProfile={onEditProfile}
          onExit={() => {
            onGuidedProfileChange(null);
            onTabChange("connections");
            focusConnectorRowAction(guidedProfile.id);
          }}
          onOpenCatalog={onOpenCatalog}
          onProfileAction={onProfileAction}
          onViewLiveAccess={() => {
            onTabChange("live_access");
            focusWorkspaceTab("live_access");
          }}
          pendingActionId={pendingProfileActionId}
          pendingActionType={pendingProfileActionType}
          profile={guidedProfile}
          step={guidedStep}
        />
      ) : null}

      <ConnectorWorkspaceTabs
        counts={{
          connections: connectorProfiles.length,
          diagnostics: diagnosticIssueCount,
          liveAccess: approvedCatalogCount,
          schemaReviews: catalogEntries.length,
        }}
        onChange={onTabChange}
        value={activeTab}
      />
      <p className="sr-only" aria-live="polite">Showing {connectorWorkspaceTabs.find((tab) => tab.id === activeTab)?.label}</p>

      {activeTab === "connections" ? (
        <section id="connector-workspace-panel-connections" role="tabpanel" aria-labelledby="connector-workspace-tab-connections" className="connector-table-section">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="sv-section-title">Connections</h3>
            <p className="text-label-md text-secondary">{connectorProfiles.length} saved</p>
          </div>
          {isProfilesError ? <InlineMessage tone="error">Unable to load database connections.</InlineMessage> : null}
          <ConnectorProfileCards
            catalogsByProfile={catalogsByProfile}
            emptyMessage="No database connections yet. Add a connection, test it, then read its schema to prepare Live DB access."
            isLoading={isProfilesLoading}
            onDeleteProfile={onDeleteProfile}
            onEditProfile={onEditProfile}
            onOpenCatalog={(profile, catalog) => {
              onTabChange("schema_reviews");
              onOpenCatalog(profile, catalog);
            }}
            onProfileAction={onProfileAction}
            onViewLiveAccess={(profile) => {
              onGuidedProfileChange(profile.id);
              onTabChange("live_access");
              focusWorkspaceTab("live_access");
            }}
            pendingDeleteProfileId={pendingDeleteProfileId}
            pendingActionId={pendingProfileActionId}
            pendingActionType={pendingProfileActionType}
            profiles={connectorProfiles}
          />
          {!profileEditor && profileMutationError ? <InlineMessage tone="error">{errorMessage(profileMutationError, "Unable to manage database connection.")}</InlineMessage> : null}
        </section>
      ) : null}

      {activeTab === "schema_reviews" ? (
        <div id="connector-workspace-panel-schema_reviews" role="tabpanel" aria-labelledby="connector-workspace-tab-schema_reviews">
          <ConnectorCatalogReadiness
            catalogsByProfile={catalogsByProfile}
            connectorProfiles={connectorProfiles}
            isError={catalogsError}
            isLoading={catalogsLoading}
            onOpenCatalog={onOpenCatalog}
            onProfileAction={onProfileAction}
            pendingActionId={pendingProfileActionId}
            pendingActionType={pendingProfileActionType}
          />
        </div>
      ) : null}

      {activeTab === "live_access" ? (
        <div id="connector-workspace-panel-live_access" role="tabpanel" aria-labelledby="connector-workspace-tab-live_access">
          <ConnectorLiveAccessPanel
            catalogsByProfile={catalogsByProfile}
            connectorProfiles={connectorProfiles}
            isError={catalogsError}
            isLoading={catalogsLoading}
            onOpenCatalog={onOpenCatalog}
          />
        </div>
      ) : null}

      {activeTab === "diagnostics" ? (
        <div id="connector-workspace-panel-diagnostics" role="tabpanel" aria-labelledby="connector-workspace-tab-diagnostics">
          <ConnectorDiagnosticsPanel
            catalogsByProfile={catalogsByProfile}
            connectorProfiles={connectorProfiles}
            isError={isProfilesError || catalogsError}
            isLoading={isProfilesLoading || catalogsLoading}
            onProfileAction={onProfileAction}
            pendingActionId={pendingProfileActionId}
            pendingActionType={pendingProfileActionType}
          />
        </div>
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

function ConnectorGuidedStage({ catalog, onEditProfile, onExit, onOpenCatalog, onProfileAction, onViewLiveAccess, pendingActionId, pendingActionType, profile, step }: ConnectorGuidedStageProps) {
  const actionPending = pendingActionId === profile.id;
  const title = step === 0 ? "Confirm connection details"
    : step === 1 ? "Verify the connection"
      : step === 2 ? "Read the database schema"
        : step === 3 ? "Review schema access"
          : "Live DB access is ready";
  const detail = step === 0 ? `${connectorTypeLabel(profile.connector_type)} at ${profileEndpointSummary(profile)}`
    : step === 1 ? profileTestDetail(profile)
      : step === 2 ? "Read-only metadata discovery prepares tables, columns, and relationships for review."
        : step === 3 ? "Review AI-assisted descriptions and explicitly choose what Live DB may query."
          : "This approved connection is available to authorized Live DB answers.";
  const actionLabel = actionPending && step === 1 && pendingActionType === "test" ? "Testing"
    : actionPending && step === 2 && pendingActionType === "introspect" ? "Reading schema"
      : step === 0 ? "Edit Connection"
        : step === 1 ? "Test Connection"
          : step === 2 ? "Read Schema"
            : step === 3 ? "Review Access"
              : "View Live Access";

  function runAction() {
    if (step === 0) return onEditProfile(profile);
    if (step === 1) return onProfileAction("test", profile.id);
    if (step === 2) return onProfileAction("introspect", profile.id);
    if (step === 3 && catalog) return onOpenCatalog(profile, catalog);
    if (step === 4) onViewLiveAccess();
  }

  return (
    <section className="rounded-lg border border-primary/40 bg-surface-container-low p-4" aria-labelledby="connector-guided-stage-title" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="sv-label">Guided setup · Step {step + 1} of {connectorFlowSteps.length}</p>
          <h3 id="connector-guided-stage-title" className="mt-1 text-body-lg font-extrabold text-on-surface">{title}</h3>
          <p className="mt-1 text-body-md text-on-surface-variant">{detail}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={onExit} className="sv-action-secondary">All Connections</button>
          <button
            type="button"
            id={`connector-guide-action-${profile.id}`}
            className="sv-action-primary"
            disabled={actionPending || (step === 3 && !catalog)}
            onClick={runAction}
          >
            {actionPending && (step === 1 || step === 2) ? <Loader2 className="animate-spin" size={16} />
              : step === 0 ? <Pencil size={16} />
                : step === 2 ? <Search size={16} />
                  : step === 4 ? <Database size={16} />
                    : <CheckCircle2 size={16} />}
            {actionLabel}
          </button>
        </div>
      </div>
    </section>
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
          {progress.currentTable ? `Generating metadata for ${progress.currentTable}.` : "Saving the latest table metadata."}
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
  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, current: ConnectorWorkspaceTab) {
    const currentIndex = connectorWorkspaceTabs.findIndex((tab) => tab.id === current);
    const nextIndex = event.key === "ArrowRight"
      ? (currentIndex + 1) % connectorWorkspaceTabs.length
      : event.key === "ArrowLeft"
        ? (currentIndex - 1 + connectorWorkspaceTabs.length) % connectorWorkspaceTabs.length
        : event.key === "Home"
          ? 0
          : event.key === "End"
            ? connectorWorkspaceTabs.length - 1
            : -1;
    if (nextIndex < 0) return;
    event.preventDefault();
    const next = connectorWorkspaceTabs[nextIndex]?.id;
    if (!next) return;
    onChange(next);
    focusWorkspaceTab(next);
  }

  return (
    <div className="knowledge-inspector-tabs" role="tablist" aria-label="Database connector sections">
      {connectorWorkspaceTabs.map((tab) => (
        <button
          key={tab.id}
          id={`connector-workspace-tab-${tab.id}`}
          type="button"
          role="tab"
          aria-controls={`connector-workspace-panel-${tab.id}`}
          aria-selected={value === tab.id}
          tabIndex={value === tab.id ? 0 : -1}
          className={value === tab.id ? "knowledge-inspector-tab-active" : "knowledge-inspector-tab"}
          onClick={() => onChange(tab.id)}
          onKeyDown={(event) => handleKeyDown(event, tab.id)}
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
  enrichmentProgress: AiDraftProgress | null;
  guidedProfileId: string | null;
  isProfilesError: boolean;
  isProfilesLoading: boolean;
  onCatalogEditorClose: () => void;
  onCatalogSave: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog, request: UpdateConnectorSchemaCatalogRequest) => void;
  onContinueAiDraft: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog) => void;
  onDeleteProfile: (profile: ConnectorProfile) => void;
  onEditProfile: (profile: ConnectorProfile) => void;
  onGuidedProfileChange: (profileId: string | null) => void;
  onOpenCatalog: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog) => void;
  onProfileEditCancel: () => void;
  onProfileEditChange: (patch: Partial<ConnectorProfileDraft>) => void;
  onProfileEditSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onProfileAction: (action: "test" | "introspect", id: string) => void;
  onStartSetup: () => void;
  onTabChange: (tab: ConnectorWorkspaceTab) => void;
  pendingDeleteProfileId: string | null;
  pendingProfileActionId: string | null;
  pendingProfileActionType: "test" | "introspect" | null;
  profileEditError: string | null;
  profileEditor: ConnectorProfileEditorState | null;
  profileMutationError: unknown;
  profileSaving: boolean;
  writableSpacePaths: string[];
};

type ConnectorGuidedStageProps = {
  catalog: ConnectorSchemaCatalog | null;
  onEditProfile: (profile: ConnectorProfile) => void;
  onExit: () => void;
  onOpenCatalog: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog) => void;
  onProfileAction: (action: "test" | "introspect", id: string) => void;
  onViewLiveAccess: () => void;
  pendingActionId: string | null;
  pendingActionType: "test" | "introspect" | null;
  profile: ConnectorProfile;
  step: 0 | ConnectorFlowStep;
};

function focusWorkspaceTab(tab: ConnectorWorkspaceTab) {
  window.requestAnimationFrame(() => document.getElementById(`connector-workspace-tab-${tab}`)?.focus());
}

function connectorTabForFlowStep(step: 0 | ConnectorFlowStep): ConnectorWorkspaceTab {
  if (step === 3) return "schema_reviews";
  if (step === 4) return "live_access";
  return "connections";
}

function focusGuidedAction(profileId: string) {
  window.requestAnimationFrame(() => document.getElementById(`connector-guide-action-${profileId}`)?.focus());
}

function focusConnectorRowAction(profileId: string) {
  window.requestAnimationFrame(() => document.getElementById(`connector-primary-action-${profileId}`)?.focus());
}

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
