import { useEffect, useId, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CalendarClock, CheckCircle2, ChevronDown, ChevronRight, Eye, EyeOff, FileText, FolderOpen, KeyRound, Loader2, MoreHorizontal, Network, PauseCircle, Pencil, PlayCircle, Plus, Save, Search, ShieldAlert, Sparkles, Trash2, X } from "lucide-react";

import { connectorApi, folderIngestApi, type UpdateConnectorProfileRequest, type UpdateConnectorSchemaCatalogRequest } from "@/lib/api/contracts";
import { clearanceLevelDescription, clearanceLevelLabel, clearanceLevelsAssignableBy } from "@/lib/auth/authz";
import { useToast } from "@/components/feedback/ToastProvider";
import { InlineMessage } from "@/components/layout/Common";
import { Modal } from "@/components/layout/Modal";
import {
  buildLocalFolderScheduleRequest,
  buildSnapshotScheduleRequest,
  defaultFolderScheduleDraftForVariant,
  formatFolderCount,
  folderSnapshotLabel,
  identityFieldsFromDraft,
  isScheduleVisibleForPanelVariant,
  summarizeFolderFiles,
  WORKSPACE_TIMEZONE,
  type FolderFileEntry,
  type FolderIngestPanelVariant,
  type FolderScheduleDraft,
} from "@/features/ingestion/state/folderIngest";
import { formatFileSize } from "@/features/upload/state/pdfUploadBatch";
import type { ClearanceLevel, ConnectorProfile, ConnectorSchemaCatalog, ConnectorSchemaCatalogStatus, ConnectorSchemaSnapshot, ConnectorTestResponse, ConnectorType, FolderRun, FolderSchedule, FolderScheduleStatus, User as AuthUser } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";


const folderInputAttributes = { webkitdirectory: "", directory: "" };

const connectorWorkspaceTabs: Array<{ id: ConnectorWorkspaceTab; label: string }> = [
  { id: "connections", label: "Connections" },
  { id: "schema_reviews", label: "Schema Reviews" },
  { id: "live_access", label: "Live Access" },
  { id: "diagnostics", label: "Diagnostics" },
];

const connectorReviewTabs: Array<{ id: ConnectorReviewTab; label: string }> = [
  { id: "summary", label: "Summary" },
  { id: "tables", label: "Tables & Columns" },
  { id: "joins", label: "Joins" },
  { id: "access", label: "Access" },
  { id: "raw_schema", label: "Raw Schema" },
];

export function FolderIngestPanel({ currentUser, groupsLoading, variant = "folder_sources", writableSpacePaths }: Props) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const isConnectorPanel = variant === "database_connectors";
  const [draft, setDraft] = useState<FolderScheduleDraft>(() => defaultFolderScheduleDraftForVariant("", variant));
  const [profileDraft, setProfileDraft] = useState<ConnectorProfileDraft>(() => defaultProfileDraft());
  const [connectorSetupOpen, setConnectorSetupOpen] = useState(false);
  const [connectorWorkspaceTab, setConnectorWorkspaceTab] = useState<ConnectorWorkspaceTab>("connections");
  const [profileEditor, setProfileEditor] = useState<ConnectorProfileEditorState | null>(null);
  const [catalogEditor, setCatalogEditor] = useState<ConnectorCatalogEditorState | null>(null);
  const [schemaViewer, setSchemaViewer] = useState<ConnectorSchemaSnapshotViewerState | null>(null);
  const [deleteProfileConfirm, setDeleteProfileConfirm] = useState<ConnectorProfile | null>(null);
  const [pendingAiDraftProfileId, setPendingAiDraftProfileId] = useState<string | null>(null);
  const [aiDraftProgress, setAiDraftProgress] = useState<AiDraftProgress | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [folderInputResetKey, setFolderInputResetKey] = useState(0);
  const [formError, setFormError] = useState<string | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileEditError, setProfileEditError] = useState<string | null>(null);
  const selection = useMemo(() => summarizeFolderFiles(selectedFiles), [selectedFiles]);
  const clearanceOptions = useMemo(() => clearanceLevelsAssignableBy(currentUser), [currentUser]);

  const schedulesQuery = useQuery({
    queryKey: ["folder-ingest", "schedules"],
    queryFn: folderIngestApi.listSchedules,
    enabled: !isConnectorPanel,
    retry: false,
  });
  const profilesQuery = useQuery({
    queryKey: ["connectors", "profiles"],
    queryFn: connectorApi.listProfiles,
    enabled: isConnectorPanel,
    retry: false,
  });
  const createMutation = useMutation({
    mutationFn: () => {
      if (draft.sourceMode === "snapshot") {
        return folderIngestApi.createSnapshot(buildSnapshotScheduleRequest(draft, selection.entries));
      }
      if (draft.sourceMode === "connector") {
        throw new Error("Database connector sync schedules are retired. Use approved database access reviews for live read-only SQL.");
      }
      return folderIngestApi.createLocalFolder(buildLocalFolderScheduleRequest(draft));
    },
    onSuccess: () => {
      setSelectedFiles([]);
      setFolderInputResetKey((key) => key + 1);
      setFormError(null);
      setDraft((current) => ({ ...current, name: "", folderPath: "", connectorQuery: "", connectorIdentityFields: "" }));
      if (isConnectorPanel) {
        setConnectorSetupOpen(false);
      }
      void queryClient.invalidateQueries({ queryKey: ["folder-ingest", "schedules"] });
    },
  });
  const createProfileMutation = useMutation({
    mutationFn: () => connectorApi.createProfile({
      name: profileDraft.name.trim(),
      connector_type: profileDraft.connectorType,
      public_config: profilePublicConfig(profileDraft),
      secrets: {
        username: profileDraft.username.trim(),
        password: profileDraft.password,
      },
    }),
    onSuccess: (profile) => {
      setProfileDraft(defaultProfileDraft());
      setProfileError(null);
      setDraft((current) => ({ ...current, sourceMode: "connector", connectorProfileId: profile.id }));
      setConnectorSetupOpen(false);
      setConnectorWorkspaceTab("connections");
      void queryClient.invalidateQueries({ queryKey: ["connectors", "profiles"] });
    },
  });
  const updateProfileMutation = useMutation<ConnectorProfile, Error, { profile: ConnectorProfile; draft: ConnectorProfileDraft }>({
    mutationFn: ({ profile, draft }) => connectorApi.updateProfile(profile.id, profileUpdateRequest(draft)),
    onSuccess: (profile) => {
      setProfileEditor(null);
      setProfileEditError(null);
      void queryClient.invalidateQueries({ queryKey: ["connectors", "profiles"] });
      void queryClient.invalidateQueries({ queryKey: ["connectors", "profiles", profile.id, "schema-catalogs"] });
    },
  });
  const deleteProfileMutation = useMutation<void, Error, { profile: ConnectorProfile }>({
    mutationFn: ({ profile }) => connectorApi.deleteProfile(profile.id),
    onSuccess: (_result, variables) => {
      setProfileEditor((current) => current?.profile.id === variables.profile.id ? null : current);
      setCatalogEditor((current) => current?.profile.id === variables.profile.id ? null : current);
      void queryClient.invalidateQueries({ queryKey: ["connectors", "profiles"] });
    },
  });
  const profileActionMutation = useMutation<ConnectorTestResponse | ConnectorSchemaSnapshot, Error, { action: "test" | "introspect"; id: string }>({
    mutationFn: ({ action, id }: { action: "test" | "introspect"; id: string }) => {
      if (action === "test") return connectorApi.testProfile(id);
      return connectorApi.introspectProfile(id);
    },
    onSuccess: (result, variables) => {
      if (variables.action === "test" && "message" in result) {
        notify({
          title: result.status === "ok" ? "Connection test passed" : "Connection test failed",
          description: result.message,
          tone: result.status === "ok" ? "success" : "error",
        });
      }
      if (variables.action === "introspect" && "schema_json" in result) {
        const profile = connectorProfiles.find((item) => item.id === variables.id) ?? null;
        setSchemaViewer({ profile, snapshot: result });
        setConnectorWorkspaceTab("diagnostics");
        notify({
          title: result.status === "ok" ? "Schema snapshot ready" : "Schema introspection failed",
          description: result.status === "ok"
            ? `${schemaSnapshotSummary(result.schema_json)} Review window opened.`
            : result.error_message ?? `${connectorTypeLabel(result.connector_type)} schema introspection failed.`,
          tone: result.status === "ok" ? "success" : "error",
        });
      }
      void queryClient.invalidateQueries({ queryKey: ["connectors", "profiles"] });
    },
    onError: (error, variables) => {
      notify({
        title: variables.action === "test" ? "Connection test failed" : "Schema introspection failed",
        description: errorMessage(error, "The connector action could not complete."),
        tone: "error",
      });
    },
  });
  const enrichAiCatalogMutation = useMutation<ConnectorSchemaCatalog, Error, { profile: ConnectorProfile; catalog: ConnectorSchemaCatalog }>({
    mutationFn: async ({ profile, catalog }) => {
      let current = catalog;
      const tableKeys = schemaCatalogPendingTableKeys(catalog.catalog_json);
      setAiDraftProgress(aiDraftProgressFromCatalog(catalog, tableKeys[0] ?? null));
      for (const tableKey of tableKeys) {
        setAiDraftProgress(aiDraftProgressFromCatalog(current, tableKey));
        current = await connectorApi.enrichSchemaCatalogTable(profile.id, current.id, { table_key: tableKey });
        setCatalogEditor((editor) => editor?.catalog.id === current.id ? { profile, catalog: current } : editor);
        setAiDraftProgress(aiDraftProgressFromCatalog(current, null));
      }
      return current;
    },
    onSuccess: (catalog, variables) => {
      const enrichmentStatus = schemaCatalogAiEnrichmentStatus(catalog.catalog_json);
      notify({
        title: enrichmentStatus === "generated" ? "Database access review ready" : "Review descriptions need attention",
        description: enrichmentStatus === "generated"
          ? "Every table was processed. Review and enable Live DB access."
          : schemaCatalogAiEnrichmentError(catalog.catalog_json) || "Some tables could not be enriched. You can retry them from the review window.",
        tone: enrichmentStatus === "generated" ? "success" : "warning",
      });
      void queryClient.invalidateQueries({ queryKey: ["connectors", "profiles", variables.profile.id, "schema-catalogs"] });
    },
    onError: (error, variables) => {
      notify({
        title: "AI description enrichment paused",
        description: `${errorMessage(error, "The next table could not be processed.")} Completed tables were saved and can be resumed.`,
        tone: "warning",
      });
      void queryClient.invalidateQueries({ queryKey: ["connectors", "profiles", variables.profile.id, "schema-catalogs"] });
    },
    onSettled: () => {
      setAiDraftProgress(null);
      setPendingAiDraftProfileId(null);
    },
  });
  const createAiCatalogMutation = useMutation<ConnectorSchemaCatalog, Error, { profile: ConnectorProfile; groupPath: string; clearanceLevel: ClearanceLevel }>({
    mutationFn: ({ profile, groupPath, clearanceLevel }) =>
      connectorApi.createAiSchemaCatalogDraft(profile.id, {
        group_path: groupPath,
        group_paths: [groupPath],
        clearance_level: clearanceLevel,
    }),
    onSuccess: (catalog, variables) => {
      setCatalogEditor({ profile: variables.profile, catalog });
      setConnectorWorkspaceTab("schema_reviews");
      notify({
        title: "Database access review created",
        description: "The review window is open. AI can fill descriptions one table at a time, and you can edit everything before approval.",
        tone: "info",
      });
      void queryClient.invalidateQueries({ queryKey: ["connectors", "profiles", variables.profile.id, "schema-catalogs"] });
      enrichAiCatalogMutation.mutate({ profile: variables.profile, catalog });
    },
    onError: (error) => {
      setPendingAiDraftProfileId(null);
      notify({
        title: "Database access review failed",
        description: errorMessage(error, "Unable to prepare a database access review."),
        tone: "error",
      });
    },
  });
  const updateCatalogMutation = useMutation<ConnectorSchemaCatalog, Error, { profile: ConnectorProfile; catalog: ConnectorSchemaCatalog; request: UpdateConnectorSchemaCatalogRequest }>({
    mutationFn: ({ profile, catalog, request }) => connectorApi.updateSchemaCatalog(profile.id, catalog.id, request),
    onSuccess: (catalog, variables) => {
      setCatalogEditor({ profile: variables.profile, catalog });
      notify({
        title: "Database access review saved",
        description: catalog.status === "approved" ? "This database access review is now available for Live DB answers." : "Your review changes were saved.",
        tone: "success",
      });
      void queryClient.invalidateQueries({ queryKey: ["connectors", "profiles", variables.profile.id, "schema-catalogs"] });
    },
  });
  const actionMutation = useMutation({
    mutationFn: ({ action, id }: { action: "pause" | "resume" | "cancel"; id: string }) => {
      if (action === "pause") return folderIngestApi.pauseSchedule(id);
      if (action === "resume") return folderIngestApi.resumeSchedule(id);
      return folderIngestApi.cancelSchedule(id);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["folder-ingest", "schedules"] });
    },
  });

  function patchDraft(patch: Partial<FolderScheduleDraft>) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  function handleFolderSnapshotSelection(files: FileList | null) {
    setSelectedFiles(Array.from(files ?? []));
    setFormError(null);
  }

  function clearFolderSnapshot() {
    setSelectedFiles([]);
    setFolderInputResetKey((key) => key + 1);
  }

  function removeFolderSnapshotFile(file: File) {
    setSelectedFiles((current) => current.filter((item) => item !== file));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validation = validateDraft(draft, selection, writableSpacePaths);
    if (validation) {
      setFormError(validation);
      return;
    }
    setFormError(null);
    createMutation.mutate();
  }

  function handleProfileSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validation = validateProfileDraft(profileDraft, { credentialsRequired: true });
    if (validation) {
      setProfileError(validation);
      return;
    }
    setProfileError(null);
    createProfileMutation.mutate();
  }

  function handleProfileEditSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profileEditor) return;
    const validation = validateProfileDraft(profileEditor.draft, { credentialsRequired: false });
    if (validation) {
      setProfileEditError(validation);
      return;
    }
    setProfileEditError(null);
    updateProfileMutation.mutate(profileEditor);
  }

  function openProfileEditor(profile: ConnectorProfile) {
    setProfileEditError(null);
    setProfileEditor({ profile, draft: profileDraftFromProfile(profile) });
  }

  function handleDeleteProfile(profile: ConnectorProfile) {
    setDeleteProfileConfirm(profile);
  }

  function confirmDeleteProfile() {
    if (!deleteProfileConfirm) return;
    deleteProfileMutation.mutate({ profile: deleteProfileConfirm });
    setDeleteProfileConfirm(null);
  }

  const isSubmitting = createMutation.isPending;
  const visibleSchedules = (schedulesQuery.data?.items ?? []).filter((schedule) => isScheduleVisibleForPanelVariant(schedule.source_type, variant));
  const connectorProfiles = profilesQuery.data?.items ?? [];
  const catalogQueries = useQueries({
    queries: connectorProfiles.map((profile) => ({
      queryKey: ["connectors", "profiles", profile.id, "schema-catalogs"],
      queryFn: () => connectorApi.listSchemaCatalogs(profile.id),
      enabled: isConnectorPanel,
      retry: false,
    })),
  });
  const catalogsByProfile = useMemo(() => {
    const byProfile: Record<string, ConnectorSchemaCatalog[]> = {};
    connectorProfiles.forEach((profile, index) => {
      const current = latestConnectorCatalog(catalogQueries[index]?.data?.items ?? []);
      byProfile[profile.id] = current ? [current] : [];
    });
    return byProfile;
  }, [catalogQueries, connectorProfiles]);
  const catalogsLoading = catalogQueries.some((query) => query.isLoading);
  const catalogsError = catalogQueries.some((query) => query.isError);
  const submitLabel = "Create folder ingestion schedule";
  const submittingLabel = "Creating folder schedule";
  const scheduleListTitle = "Folder schedules";
  const scheduleLoadError = "Unable to load folder schedules.";
  const createError = "Unable to create folder ingestion schedule.";

  function openConnectorSetup() {
    setFormError(null);
    setProfileError(null);
    setConnectorSetupOpen(true);
  }

  function closeConnectorSetup() {
    setFormError(null);
    setProfileError(null);
    setConnectorSetupOpen(false);
  }

  function handleCreateAiDraft(profile: ConnectorProfile) {
    const groupPath = writableSpacePaths[0];
    if (!groupPath) {
      setFormError("Create a writable Knowledge Space before preparing a database access review.");
      return;
    }
    setPendingAiDraftProfileId(profile.id);
    notify({
      title: "Preparing database access review",
      description: "The review window will open first, then table descriptions can be filled and saved separately.",
      tone: "info",
    });
    createAiCatalogMutation.mutate({
      profile,
      groupPath,
      clearanceLevel: clearanceOptions.includes(currentUser.clearance_level) ? currentUser.clearance_level : clearanceOptions[0] ?? "NATO_RESTRICTED",
    });
  }

  function handleContinueAiDraft(profile: ConnectorProfile, catalog: ConnectorSchemaCatalog) {
    if (enrichAiCatalogMutation.isPending) return;
    setPendingAiDraftProfileId(profile.id);
    enrichAiCatalogMutation.mutate({ profile, catalog });
  }

  return (
    <section className={isConnectorPanel ? "sv-panel connector-page-panel p-5" : "sv-panel p-5"} aria-labelledby={isConnectorPanel ? "database-connectors-workspace-title" : "folder-ingest-title"}>
      {!isConnectorPanel ? (
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4 border-b border-surface-border pb-4">
        <div>
          <p className="sv-eyebrow">Scheduled Folder Sources</p>
          <h2 id="folder-ingest-title" className="sv-section-title">Stage local folder snapshots for indexing</h2>
          <p className="mt-1 text-body-md text-on-surface-variant">
            Choose a folder from this browser, review the staged files, then queue a one-time snapshot for parsing, embedding, and indexing.
          </p>
        </div>
        <span className="sv-pill">Timezone: {WORKSPACE_TIMEZONE}</span>
      </div>
      ) : null}

      {isConnectorPanel ? (
        <ConnectorOverview
          activeTab={connectorWorkspaceTab}
          catalogsByProfile={catalogsByProfile}
          catalogsError={catalogsError}
          catalogsLoading={catalogsLoading}
          catalogEditor={catalogEditor}
          catalogSaveError={updateCatalogMutation.error}
          catalogSaving={updateCatalogMutation.isPending}
          clearanceOptions={clearanceOptions}
          connectorProfiles={connectorProfiles}
          draftCreationError={createAiCatalogMutation.error}
          enrichmentProgress={aiDraftProgress}
          isProfilesError={profilesQuery.isError}
          isProfilesLoading={profilesQuery.isLoading}
          onCatalogEditorClose={() => setCatalogEditor(null)}
          onCatalogSave={(profile, catalog, request) => updateCatalogMutation.mutate({ profile, catalog, request })}
          onContinueAiDraft={handleContinueAiDraft}
          onCreateAiDraft={handleCreateAiDraft}
          onDeleteProfile={handleDeleteProfile}
          onEditProfile={openProfileEditor}
          onOpenCatalog={(profile, catalog) => setCatalogEditor({ profile, catalog })}
          onProfileEditCancel={() => {
            setProfileEditor(null);
            setProfileEditError(null);
          }}
          onProfileEditChange={(patch) => setProfileEditor((current) => current ? { ...current, draft: { ...current.draft, ...patch } } : current)}
          onProfileEditSubmit={handleProfileEditSubmit}
          onProfileAction={(action, id) => profileActionMutation.mutate({ action, id })}
          onStartSetup={openConnectorSetup}
          onTabChange={setConnectorWorkspaceTab}
          pendingAiDraftProfileId={pendingAiDraftProfileId}
          pendingDeleteProfileId={deleteProfileMutation.isPending ? deleteProfileMutation.variables?.profile.id ?? null : null}
          pendingProfileActionId={profileActionMutation.isPending ? profileActionMutation.variables?.id ?? null : null}
          pendingProfileActionType={profileActionMutation.isPending ? profileActionMutation.variables?.action ?? null : null}
          profileEditError={profileEditError}
          profileEditor={profileEditor}
          profileMutationError={updateProfileMutation.error ?? deleteProfileMutation.error}
          profileSaving={updateProfileMutation.isPending}
          writableSpacePaths={writableSpacePaths}
        />
      ) : (
        <>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="rounded-lg border border-surface-border bg-surface-container-low p-4">
              <label className="sv-field">
                <span className="sv-label">Folder Snapshot</span>
                <input
                  key={folderInputResetKey}
                  type="file"
                  multiple
                  {...folderInputAttributes}
                  onChange={(event) => handleFolderSnapshotSelection(event.currentTarget.files)}
                  className="sv-input file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-label-md file:font-bold file:text-on-primary"
                />
                <small className="text-secondary">Choose a local folder to upload a point-in-time copy. Future edits require a new snapshot.</small>
              </label>
              {selectedFiles.length > 0 ? (
                <FolderSnapshotReview
                  label={folderSnapshotLabel(selection.entries)}
                  onClear={clearFolderSnapshot}
                  onRemove={removeFolderSnapshotFile}
                  selection={selection}
                />
              ) : (
                <p className="mt-3 rounded-md border border-dashed border-surface-border bg-surface px-3 py-2 text-body-sm text-secondary">No folder selected.</p>
              )}
            </div>

            <div className="grid items-start gap-4 md:grid-cols-2">
              <label className="sv-field">
                <span className="sv-label">Schedule Name</span>
                <input value={draft.name} onChange={(event) => patchDraft({ name: event.target.value })} placeholder="Finance policies off-peak sync" className="sv-input" />
                <small className="text-secondary">Used to identify this ingestion schedule in activity history.</small>
              </label>
              <SelectField label="Knowledge Space" value={draft.groupPath} onChange={(value) => patchDraft({ groupPath: value })} options={["", ...writableSpacePaths]} emptyLabel={groupsLoading ? "Loading spaces" : "Select ingestion space"} helper="Files inherit this space for retrieval filtering." />
              <ClearanceSelect value={draft.clearanceLevel} onChange={(clearanceLevel) => patchDraft({ clearanceLevel })} options={clearanceOptions} />
              <label className="sv-field">
                <span className="sv-label">Effective Date <span className="font-normal text-secondary">(optional)</span></span>
                <input type="date" value={draft.effectiveDate} onChange={(event) => patchDraft({ effectiveDate: event.target.value })} className="sv-input" />
                <small className="text-secondary">Optional start date applied to ingested files.</small>
              </label>
              <label className="sv-field">
                <span className="sv-label">Expiry Date</span>
                <input type="date" value={draft.expiryDate} onChange={(event) => patchDraft({ expiryDate: event.target.value })} className="sv-input" />
                <small className="text-secondary">Leave blank unless these files should expire from current use.</small>
              </label>
            </div>

        <label className="sv-field">
          <span className="sv-label">Start Time ({WORKSPACE_TIMEZONE})</span>
          <input type="datetime-local" value={draft.scheduledAt} onChange={(event) => patchDraft({ scheduledAt: event.target.value })} className="sv-input" />
          <small className="text-secondary">Queue this snapshot at the selected local time.</small>
        </label>

        <label className="sv-field">
          <span className="sv-label">Description</span>
          <textarea value={draft.description} onChange={(event) => patchDraft({ description: event.target.value })} placeholder={isConnectorPanel ? "Optional context for synced database records" : "Optional shared context for staged folder files"} className="sv-input min-h-20" />
            <small className="text-secondary">{isConnectorPanel ? "Shared context attached to every synced connector record." : "Shared context attached to every staged folder file."}</small>
          </label>

        {formError ? <InlineMessage tone="warning">{formError}</InlineMessage> : null}
        {createMutation.isError ? <InlineMessage tone="error">{errorMessage(createMutation.error, createError)}</InlineMessage> : null}
        <button type="submit" disabled={isSubmitting || writableSpacePaths.length === 0} className="sv-action-primary w-full">
          {isSubmitting ? <Loader2 className="animate-spin" size={18} /> : <CalendarClock size={18} />}
          {isSubmitting ? submittingLabel : submitLabel}
        </button>
          </form>

          <ScheduleListPanel
            emptyMessage="No folder source schedules yet. Create one above to defer ingestion into an off-peak window."
            isError={schedulesQuery.isError}
            isLoading={schedulesQuery.isLoading}
            loadError={scheduleLoadError}
            pendingActionId={actionMutation.variables?.id ?? null}
            pendingActionPending={actionMutation.isPending}
            schedules={visibleSchedules}
            title={scheduleListTitle}
            onAction={(action, id) => actionMutation.mutate({ action, id })}
          />
        </>
      )}

      {isConnectorPanel ? (
        <>
          <SchemaSnapshotModal
            onClose={() => setSchemaViewer(null)}
            viewer={schemaViewer}
          />
          <Modal
            description="Save encrypted read-only credentials, then read the schema and review what Live DB may use."
            icon={<KeyRound size={18} />}
            onClose={closeConnectorSetup}
            open={connectorSetupOpen}
            size="md"
            title="Add Connection"
          >
            <ConnectorProfileSetup
              connectorProfiles={connectorProfiles}
              onClose={closeConnectorSetup}
              onProfileAction={(action, id) => profileActionMutation.mutate({ action, id })}
              onProfileChange={(patch) => setProfileDraft((current) => ({ ...current, ...patch }))}
              onProfileSubmit={handleProfileSubmit}
              pendingProfileActionId={profileActionMutation.isPending ? profileActionMutation.variables?.id ?? null : null}
              pendingProfileActionType={profileActionMutation.isPending ? profileActionMutation.variables?.action ?? null : null}
              profileDraft={profileDraft}
              profileError={profileError}
              profileMutationError={createProfileMutation.error}
              profilesCreating={createProfileMutation.isPending}
              profilesLoading={profilesQuery.isLoading}
            />
          </Modal>
          <Modal
            description="This removes the connection and its database access review. Uploaded documents are not deleted."
            icon={<Trash2 size={18} />}
            onClose={() => setDeleteProfileConfirm(null)}
            open={Boolean(deleteProfileConfirm)}
            size="sm"
            title="Delete Connection"
          >
            {deleteProfileConfirm ? (
              <section className="space-y-4">
                <InlineMessage tone="warning">
                  Delete {deleteProfileConfirm.name}? Live DB will no longer use reviews from this connection.
                </InlineMessage>
                <div className="flex flex-wrap justify-end gap-2">
                  <button type="button" onClick={() => setDeleteProfileConfirm(null)} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-label-md font-bold text-on-surface hover:border-primary">
                    Cancel
                  </button>
                  <button type="button" disabled={deleteProfileMutation.isPending} onClick={confirmDeleteProfile} className="rounded-md border border-error-red/30 bg-error-container px-3 py-2 text-label-md font-bold text-error-red hover:border-error-red disabled:opacity-50">
                    {deleteProfileMutation.isPending ? "Deleting" : "Delete Connection"}
                  </button>
                </div>
              </section>
            ) : null}
          </Modal>
        </>
      ) : null}
    </section>
  );
}

function ConnectorProfileSetup({
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

function ConnectorOverview({
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

function ConnectorReviewTabs({ onChange, value }: ConnectorReviewTabsProps) {
  return (
    <div className="knowledge-inspector-tabs" role="tablist" aria-label="Database access review sections" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(7rem, 1fr))" }}>
      {connectorReviewTabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={value === tab.id}
          className={value === tab.id ? "knowledge-inspector-tab-active" : "knowledge-inspector-tab"}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function ConnectorLiveAccessPanel({ catalogsByProfile, connectorProfiles, isError, isLoading, onOpenCatalog }: ConnectorLiveAccessPanelProps) {
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
        <div className="sv-table-wrap">
          <table className="sv-table">
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
                  <td>
                    <strong className="block text-on-surface">{profile.name}</strong>
                    <small className="text-secondary">{connectorTypeLabel(profile.connector_type)}</small>
                  </td>
                  <td>{connectorSchemaAccessSummary(catalog)}</td>
                  <td>{catalogScopeSummary(catalog)}</td>
                  <td>{clearanceLevelLabel(catalog.clearance_level as ClearanceLevel)}</td>
                  <td>
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

function ConnectorDiagnosticsPanel({ catalogsByProfile, connectorProfiles, isError, isLoading, onProfileAction, pendingActionId, pendingActionType }: ConnectorDiagnosticsPanelProps) {
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
        <div className="sv-table-wrap">
          <table className="sv-table">
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
                    <td>
                      <strong className="block text-on-surface">{profile.name}</strong>
                      <small className="text-secondary">{connectorTypeLabel(profile.connector_type)}</small>
                    </td>
                    <td>
                      <ConnectorStatusPill className={profileHealthPillClass(profile)} label={profileHealthLabel(profile)} />
                      <small className={profile.last_test_status === "failed" ? "mt-1 block text-error-red" : "mt-1 block text-secondary"}>{profileTestDetail(profile)}</small>
                    </td>
                    <td>{currentCatalog ? catalogName(currentCatalog, profile) : "No review prepared"}</td>
                    <td>{currentCatalog ? formatDateTime(currentCatalog.updated_at ?? currentCatalog.created_at) : "No schema review"}</td>
                    <td>
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


function ConnectorProfilePanel({
  draft,
  error,
  isCreating,
  isLoading,
  mutationError,
  onChange,
  onProfileAction,
  onSubmit,
  pendingActionId,
  pendingActionType,
  profiles,
  showExisting = true,
}: ConnectorProfilePanelProps) {
  const passwordInputId = useId();
  const [showPassword, setShowPassword] = useState(false);
  const passwordToggleLabel = showPassword ? "Hide password" : "Show password";

  return (
    <div className="mb-5 rounded-lg border border-surface-border bg-surface-container-low p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="sv-label">Database connection</p>
          <p className="mt-1 text-body-md text-on-surface-variant">SQL Server and PostgreSQL credentials are encrypted at rest and redacted after save.</p>
        </div>
        {showExisting ? <span className="sv-pill">{profiles.length} connection{profiles.length === 1 ? "" : "s"}</span> : null}
      </div>
      <form
        onSubmit={onSubmit}
        className={`connector-profile-form ${showExisting ? "connector-profile-form-overview" : "connector-profile-form-compact"}`}
      >
        <label className="sv-field">
          <span className="sv-label">Type <span className="font-normal text-secondary">(required)</span></span>
          <select
            value={draft.connectorType}
            onChange={(event) => onChange(defaultProfileDraftForType(event.target.value as ConnectorProfileDraft["connectorType"]))}
            className="sv-select"
          >
            <option value="sql_server">SQL Server</option>
            <option value="postgres">PostgreSQL</option>
          </select>
        </label>
        <label className="sv-field">
          <span className="sv-label">Connection Name <span className="font-normal text-secondary">(required)</span></span>
          <input value={draft.name} onChange={(event) => onChange({ name: event.target.value })} placeholder={draft.connectorType === "postgres" ? "Postgres case read replica" : "CaseDB read replica"} className="sv-input" />
        </label>
        <label className="sv-field">
          <span className="sv-label">{draft.connectorType === "postgres" ? "Host" : "Server"} <span className="font-normal text-secondary">(required)</span></span>
          <input value={draft.server} onChange={(event) => onChange({ server: event.target.value })} placeholder={draft.connectorType === "postgres" ? "postgres.internal" : "sql01.internal"} className="sv-input" />
        </label>
        <label className="sv-field">
          <span className="sv-label">Port</span>
          <input value={draft.port} onChange={(event) => onChange({ port: event.target.value })} placeholder={draft.connectorType === "postgres" ? "5432" : "1433"} className="sv-input" />
        </label>
        <label className="sv-field">
          <span className="sv-label">Database <span className="font-normal text-secondary">(required)</span></span>
          <input value={draft.database} onChange={(event) => onChange({ database: event.target.value })} placeholder="CaseDB" className="sv-input" />
        </label>
        <label className="sv-field">
          <span className="sv-label">User <span className="font-normal text-secondary">(required)</span></span>
          <input value={draft.username} onChange={(event) => onChange({ username: event.target.value })} placeholder="readonly_user" className="sv-input" />
        </label>
        <div className="sv-field">
          <label htmlFor={passwordInputId} className="sv-label">Password <span className="font-normal text-secondary">(required)</span></label>
          <div className="flex gap-2">
            <input id={passwordInputId} autoComplete="off" type={showPassword ? "text" : "password"} value={draft.password} onChange={(event) => onChange({ password: event.target.value })} className="sv-input min-w-0 flex-1" />
            <button type="button" onClick={() => setShowPassword((value) => !value)} className="sv-action-secondary min-h-11 shrink-0 px-3" aria-label={passwordToggleLabel} aria-pressed={showPassword} title={passwordToggleLabel}>
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>
        <button type="submit" disabled={isCreating} className="connector-profile-save sv-action-secondary">
          {isCreating ? <Loader2 className="animate-spin" size={16} /> : <KeyRound size={16} />}
          Save Connection
        </button>
        <details className="connector-profile-advanced rounded-md border border-surface-border bg-surface px-3 py-2">
          <summary className="cursor-pointer text-label-md font-bold text-on-surface">Advanced connection settings</summary>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {draft.connectorType === "sql_server" ? (
              <>
                <label className="sv-field">
                  <span className="sv-label">SQL Server Driver</span>
                  <select value={draft.driver} onChange={(event) => onChange({ driver: event.target.value })} className="sv-select">
                    <option value="ODBC Driver 18 for SQL Server">ODBC Driver 18 for SQL Server (recommended)</option>
                    <option value="ODBC Driver 17 for SQL Server">ODBC Driver 17 for SQL Server</option>
                    <option value="custom">Custom driver name</option>
                  </select>
                  <small className="text-secondary">The deployment image includes Driver 18 by default.</small>
                </label>
                {draft.driver === "custom" ? (
                  <label className="sv-field">
                    <span className="sv-label">Custom Driver Name</span>
                    <input value={draft.customDriver} onChange={(event) => onChange({ customDriver: event.target.value })} placeholder="ODBC Driver 18 for SQL Server" className="sv-input" />
                  </label>
                ) : null}
              </>
            ) : (
              <label className="sv-field">
                <span className="sv-label">Connection SSL</span>
                <select value={draft.sslMode} onChange={(event) => onChange({ sslMode: event.target.value })} className="sv-select">
                  <option value="prefer">Prefer SSL (default)</option>
                  <option value="require">Require SSL</option>
                  <option value="disable">Disable SSL</option>
                  <option value="verify-ca">Verify certificate authority</option>
                  <option value="verify-full">Verify certificate and host</option>
                </select>
              </label>
            )}
          </div>
        </details>
      </form>
      {error ? <InlineMessage tone="warning">{error}</InlineMessage> : null}
      {mutationError ? <InlineMessage tone="error">{errorMessage(mutationError, "Unable to save database connection.")}</InlineMessage> : null}
      {showExisting && isLoading ? <p className="mt-3 text-body-md text-secondary">Loading database connections.</p> : null}
      {showExisting && profiles.length > 0 ? (
        <div className="mt-3 grid gap-2">
          {profiles.slice(0, 4).map((profile) => (
            <div key={profile.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-surface-border bg-surface px-3 py-2">
              <span className="min-w-0">
                <strong className="block truncate text-body-md text-on-surface">{profile.name}</strong>
                <small className="text-secondary">{connectorTypeLabel(profile.connector_type)}</small>
                <small className={profile.last_test_status === "failed" ? "block text-error-red" : "block text-secondary"}>{profileTestDetail(profile)}</small>
              </span>
              <span className="flex gap-2">
                <button type="button" disabled={pendingActionId === profile.id} onClick={() => onProfileAction("test", profile.id)} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                  {pendingActionId === profile.id && pendingActionType === "test" ? "Testing" : "Test"}
                </button>
                <button type="button" disabled={pendingActionId === profile.id} onClick={() => onProfileAction("introspect", profile.id)} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                  {pendingActionId === profile.id && pendingActionType === "introspect" ? "Reading" : "Read Schema"}
                </button>
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ConnectorProfileEditor({ draft, error, isSaving, mutationError, onCancel, onChange, onSubmit, profile }: ConnectorProfileEditorProps) {
  const passwordInputId = useId();
  const [showPassword, setShowPassword] = useState(false);
  const passwordToggleLabel = showPassword ? "Hide replacement password" : "Show replacement password";

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="sv-label">Edit connection</p>
          <p className="mt-1 text-body-md text-on-surface-variant">
            Updating the connection affects future schema introspection and Live DB queries for this source.
          </p>
        </div>
        <span className="sv-pill">{connectorTypeLabel(profile.connector_type)}</span>
      </div>
      <div className="grid items-start gap-3 lg:grid-cols-2 xl:grid-cols-[0.8fr_1fr_1fr_0.7fr_1fr]">
        <label className="sv-field">
          <span className="sv-label">Type</span>
          <select
            value={draft.connectorType}
            onChange={(event) => onChange(defaultProfileDraftForType(event.target.value as ConnectorProfileDraft["connectorType"]))}
            className="sv-select"
          >
            <option value="sql_server">SQL Server</option>
            <option value="postgres">PostgreSQL</option>
          </select>
        </label>
        <label className="sv-field">
          <span className="sv-label">Connection Name</span>
          <input value={draft.name} onChange={(event) => onChange({ name: event.target.value })} className="sv-input" />
        </label>
        <label className="sv-field">
          <span className="sv-label">{draft.connectorType === "postgres" ? "Host" : "Server"}</span>
          <input value={draft.server} onChange={(event) => onChange({ server: event.target.value })} className="sv-input" />
        </label>
        <label className="sv-field">
          <span className="sv-label">Port</span>
          <input value={draft.port} onChange={(event) => onChange({ port: event.target.value })} className="sv-input" />
        </label>
        <label className="sv-field">
          <span className="sv-label">Database</span>
          <input value={draft.database} onChange={(event) => onChange({ database: event.target.value })} className="sv-input" />
        </label>
      </div>
      <details className="rounded-md border border-surface-border bg-surface-container-low px-3 py-2">
        <summary className="cursor-pointer text-label-md font-bold text-on-surface">Credentials and advanced settings</summary>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <label className="sv-field">
            <span className="sv-label">Replacement User</span>
            <input value={draft.username} onChange={(event) => onChange({ username: event.target.value })} placeholder="Leave blank to keep current user" className="sv-input" />
          </label>
          <div className="sv-field">
            <label htmlFor={passwordInputId} className="sv-label">Replacement Password</label>
            <div className="flex gap-2">
              <input id={passwordInputId} autoComplete="off" type={showPassword ? "text" : "password"} value={draft.password} onChange={(event) => onChange({ password: event.target.value })} placeholder="Leave blank to keep current password" className="sv-input min-w-0 flex-1" />
              <button type="button" onClick={() => setShowPassword((value) => !value)} className="sv-action-secondary min-h-11 shrink-0 px-3" aria-label={passwordToggleLabel} aria-pressed={showPassword} title={passwordToggleLabel}>
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
          {draft.connectorType === "sql_server" ? (
            <>
              <label className="sv-field">
                <span className="sv-label">SQL Server Driver</span>
                <select value={draft.driver} onChange={(event) => onChange({ driver: event.target.value })} className="sv-select">
                  <option value="ODBC Driver 18 for SQL Server">ODBC Driver 18 for SQL Server (recommended)</option>
                  <option value="ODBC Driver 17 for SQL Server">ODBC Driver 17 for SQL Server</option>
                  <option value="custom">Custom driver name</option>
                </select>
              </label>
              {draft.driver === "custom" ? (
                <label className="sv-field">
                  <span className="sv-label">Custom Driver Name</span>
                  <input value={draft.customDriver} onChange={(event) => onChange({ customDriver: event.target.value })} className="sv-input" />
                </label>
              ) : null}
            </>
          ) : (
            <label className="sv-field">
              <span className="sv-label">Connection SSL</span>
              <select value={draft.sslMode} onChange={(event) => onChange({ sslMode: event.target.value })} className="sv-select">
                <option value="prefer">Prefer SSL (default)</option>
                <option value="require">Require SSL</option>
                <option value="disable">Disable SSL</option>
                <option value="verify-ca">Verify certificate authority</option>
                <option value="verify-full">Verify certificate and host</option>
              </select>
            </label>
          )}
        </div>
      </details>
      {error ? <InlineMessage tone="warning">{error}</InlineMessage> : null}
      {mutationError ? <InlineMessage tone="error">{errorMessage(mutationError, "Unable to update database connection.")}</InlineMessage> : null}
      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        <button type="button" onClick={onCancel} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-label-md font-bold text-on-surface hover:border-primary">
          Cancel
        </button>
        <button type="submit" disabled={isSaving} className="sv-action-primary">
          {isSaving ? <Loader2 className="animate-spin" size={16} /> : <Save size={16} />}
          Save Changes
        </button>
      </div>
    </form>
  );
}

function ConnectorProfileCards({ catalogsByProfile = {}, emptyMessage, isLoading, onCreateAiDraft, onDeleteProfile, onEditProfile, onOpenCatalog, onProfileAction, pendingActionId, pendingActionType, pendingAiDraftProfileId, pendingDeleteProfileId, profiles, writableSpacePaths }: ConnectorProfileCardsProps) {
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
                <td className="align-top">
                  <div className="connector-identity-cell">
                    <strong className="block text-on-surface">{profile.name}</strong>
                    <span className="text-label-md font-bold text-on-surface-variant">{connectorTypeLabel(profile.connector_type)}</span>
                    <small className="text-secondary">{profileEndpointSummary(profile)}</small>
                  </div>
                </td>
                <td className="align-top">
                  <div className="connector-status-stack">
                    <ConnectorStatusPill className={profileHealthPillClass(profile)} label={profileHealthLabel(profile)} minWidth="7.25rem" />
                    <small className={profile.last_test_status === "failed" ? "block text-error-red" : "block text-secondary"}>{profileTestDetail(profile)}</small>
                  </div>
                </td>
                <td className="align-top">
                  {currentCatalog ? (
                    <ConnectorSchemaProgress catalog={currentCatalog} />
                  ) : (
                    <div className="connector-status-stack">
                      <ConnectorStatusPill className="sv-pill sv-pill-warning" label="Needs review" minWidth="8.5rem" />
                      <small className="block text-secondary">Read schema, then prepare review</small>
                    </div>
                  )}
                </td>
                <td className="align-top">
                  <div className="connector-status-stack">
                    <ConnectorStatusPill className={catalogAccessPillClass(currentCatalog?.status ?? "draft")} label={catalogAccessStateLabel(currentCatalog?.status ?? "draft")} minWidth="7.25rem" />
                    <small className="block text-secondary">{catalogAccessStateHint(currentCatalog?.status ?? "draft")}</small>
                  </div>
                </td>
                <td className="connector-actions-cell align-top">
                  <ConnectorRowActions
                    catalog={currentCatalog}
                    onCreateAiDraft={onCreateAiDraft}
                    onDeleteProfile={onDeleteProfile}
                    onEditProfile={onEditProfile}
                    onOpenCatalog={onOpenCatalog}
                    onProfileAction={onProfileAction}
                    pendingActionId={pendingActionId}
                    pendingActionType={pendingActionType}
                    pendingAiDraftProfileId={pendingAiDraftProfileId}
                    pendingDeleteProfileId={pendingDeleteProfileId}
                    profile={profile}
                    writableSpacePaths={writableSpacePaths}
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
  onCreateAiDraft,
  onDeleteProfile,
  onEditProfile,
  onOpenCatalog,
  onProfileAction,
  pendingActionId,
  pendingActionType,
  pendingAiDraftProfileId,
  pendingDeleteProfileId,
  profile,
  writableSpacePaths,
}: ConnectorRowActionsProps) {
  const profileActionPending = pendingActionId === profile.id;
  const primaryPending = pendingAiDraftProfileId === profile.id;
  const primaryDisabled = pendingAiDraftProfileId !== null || (!catalog && writableSpacePaths.length === 0);
  const primaryLabel = primaryPending ? "Preparing" : catalog ? "Review" : "Prepare Review";

  return (
    <div className="connector-row-actions">
      <button
        type="button"
        disabled={primaryDisabled}
        onClick={() => catalog ? onOpenCatalog(profile, catalog) : onCreateAiDraft(profile)}
        className="sv-action-secondary connector-row-primary-action"
      >
        {primaryPending ? <Loader2 className="animate-spin" size={14} /> : catalog ? <CheckCircle2 size={14} /> : <Sparkles size={14} />}
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
          <button type="button" disabled={profileActionPending} onClick={() => onProfileAction("introspect", profile.id)}>
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

function ConnectorCatalogReadiness({ catalogsByProfile, connectorProfiles, isError, isLoading, onCreateAiDraft, onOpenCatalog, pendingAiDraftProfileId, writableSpacePaths }: ConnectorCatalogReadinessProps) {
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
        <div className="sv-table-wrap">
          <table className="sv-table">
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
                  <td>
                    <strong className="block text-on-surface">{profile.name}</strong>
                    <small className="text-secondary">{connectorTypeLabel(profile.connector_type)}</small>
                  </td>
                  <td>
                    {catalog ? (
                      <ConnectorStatusPill className={catalogReviewPillClass(catalog.status)} label={catalogReviewLabel(catalog.status)} />
                    ) : (
                      <ConnectorStatusPill className="sv-pill sv-pill-warning" label="Needs review" />
                    )}
                  </td>
                  <td>{catalog ? connectorSchemaAccessSummary(catalog) : "No schema review prepared"}</td>
                  <td>{catalog ? `${catalogScopeSummary(catalog)} - ${clearanceLevelLabel(catalog.clearance_level as ClearanceLevel)}` : "Choose owner space during review"}</td>
                  <td>{catalog ? formatDateTime(catalog.updated_at ?? catalog.created_at) : "Not prepared"}</td>
                  <td>
                    {catalog ? (
                      <button type="button" onClick={() => onOpenCatalog(profile, catalog)} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary">
                        Review Access
                      </button>
                    ) : (
                      <button type="button" disabled={pendingAiDraftProfileId !== null || writableSpacePaths.length === 0} onClick={() => onCreateAiDraft(profile)} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                        <span className="inline-flex items-center gap-1">
                          {pendingAiDraftProfileId === profile.id ? <Loader2 className="animate-spin" size={14} /> : <Sparkles size={14} />}
                          {pendingAiDraftProfileId === profile.id ? "Preparing" : "Prepare Review"}
                        </span>
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {reviewCount === 0 ? <p className="mt-3 text-label-md text-secondary">No reviews are prepared yet. Use Prepare Review on the connection that should be available to Live DB.</p> : null}
        </div>
      ) : null}
    </section>
  );
}

function SchemaSnapshotModal({ onClose, viewer }: SchemaSnapshotModalProps) {
  const snapshot = viewer?.snapshot ?? null;
  const profile = viewer?.profile ?? null;
  const tables = snapshot ? schemaSnapshotTables(snapshot.schema_json) : [];
  const columnCount = tables.reduce((total, table) => total + table.columns.length, 0);
  const relationshipCount = tables.reduce((total, table) => total + table.foreignKeys.length, 0);
  const indexCount = tables.reduce((total, table) => total + table.indexes.length, 0);
  const visibleTables = tables.slice(0, 12);

  return (
    <Modal
      description="Review the latest raw schema captured from the connector before preparing a database access review."
      icon={<FileText size={18} />}
      onClose={onClose}
      open={Boolean(viewer)}
      size="lg"
      title="Schema Snapshot"
    >
      {snapshot ? (
        <section className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="sv-label">{profile?.name ?? connectorTypeLabel(snapshot.connector_type)}</p>
              <p className="mt-1 text-body-md text-on-surface-variant">
                {connectorTypeLabel(snapshot.connector_type)} introspection {snapshot.created_at ? `captured ${formatDateTime(snapshot.created_at)}` : "captured now"}.
              </p>
            </div>
            <span className={snapshot.status === "ok" ? "sv-pill sv-pill-success" : "sv-pill"}>
              {snapshot.status}
            </span>
          </div>

          {snapshot.status !== "ok" ? (
            <InlineMessage tone="error">{snapshot.error_message ?? "Schema introspection failed."}</InlineMessage>
          ) : (
            <>
              <dl className="grid gap-3 md:grid-cols-4">
                <SchemaSnapshotMetric label="Tables" value={tables.length.toString()} />
                <SchemaSnapshotMetric label="Columns" value={columnCount.toString()} />
                <SchemaSnapshotMetric label="Relationships" value={relationshipCount.toString()} />
                <SchemaSnapshotMetric label="Indexes" value={indexCount.toString()} />
              </dl>

              {tables.length === 0 ? (
                <InlineMessage tone="warning">The connector returned no tables in this schema snapshot.</InlineMessage>
              ) : (
                <div className="space-y-2">
                  {visibleTables.map((table) => (
                    <details key={table.key} className="rounded-md border border-surface-border bg-surface px-3 py-2">
                      <summary className="cursor-pointer text-body-md font-bold text-on-surface">
                        {table.key}
                        <span className="ml-2 text-label-md font-normal text-secondary">
                          {table.columns.length} column{table.columns.length === 1 ? "" : "s"}
                          {table.estimatedRowCount !== null ? `, ${table.estimatedRowCount} estimated rows` : ""}
                        </span>
                      </summary>
                      <div className="mt-3 space-y-3">
                        {table.columns.length > 0 ? (
                          <div className="grid gap-2 md:grid-cols-2">
                            {table.columns.slice(0, 16).map((column) => (
                              <span key={`${table.key}.${column.name}`} className="rounded-md border border-surface-border bg-surface-container-low px-2 py-1 text-label-md text-on-surface">
                                <strong>{column.name}</strong>
                                <span className="text-secondary"> {column.type}</span>
                              </span>
                            ))}
                          </div>
                        ) : (
                          <p className="text-body-md text-secondary">No columns were returned for this table.</p>
                        )}
                        {table.columns.length > 16 ? <p className="text-label-md text-secondary">Showing 16 of {table.columns.length} columns.</p> : null}
                        {table.primaryKeys.length > 0 ? <p className="text-label-md text-secondary">Primary key: {table.primaryKeys.join(", ")}</p> : null}
                        {table.foreignKeys.length > 0 ? <p className="text-label-md text-secondary">Foreign keys: {table.foreignKeys.map((key) => key.name || key.referencedTable).join(", ")}</p> : null}
                        {table.indexes.length > 0 ? <p className="text-label-md text-secondary">Indexes: {table.indexes.map((index) => index.name).filter(Boolean).join(", ")}</p> : null}
                      </div>
                    </details>
                  ))}
                  {tables.length > visibleTables.length ? (
                    <p className="text-label-md text-secondary">Showing {visibleTables.length} of {tables.length} tables. Prepare a review to choose the tables, columns, and joins Live DB may use.</p>
                  ) : null}
                </div>
              )}

              <details className="rounded-md border border-surface-border bg-surface px-3 py-2">
                <summary className="cursor-pointer text-label-md font-bold text-on-surface">Raw schema JSON</summary>
                <pre className="mt-3 max-h-80 overflow-auto rounded-md bg-surface-container-low p-3 text-xs text-on-surface">
                  {JSON.stringify(snapshot.schema_json, null, 2)}
                </pre>
              </details>
            </>
          )}
        </section>
      ) : null}
    </Modal>
  );
}

function SchemaSnapshotMetric({ label, value }: SchemaSnapshotMetricProps) {
  return (
    <div className="rounded-md border border-surface-border bg-surface px-3 py-2">
      <dt className="text-label-md font-bold uppercase tracking-wide text-secondary">{label}</dt>
      <dd className="mt-1 text-body-lg font-extrabold text-on-surface">{value}</dd>
    </div>
  );
}

function ConnectorCatalogEditor({ catalog, clearanceOptions, isSaving, mutationError, onClose, onContinueAiEnrichment, onSave, profile, writableSpacePaths }: ConnectorCatalogEditorProps) {
  const [draftJson, setDraftJson] = useState<SchemaCatalogJson>(() => normalizeCatalogJson(catalog.catalog_json));
  const [ownerGroupPath, setOwnerGroupPath] = useState(catalogOwnerGroupPath(catalog));
  const [sharedGroupPaths, setSharedGroupPaths] = useState<string[]>(() => catalogSharedGroupPaths(catalog));
  const [shareCandidate, setShareCandidate] = useState("");
  const [clearanceLevel, setClearanceLevel] = useState<ClearanceLevel>(catalog.clearance_level as ClearanceLevel);
  const [tableSearch, setTableSearch] = useState("");
  const [tableFilter, setTableFilter] = useState<SchemaCatalogFilter>("all");
  const [joinDraft, setJoinDraft] = useState<SchemaJoinDraft>(() => emptySchemaJoinDraft());
  const [reviewTab, setReviewTab] = useState<ConnectorReviewTab>("summary");

  useEffect(() => {
    setDraftJson(normalizeCatalogJson(catalog.catalog_json));
    setOwnerGroupPath(catalogOwnerGroupPath(catalog));
    setSharedGroupPaths(catalogSharedGroupPaths(catalog));
    setShareCandidate("");
    setClearanceLevel(catalog.clearance_level as ClearanceLevel);
    setTableSearch("");
    setTableFilter("all");
    setJoinDraft(emptySchemaJoinDraft());
    setReviewTab("summary");
  }, [catalog]);

  const tables = draftJson.tables ?? [];
  const relationships = draftJson.relationships ?? [];
  const tableOptions = useMemo(() => tables.map(schemaCatalogTableKey).filter(Boolean), [tables]);
  const leftJoinColumns = useMemo(() => schemaCatalogColumnsForTable(tables, joinDraft.leftTable), [joinDraft.leftTable, tables]);
  const rightJoinColumns = useMemo(() => schemaCatalogColumnsForTable(tables, joinDraft.rightTable), [joinDraft.rightTable, tables]);
  const reviewStats = schemaCatalogReviewStats(draftJson);
  const accessGroupPaths = useMemo(() => uniqueGroupPaths([ownerGroupPath, ...sharedGroupPaths]), [ownerGroupPath, sharedGroupPaths]);
  const approvalWarnings = schemaCatalogApprovalWarnings(reviewStats, ownerGroupPath);
  const visibleTables = useMemo(
    () => tables
      .map((table, tableIndex) => ({ table, tableIndex }))
      .filter(({ table }) => schemaCatalogTableMatches(table, tableSearch, tableFilter)),
    [tableFilter, tableSearch, tables],
  );
  const enrichmentStatus = schemaCatalogAiEnrichmentStatus(draftJson);
  const enrichmentError = schemaCatalogAiEnrichmentError(draftJson);
  const aiGenerated = enrichmentStatus === "generated";
  const aiFailed = enrichmentStatus === "failed";
  const missingAiTableCount = schemaCatalogPendingTableKeys(draftJson).length;
  const aiIncomplete = enrichmentStatus === "pending" || enrichmentStatus === "in_progress" || enrichmentStatus === "partial" || aiFailed || missingAiTableCount > 0;
  const canContinueAiEnrichment = aiIncomplete && (catalog.status === "draft" || catalog.status === "reviewed");
  const groupOptions = Array.from(new Set(["", ownerGroupPath, ...writableSpacePaths].filter((value, index) => index === 0 || Boolean(value))));
  const shareOptions = writableSpacePaths.filter((path) => path !== ownerGroupPath && !sharedGroupPaths.includes(path));
  const joinDraftReady = Boolean(joinDraft.leftTable && joinDraft.leftColumn && joinDraft.rightTable && joinDraft.rightColumn);
  const joinDraftDuplicate = joinDraftReady && relationships.some((relationship) => schemaCatalogRelationshipMatchesDraft(relationship, joinDraft));

  function updateTable(index: number, patch: Partial<SchemaCatalogTable>) {
    setDraftJson((current) => {
      const next = normalizeCatalogJson(current);
      const nextTables = [...(next.tables ?? [])];
      nextTables[index] = { ...nextTables[index], ...patch };
      return { ...next, tables: nextTables };
    });
  }

  function updateColumn(tableIndex: number, columnIndex: number, patch: Partial<SchemaCatalogColumn>) {
    setDraftJson((current) => {
      const next = normalizeCatalogJson(current);
      const nextTables = [...(next.tables ?? [])];
      const table = { ...nextTables[tableIndex] };
      const columns = [...(table.columns ?? [])];
      columns[columnIndex] = { ...columns[columnIndex], ...patch };
      table.columns = columns;
      nextTables[tableIndex] = table;
      return { ...next, tables: nextTables };
    });
  }

  function updateRelationship(index: number, patch: Partial<SchemaCatalogRelationship>) {
    setDraftJson((current) => {
      const next = normalizeCatalogJson(current);
      const nextRelationships = [...(next.relationships ?? [])];
      nextRelationships[index] = { ...nextRelationships[index], ...patch };
      return { ...next, relationships: nextRelationships };
    });
  }

  function removeRelationship(index: number) {
    setDraftJson((current) => {
      const next = normalizeCatalogJson(current);
      return { ...next, relationships: (next.relationships ?? []).filter((_relationship, relationshipIndex) => relationshipIndex !== index) };
    });
  }

  function updateJoinDraft(patch: Partial<SchemaJoinDraft>) {
    setJoinDraft((current) => ({ ...current, ...patch }));
  }

  function addJoinDraft() {
    if (!joinDraftReady || joinDraftDuplicate) return;
    setDraftJson((current) => {
      const next = normalizeCatalogJson(current);
      const relationship: SchemaCatalogRelationship = {
        name: schemaCatalogManualRelationshipName(joinDraft),
        left_table: joinDraft.leftTable,
        left_columns: [joinDraft.leftColumn],
        right_table: joinDraft.rightTable,
        right_columns: [joinDraft.rightColumn],
        allowed: true,
        description: joinDraft.description,
        source: "manual",
      };
      return { ...next, relationships: [...(next.relationships ?? []), relationship] };
    });
    setJoinDraft(emptySchemaJoinDraft());
  }

  function addSharedGroupPath(path: string) {
    const groupPath = path.trim();
    if (!groupPath || groupPath === ownerGroupPath || sharedGroupPaths.includes(groupPath)) return;
    setSharedGroupPaths(uniqueGroupPaths([...sharedGroupPaths, groupPath]));
    setShareCandidate("");
  }

  function updateOwnerGroupPath(groupPath: string) {
    setOwnerGroupPath(groupPath);
    setSharedGroupPaths((current) => current.filter((path) => path !== groupPath));
    if (shareCandidate === groupPath) setShareCandidate("");
  }

  function bulkUpdateVisibleTables(patch: Partial<SchemaCatalogTable>) {
    const visibleIndexes = new Set(visibleTables.map((item) => item.tableIndex));
    setDraftJson((current) => {
      const next = normalizeCatalogJson(current);
      const nextTables = (next.tables ?? []).map((table, index) => visibleIndexes.has(index) ? { ...table, ...patch } : table);
      return { ...next, tables: nextTables };
    });
  }

  function bulkUpdateVisibleColumns(patch: Partial<SchemaCatalogColumn>) {
    const visibleIndexes = new Set(visibleTables.map((item) => item.tableIndex));
    setDraftJson((current) => {
      const next = normalizeCatalogJson(current);
      const nextTables = (next.tables ?? []).map((table, index) => {
        if (!visibleIndexes.has(index)) return table;
        return {
          ...table,
          columns: (table.columns ?? []).map((column) => ({ ...column, ...patch })),
        };
      });
      return { ...next, tables: nextTables };
    });
  }

  function handleSave(nextStatus: ConnectorSchemaCatalogStatus = "draft") {
    onSave({
      catalog_json: { ...(draftJson as Record<string, unknown>), shared_group_paths: sharedGroupPaths },
      status: nextStatus,
      group_path: ownerGroupPath,
      group_paths: accessGroupPaths,
      clearance_level: clearanceLevel,
    });
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-surface-border pb-4">
        <div>
          <p className="sv-label">Database access review</p>
          <h3 className="mt-1 text-body-lg font-extrabold text-on-surface">{catalogName(catalog, profile)}</h3>
          <p className="mt-1 max-w-3xl text-body-md text-on-surface-variant">
            Approving this review tells Live DB exactly which tables, columns, and joins it may use.
          </p>
        </div>
      </div>

      <ConnectorReviewTabs onChange={setReviewTab} value={reviewTab} />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="space-y-4">
          {reviewTab === "summary" ? (
            <>
          <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <SchemaReviewMetric label="Included tables" value={`${reviewStats.allowedTables}/${reviewStats.totalTables}`} />
            <SchemaReviewMetric label="Included columns" value={`${reviewStats.allowedColumns}/${reviewStats.totalColumns}`} />
            <SchemaReviewMetric label="Sensitive fields" value={reviewStats.sensitiveColumns.toString()} />
            <SchemaReviewMetric label="Missing text" value={reviewStats.missingDescriptions.toString()} />
          </dl>

          {aiFailed ? (
            <InlineMessage tone="warning">
              AI enrichment failed, so this review contains raw schema metadata only. You can still edit descriptions, mark sensitive fields, and approve access after review.
              {enrichmentError ? ` Detail: ${enrichmentError}` : ""}
            </InlineMessage>
          ) : null}
          {!aiFailed && aiIncomplete ? (
            <InlineMessage tone="warning">
              AI enrichment is incomplete. Completed table descriptions are saved, and remaining tables can be retried.
              {enrichmentError ? ` Detail: ${enrichmentError}` : ""}
            </InlineMessage>
          ) : null}
          {aiGenerated && !aiIncomplete ? (
            <p className="rounded-md border border-surface-border bg-surface px-3 py-2 text-label-md text-on-surface-variant">
              AI-generated metadata is editable. Live DB cannot use it until this review is approved.
            </p>
          ) : null}
          <label className="sv-field">
            <span className="sv-label">Review Name</span>
            <input value={draftJson.name ?? ""} onChange={(event) => setDraftJson((current) => ({ ...normalizeCatalogJson(current), name: event.target.value }))} placeholder={`${profile.name} Live DB access`} className="sv-input" />
          </label>
          <label className="sv-field">
            <span className="sv-label">Business Rules</span>
            <textarea
              value={(draftJson.business_rules ?? []).join("\n")}
              onChange={(event) => setDraftJson((current) => ({ ...normalizeCatalogJson(current), business_rules: event.target.value.split("\n").map((line) => line.trim()).filter(Boolean) }))}
              placeholder="One rule per line"
              className="sv-input min-h-24"
            />
          </label>
            </>
          ) : null}

          {reviewTab === "tables" ? (
            <>
          <section className="rounded-md border border-surface-border bg-surface p-3">
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_12rem]">
              <label className="sv-field">
                <span className="sv-label">Find schema objects</span>
                <span className="relative block">
                  <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-secondary" size={15} />
                  <input value={tableSearch} onChange={(event) => setTableSearch(event.target.value)} placeholder="Table, column, synonym, or description" className="sv-input pl-9" />
                </span>
              </label>
              <label className="sv-field">
                <span className="sv-label">Filter</span>
                <select value={tableFilter} onChange={(event) => setTableFilter(event.target.value as SchemaCatalogFilter)} className="sv-select">
                  <option value="all">All tables</option>
                  <option value="included">Included</option>
                  <option value="excluded">Excluded</option>
                  <option value="sensitive">Sensitive</option>
                  <option value="missing">Needs descriptions</option>
                </select>
              </label>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-label-md text-secondary">{visibleTables.length} visible</span>
              <button type="button" disabled={visibleTables.length === 0} onClick={() => bulkUpdateVisibleTables({ allowed: true, sensitive: false })} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                <span className="inline-flex items-center gap-1"><CheckCircle2 size={14} />Include visible</span>
              </button>
              <button type="button" disabled={visibleTables.length === 0} onClick={() => bulkUpdateVisibleTables({ allowed: false })} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                <span className="inline-flex items-center gap-1"><X size={14} />Exclude visible</span>
              </button>
              <button type="button" disabled={visibleTables.length === 0} onClick={() => bulkUpdateVisibleColumns({ allowed: false, sensitive: true })} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                <span className="inline-flex items-center gap-1"><ShieldAlert size={14} />Mark visible columns sensitive</span>
              </button>
              <button type="button" disabled={visibleTables.length === 0} onClick={() => bulkUpdateVisibleColumns({ sensitive: false })} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                Clear column sensitivity
              </button>
            </div>
          </section>

          <div className="space-y-3">
            {tables.length === 0 ? <p className="rounded-md border border-surface-border bg-surface p-3 text-body-md text-secondary">This catalog has no tables to review.</p> : null}
            {tables.length > 0 && visibleTables.length === 0 ? <p className="rounded-md border border-surface-border bg-surface p-3 text-body-md text-secondary">No tables match the current filter.</p> : null}
            {visibleTables.map(({ table, tableIndex }) => (
              <details key={table.key ?? `${table.schema}.${table.name}.${tableIndex}`} className="rounded-md border border-surface-border bg-surface p-3" open={tableIndex < 3}>
                <summary className="cursor-pointer text-body-md font-extrabold text-on-surface">
                  <span>{table.key ?? table.name ?? "Unnamed table"}</span>
                  <span className="ml-2 text-label-md font-normal text-secondary">{table.columns?.length ?? 0} columns</span>
                  <span className="ml-2 inline-flex flex-wrap gap-1 align-middle">
                    <span className={table.allowed !== false && table.sensitive !== true ? "sv-pill sv-pill-success" : "sv-pill"}>{table.allowed !== false && table.sensitive !== true ? "included" : "excluded"}</span>
                    {table.sensitive === true ? <span className="sv-pill">sensitive</span> : null}
                    {schemaCatalogTableNeedsEnrichment(table) ? <span className="sv-pill">needs text</span> : null}
                  </span>
                </summary>
                <div className="mt-3 grid gap-3">
                  <div className="flex flex-wrap gap-3">
                    <label className="inline-flex items-center gap-2 text-label-md font-bold text-on-surface">
                      <input type="checkbox" checked={table.allowed !== false} onChange={(event) => updateTable(tableIndex, { allowed: event.target.checked })} />
                      Allowed
                    </label>
                    <label className="inline-flex items-center gap-2 text-label-md font-bold text-on-surface">
                      <input type="checkbox" checked={table.sensitive === true} onChange={(event) => updateTable(tableIndex, { sensitive: event.target.checked })} />
                      Sensitive
                    </label>
                  </div>
                  <label className="sv-field">
                    <span className="sv-label">Table Description</span>
                    <textarea value={table.description ?? ""} onChange={(event) => updateTable(tableIndex, { description: event.target.value })} className="sv-input min-h-20" />
                  </label>
                  <label className="sv-field">
                    <span className="sv-label">Table Synonyms</span>
                    <input value={(table.synonyms ?? []).join(", ")} onChange={(event) => updateTable(tableIndex, { synonyms: splitCommaList(event.target.value) })} className="sv-input" />
                  </label>
                  <div className="rounded-md border border-surface-border">
                    {(table.columns ?? []).map((column, columnIndex) => (
                      <div key={`${column.name ?? columnIndex}`} className="grid gap-3 border-b border-surface-border p-3 last:border-b-0 lg:grid-cols-[minmax(10rem,12rem)_minmax(0,1fr)]">
                        <div>
                          <strong className="block text-body-md text-on-surface">{column.name}</strong>
                          <small className="text-secondary">{column.data_type ?? "unknown"}</small>
                          <div className="mt-2 flex flex-wrap gap-3">
                            <label className="inline-flex items-center gap-2 text-label-md font-bold text-on-surface">
                              <input type="checkbox" checked={column.allowed !== false} onChange={(event) => updateColumn(tableIndex, columnIndex, { allowed: event.target.checked })} />
                              Allowed
                            </label>
                            <label className="inline-flex items-center gap-2 text-label-md font-bold text-on-surface">
                              <input type="checkbox" checked={column.sensitive === true} onChange={(event) => updateColumn(tableIndex, columnIndex, { sensitive: event.target.checked })} />
                              Sensitive
                            </label>
                          </div>
                          {column.sensitive === true || column.allowed === false ? <small className="mt-2 block text-secondary">Excluded from Live DB SQL prompts.</small> : null}
                        </div>
                        <div className="grid gap-2">
                          <textarea value={column.description ?? ""} onChange={(event) => updateColumn(tableIndex, columnIndex, { description: event.target.value })} placeholder="Column meaning" className="sv-input min-h-16" />
                          <input value={(column.synonyms ?? []).join(", ")} onChange={(event) => updateColumn(tableIndex, columnIndex, { synonyms: splitCommaList(event.target.value) })} placeholder="Synonyms, comma separated" className="sv-input" />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </details>
            ))}
          </div>
            </>
          ) : null}

          {reviewTab === "joins" ? (
          <details className="rounded-md border border-surface-border bg-surface p-3" open>
            <summary className="cursor-pointer text-body-md font-extrabold text-on-surface">
              <span className="inline-flex items-center gap-2"><Network size={16} />Joins</span>
              <span className="ml-2 text-label-md font-normal text-secondary">{schemaCatalogAllowedRelationships(relationships)} of {relationships.length} joins approved</span>
            </summary>
            <div className="mt-3 rounded-md border border-surface-border bg-surface-container-low p-3">
              <div className="mb-3">
                <p className="text-label-md font-extrabold text-on-surface">Add inferred join</p>
                <p className="mt-1 text-label-md text-secondary">Use this when the database does not declare a foreign key, but reviewers know the columns should join.</p>
              </div>
              <div className="grid gap-3 xl:grid-cols-4">
                <label className="sv-field">
                  <span className="sv-label">Left Table</span>
                  <select value={joinDraft.leftTable} onChange={(event) => updateJoinDraft({ leftTable: event.target.value, leftColumn: "" })} className="sv-select">
                    <option value="">Select table</option>
                    {tableOptions.map((tableKey) => <option key={`left.${tableKey}`} value={tableKey}>{tableKey}</option>)}
                  </select>
                </label>
                <label className="sv-field">
                  <span className="sv-label">Left Column</span>
                  <select value={joinDraft.leftColumn} onChange={(event) => updateJoinDraft({ leftColumn: event.target.value })} disabled={!joinDraft.leftTable} className="sv-select disabled:opacity-50">
                    <option value="">Select column</option>
                    {leftJoinColumns.map((column) => <option key={`left.${joinDraft.leftTable}.${column}`} value={column}>{column}</option>)}
                  </select>
                </label>
                <label className="sv-field">
                  <span className="sv-label">Right Table</span>
                  <select value={joinDraft.rightTable} onChange={(event) => updateJoinDraft({ rightTable: event.target.value, rightColumn: "" })} className="sv-select">
                    <option value="">Select table</option>
                    {tableOptions.map((tableKey) => <option key={`right.${tableKey}`} value={tableKey}>{tableKey}</option>)}
                  </select>
                </label>
                <label className="sv-field">
                  <span className="sv-label">Right Column</span>
                  <select value={joinDraft.rightColumn} onChange={(event) => updateJoinDraft({ rightColumn: event.target.value })} disabled={!joinDraft.rightTable} className="sv-select disabled:opacity-50">
                    <option value="">Select column</option>
                    {rightJoinColumns.map((column) => <option key={`right.${joinDraft.rightTable}.${column}`} value={column}>{column}</option>)}
                  </select>
                </label>
              </div>
              <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_9rem]">
                <input value={joinDraft.description} onChange={(event) => updateJoinDraft({ description: event.target.value })} placeholder="Join meaning, optional" className="sv-input" />
                <button type="button" disabled={!joinDraftReady || Boolean(joinDraftDuplicate)} onClick={addJoinDraft} className="sv-action-secondary justify-center disabled:opacity-50">
                  <Plus size={16} />
                  Add Join
                </button>
              </div>
              {joinDraftDuplicate ? <p className="mt-2 text-label-md text-secondary">That join is already in the review.</p> : null}
            </div>
            {relationships.length === 0 ? (
              <p className="mt-3 text-body-md text-secondary">No joins are in this review yet. Add one above or rerun Schema after foreign keys are added to the database.</p>
            ) : (
              <div className="mt-3 grid gap-2">
                {relationships.map((relationship, relationshipIndex) => (
                  <div key={`${schemaCatalogRelationshipLabel(relationship)}.${relationshipIndex}`} className="grid gap-3 rounded-md border border-surface-border bg-surface-container-low p-3 lg:grid-cols-[minmax(0,1fr)_9rem]">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <strong className="block text-body-md text-on-surface" style={{ overflowWrap: "anywhere" }}>{schemaCatalogRelationshipLabel(relationship)}</strong>
                        {schemaCatalogRelationshipSource(relationship) === "manual" ? <span className="sv-pill">manual</span> : <span className="sv-pill">detected</span>}
                      </div>
                      <textarea
                        value={relationship.description ?? ""}
                        onChange={(event) => updateRelationship(relationshipIndex, { description: event.target.value })}
                        placeholder="Join meaning"
                        className="sv-input mt-2 min-h-16"
                      />
                    </div>
                    <div className="grid content-start gap-2">
                      <label className="inline-flex items-start gap-2 text-label-md font-bold text-on-surface">
                        <input type="checkbox" checked={relationship.allowed !== false} onChange={(event) => updateRelationship(relationshipIndex, { allowed: event.target.checked })} />
                        Approved join
                      </label>
                      <button type="button" onClick={() => removeRelationship(relationshipIndex)} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-error-red hover:border-error-red">
                        <span className="inline-flex items-center gap-1"><Trash2 size={14} />Remove</span>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </details>
          ) : null}

          {reviewTab === "access" ? (
            <section className="space-y-4 rounded-md border border-surface-border bg-surface p-3">
              <div>
                <p className="sv-label">Live DB Access</p>
                <strong className="mt-1 block text-body-md text-on-surface">{catalogAccessStateLabel(catalog.status)}</strong>
                <p className="mt-1 text-body-md text-on-surface-variant">{catalogAccessStateDescription(catalog.status)}</p>
              </div>
              <SelectField label="Owner Space" value={ownerGroupPath} onChange={updateOwnerGroupPath} options={groupOptions} emptyLabel="Select space" helper="Primary owner for this review." />
              <div className="grid gap-2 border-t border-surface-border pt-3">
                <span className="sv-label">Shared Spaces</span>
                <div className="flex gap-2">
                  <select value={shareCandidate} onChange={(event) => setShareCandidate(event.target.value)} className="sv-select min-w-0 flex-1">
                    <option value="">Select space</option>
                    {shareOptions.map((path) => <option key={path} value={path}>{path}</option>)}
                  </select>
                  <button type="button" disabled={!shareCandidate} onClick={() => addSharedGroupPath(shareCandidate)} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50" aria-label="Add shared Knowledge Space">
                    <Plus size={14} />
                  </button>
                </div>
                {sharedGroupPaths.length ? (
                  <div className="flex flex-wrap gap-1">
                    {sharedGroupPaths.map((path) => (
                      <span key={path} className="inline-flex max-w-full items-center gap-1 rounded-md border border-surface-border px-2 py-1 text-label-md text-on-surface">
                        <span className="truncate">{path}</span>
                        <button type="button" onClick={() => setSharedGroupPaths(sharedGroupPaths.filter((value) => value !== path))} aria-label={`Remove ${path}`} className="text-secondary hover:text-error-red">
                          <X size={13} />
                        </button>
                      </span>
                    ))}
                  </div>
                ) : <small className="text-secondary">Owner only</small>}
              </div>
              <ClearanceSelect value={clearanceLevel} onChange={setClearanceLevel} options={clearanceOptions} />
            </section>
          ) : null}

          {reviewTab === "raw_schema" ? (
            <details className="rounded-md border border-surface-border bg-surface p-3" open>
              <summary className="cursor-pointer text-body-md font-extrabold text-on-surface">Raw schema catalog JSON</summary>
              <pre className="mt-3 max-h-[32rem] overflow-auto rounded-md bg-surface-container-low p-3 text-xs text-on-surface">
                {JSON.stringify(draftJson, null, 2)}
              </pre>
            </details>
          ) : null}
        </div>

        <aside className="rounded-md border border-surface-border bg-surface p-3">
          <div className="grid gap-3">
            <div>
              <p className="sv-label">Ready to enable</p>
              <dl className="mt-2 grid gap-2 text-label-md">
                <SchemaReviewStat label="Included tables" value={`${reviewStats.allowedTables}/${reviewStats.totalTables}`} />
                <SchemaReviewStat label="Excluded tables" value={reviewStats.excludedTables.toString()} />
                <SchemaReviewStat label="Sensitive columns" value={reviewStats.sensitiveColumns.toString()} />
                <SchemaReviewStat label="Approved joins" value={`${schemaCatalogAllowedRelationships(relationships)}/${relationships.length}`} />
              </dl>
            </div>
            {approvalWarnings.length > 0 ? (
              <InlineMessage tone="warning">{approvalWarnings[0]}</InlineMessage>
            ) : (
              <p className="rounded-md border border-surface-border bg-surface-container-low px-3 py-2 text-label-md text-on-surface-variant">This review is ready when the access settings are correct.</p>
            )}
            <div className="rounded-md border border-surface-border bg-surface-container-low px-3 py-2">
              <span className="sv-label">Live DB Access</span>
              <strong className="mt-1 block text-body-md text-on-surface">{catalogAccessStateLabel(catalog.status)}</strong>
              <small className="mt-1 block text-secondary">{catalogAccessStateDescription(catalog.status)}</small>
            </div>
            <button type="button" onClick={() => setReviewTab("access")} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-label-md font-bold text-on-surface hover:border-primary">
              Edit Access Settings
            </button>
            {mutationError ? <InlineMessage tone="error">{errorMessage(mutationError, "Unable to save database access review.")}</InlineMessage> : null}
            {canContinueAiEnrichment ? (
              <button type="button" disabled={isSaving} onClick={onContinueAiEnrichment} className="sv-action-secondary justify-center disabled:opacity-50">
                <Sparkles size={16} />
                Continue AI Enrichment
              </button>
            ) : null}
            <button type="button" disabled={isSaving || !ownerGroupPath} onClick={() => handleSave()} className="sv-action-secondary justify-center disabled:opacity-50">
              {isSaving ? <Loader2 className="animate-spin" size={16} /> : <Save size={16} />}
              Save Review
            </button>
            <button type="button" disabled={isSaving || !ownerGroupPath} onClick={() => handleSave("approved")} className="sv-action-primary justify-center disabled:opacity-50">
              {isSaving ? <Loader2 className="animate-spin" size={16} /> : <CheckCircle2 size={16} />}
              Enable Live DB Access
            </button>
            {catalog.status === "approved" ? (
              <button type="button" disabled={isSaving} onClick={() => handleSave("disabled")} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-label-md font-bold text-error-red hover:border-error-red disabled:opacity-50">
                <span className="inline-flex items-center justify-center gap-2"><Ban size={16} />Disable Live DB Access</span>
              </button>
            ) : null}
            <button type="button" onClick={onClose} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-label-md font-bold text-on-surface hover:border-primary">
              Close
            </button>
          </div>
        </aside>
      </div>
    </section>
  );
}

function SchemaReviewMetric({ label, value }: SchemaReviewMetricProps) {
  return (
    <div className="rounded-md border border-surface-border bg-surface px-3 py-2">
      <dt className="text-label-md font-bold uppercase tracking-wide text-secondary">{label}</dt>
      <dd className="mt-1 text-body-lg font-extrabold text-on-surface">{value}</dd>
    </div>
  );
}

function SchemaReviewStat({ label, value }: SchemaReviewMetricProps) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-surface-border py-1.5 last:border-b-0">
      <dt className="text-secondary">{label}</dt>
      <dd className="font-extrabold text-on-surface">{value}</dd>
    </div>
  );
}


function ScheduleListPanel({ emptyMessage, isError, isLoading, loadError, onAction, pendingActionId, pendingActionPending, schedules, title }: ScheduleListPanelProps) {
  return (
    <div className="mt-6 border-t border-surface-border pt-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="sv-section-title">{title}</h3>
        <p className="text-label-md text-secondary">{schedules.length} visible</p>
      </div>
      {isError ? <InlineMessage tone="error">{errorMessage(loadError, "Unable to load schedules.")}</InlineMessage> : null}
      {isLoading ? <p className="mt-3 text-body-md text-secondary">Loading schedules...</p> : null}
      {!isLoading && schedules.length === 0 ? (
        <p className="mt-3 rounded-md border border-surface-border bg-surface-container-low p-3 text-body-md text-on-surface-variant">
          {emptyMessage}
        </p>
      ) : null}
      <div className="mt-3 grid gap-3">
        {schedules.slice(0, 5).map((schedule) => (
          <ScheduleCard key={schedule.id} schedule={schedule} pendingAction={pendingActionId === schedule.id && pendingActionPending} onAction={(action) => onAction(action, schedule.id)} />
        ))}
      </div>
    </div>
  );
}

function FolderSnapshotReview({ label, onClear, onRemove, selection }: FolderSnapshotReviewProps) {
  return (
    <div className="mt-3 rounded-lg border border-surface-border bg-surface p-3 text-body-md text-on-surface-variant">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-body-md font-extrabold text-on-surface">
            <FolderOpen className="shrink-0 text-primary" size={17} />
            <span className="truncate">{label}</span>
          </p>
          <p className="mt-1 text-label-md text-secondary">Snapshot ready for review. Re-browse this folder later to stage a newer copy.</p>
        </div>
        <button type="button" onClick={onClear} className="rounded-md border border-surface-border bg-surface-container-low px-3 py-2 text-label-md font-bold text-on-surface hover:border-primary">
          Clear folder
        </button>
      </div>

      <dl className="mt-3 grid gap-2 sm:grid-cols-3">
        <SnapshotMetric label="Supported" value={formatFolderCount(selection.supportedEntries.length, "file")} />
        <SnapshotMetric label="Skipped" value={formatFolderCount(selection.unsupportedEntries.length, "item")} />
        <SnapshotMetric label="Staged size" value={formatFileSize(selection.supportedBytes)} />
      </dl>

      {selection.entries.length > 0 ? (
        <div className="mt-3">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <strong className="text-label-md uppercase tracking-wide text-secondary">Folder items</strong>
            <span className="text-label-md text-secondary">{formatFolderCount(selection.entries.length, "item")}</span>
          </div>
          <ul className="max-h-64 overflow-auto rounded-md border border-surface-border" aria-label="Selected folder snapshot files">
            {selection.entries.map((entry) => (
              <FolderSnapshotFileRow key={`${entry.relativePath}:${entry.file.size}:${entry.file.lastModified}`} entry={entry} onRemove={onRemove} />
            ))}
          </ul>
        </div>
      ) : null}

      {selection.unsupportedEntries.length > 0 ? (
        <p className="mt-3 rounded-md border border-surface-border bg-surface-container-low px-3 py-2 text-label-md text-secondary">
          {formatFolderCount(selection.unsupportedEntries.length, "unsupported item")} will be recorded as skipped because only PDF, DOCX, JPG, PNG, and JSON files are ingested.
        </p>
      ) : null}
    </div>
  );
}

function SnapshotMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-surface-border bg-surface-container-low px-3 py-2">
      <dt className="text-label-md font-bold uppercase tracking-wide text-secondary">{label}</dt>
      <dd className="mt-0.5 font-extrabold text-on-surface">{value}</dd>
    </div>
  );
}

function FolderSnapshotFileRow({ entry, onRemove }: FolderSnapshotFileRowProps) {
  return (
    <li className="flex items-center gap-3 border-b border-surface-border px-3 py-2 last:border-b-0">
      <FileText className="shrink-0 text-primary" size={16} />
      <span className="min-w-0 flex-1">
        <strong className="block truncate text-body-md text-on-surface">{entry.file.name}</strong>
        <small className="block truncate text-secondary">{entry.relativePath}</small>
      </span>
      <span className="shrink-0 text-label-md text-secondary">{formatFileSize(entry.file.size)}</span>
      <span className={entry.supported ? "sv-pill sv-pill-success shrink-0" : "sv-pill shrink-0"}>{entry.supported ? "Supported" : "Skipped"}</span>
      <button
        type="button"
        onClick={() => onRemove(entry.file)}
        className="rounded p-2 text-secondary hover:bg-surface-container-low hover:text-on-surface"
        aria-label={`Remove ${entry.file.name}`}
      >
        <X size={15} />
      </button>
    </li>
  );
}

function SelectField({ emptyLabel, helper, label, onChange, optionLabels = {}, options, value }: SelectProps) {
  return (
    <label className="sv-field">
      <span className="sv-label">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} className="sv-select">
        {options.map((option) => <option key={option || "empty"} value={option}>{option ? optionLabels[option] ?? option : emptyLabel || option}</option>)}
      </select>
      {helper ? <small className="text-secondary">{helper}</small> : null}
    </label>
  );
}

function ClearanceSelect({ onChange, options, value }: ClearanceSelectProps) {
  return (
    <label className="sv-field">
      <span className="sv-label">Clearance Level</span>
      <select value={value} onChange={(event) => onChange(event.target.value as ClearanceLevel)} className="sv-select">
        {options.map((option) => <option key={option} value={option}>{clearanceLevelLabel(option)}</option>)}
      </select>
      <small className="text-secondary">{clearanceLevelDescription(value)}</small>
    </label>
  );
}

function ScheduleCard({ onAction, pendingAction, schedule }: ScheduleCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const runsQuery = useQuery({
    queryKey: ["folder-ingest", "schedules", schedule.id, "runs"],
    queryFn: () => folderIngestApi.listRuns(schedule.id),
    enabled: expanded,
    retry: false,
  });
  const runItemsQuery = useQuery({
    queryKey: ["folder-ingest", "runs", selectedRunId, "items"],
    queryFn: () => folderIngestApi.listRunItems(selectedRunId ?? ""),
    enabled: Boolean(selectedRunId),
    retry: false,
  });
  const canPause = schedule.status === "active" || schedule.status === "scheduled";
  const canResume = schedule.status === "paused";
  const canCancel = !["cancelled", "complete"].includes(schedule.status);
  const runs = runsQuery.data?.items ?? [];
  return (
    <article className="rounded-lg border border-surface-border bg-surface-container-low p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="truncate text-body-md font-extrabold text-on-surface">{schedule.name}</h4>
            <StatusPill status={schedule.status} />
          </div>
          <p className="mt-1 text-label-md text-secondary">
            {sourceTypeLabel(schedule)} · {schedule.group_path} · {clearanceLevelLabel(schedule.clearance_level)} · {schedule.schedule_type === "recurring" ? "Recurring window" : "One-time start"}
          </p>
        </div>
        <div className="flex gap-2">
          {canPause ? <IconAction disabled={pendingAction} label="Pause" icon={<PauseCircle size={15} />} onClick={() => onAction("pause")} /> : null}
          {canResume ? <IconAction disabled={pendingAction} label="Resume" icon={<PlayCircle size={15} />} onClick={() => onAction("resume")} /> : null}
          {canCancel ? <IconAction disabled={pendingAction} label="Cancel" icon={<Ban size={15} />} onClick={() => onAction("cancel")} /> : null}
        </div>
      </div>
      <dl className="mt-3 grid gap-2 text-body-md text-on-surface-variant sm:grid-cols-3">
        <ScheduleStat label="Next run" value={formatDateTime(schedule.next_run_at)} />
        <ScheduleStat label="Last run" value={formatDateTime(schedule.last_run_at)} />
        <ScheduleStat label="Latest run" value={formatLatestRun(schedule)} />
      </dl>
      <button type="button" className="folder-schedule-expand" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
        {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        {expanded ? "Hide runs" : "Show runs"}
      </button>
      {expanded ? (
        <div className="folder-schedule-runs">
          {runsQuery.isError ? <InlineMessage tone="error">{errorMessage(runsQuery.error, "Unable to load folder runs.")}</InlineMessage> : null}
          {runsQuery.isLoading ? <p className="text-body-md text-secondary">Loading runs.</p> : null}
          {!runsQuery.isLoading && runs.length === 0 ? <p className="text-body-md text-secondary">No runs have been created for this schedule.</p> : null}
          {runs.map((run) => (
            <RunRow
              key={run.id}
              active={selectedRunId === run.id}
              onClick={() => setSelectedRunId((current) => current === run.id ? null : run.id)}
              run={run}
            />
          ))}
          {selectedRunId ? (
            <div className="folder-run-items">
              <div className="folder-run-items-header">
                <strong>Run items</strong>
                <span>{runItemsQuery.data?.total ?? 0} items</span>
              </div>
              {runItemsQuery.isError ? <InlineMessage tone="error">{errorMessage(runItemsQuery.error, "Unable to load run items.")}</InlineMessage> : null}
              {runItemsQuery.isLoading ? <p className="text-body-md text-secondary">Loading run items.</p> : null}
              {(runItemsQuery.data?.items ?? []).map((item) => (
                <div key={item.id} className="folder-run-item">
                  <FileText size={15} />
                  <span>
                    <strong>{item.filename}</strong>
                    <small>{item.source_path}</small>
                  </span>
                  <StatusText status={item.status} />
                  {item.skip_message ? <p>{item.skip_message}</p> : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function RunRow({ active, onClick, run }: { active: boolean; onClick: () => void; run: FolderRun }) {
  return (
    <button type="button" className={active ? "folder-run-row folder-run-row-active" : "folder-run-row"} onClick={onClick} aria-expanded={active}>
      <span>
        <strong>{formatDateTime(run.due_at)}</strong>
        <small>{run.item_count} items · {run.queued_count} queued · {run.skipped_count} skipped</small>
      </span>
      <StatusText status={run.status} />
      {active ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
    </button>
  );
}

function StatusText({ status }: { status: string }) {
  const attention = status === "failed" || status === "skipped" || status === "cancelled";
  return <span className={attention ? "folder-status-text folder-status-text-attention" : "folder-status-text"}>{status.replace("_", " ")}</span>;
}

function IconAction({ disabled, icon, label, onClick }: IconActionProps) {
  return (
    <button type="button" disabled={disabled} onClick={onClick} className="rounded-md border border-surface-border bg-surface px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
      <span className="inline-flex items-center gap-1">{icon}{label}</span>
    </button>
  );
}

function StatusPill({ status }: { status: FolderScheduleStatus }) {
  const className = status === "active" || status === "scheduled"
    ? "sv-pill sv-pill-success"
    : status === "failed"
      ? "sv-pill border-error-red/30 bg-error-container text-error-red"
      : "sv-pill";
  return <span className={className}>{status.replace("_", " ")}</span>;
}

function ConnectorStatusPill({ className, label, minWidth }: { className: string; label: string; minWidth?: string }) {
  return <span className={`${className} justify-center whitespace-nowrap`} style={minWidth ? { minWidth } : undefined}>{label}</span>;
}

function ConnectorEmptyState({ detail, title }: { detail: string; title: string }) {
  return (
    <div className="rounded-md border border-dashed border-surface-border bg-surface p-3 text-body-md text-on-surface-variant">
      <p className="font-bold text-on-surface">{title}</p>
      <p className="mt-1">{detail}</p>
    </div>
  );
}

function ScheduleStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-label-md font-bold uppercase tracking-wide text-secondary">{label}</dt>
      <dd className="mt-0.5 text-on-surface">{value}</dd>
    </div>
  );
}

function validateDraft(draft: FolderScheduleDraft, selection: ReturnType<typeof summarizeFolderFiles>, writableSpacePaths: string[]): string | null {
  if (!draft.name.trim()) return "Enter a schedule name.";
  if (!draft.groupPath || !writableSpacePaths.includes(draft.groupPath)) return "Select a writable Knowledge Space.";
  if (draft.scheduleType === "one_time" && !draft.scheduledAt) return "Choose the one-time start time.";
  if (draft.scheduleType === "recurring" && draft.recurrenceDays.length === 0) return "Select at least one recurring day.";
  if (draft.sourceMode === "snapshot") {
    if (selection.entries.length === 0) return "Choose a folder snapshot.";
    if (selection.validationMessages.length > 0) return selection.validationMessages[0] ?? "Selected folder is invalid.";
  }
  if (draft.sourceMode === "local_folder" && !draft.folderPath.trim()) {
    return "Enter a watched folder path.";
  }
  if (draft.sourceMode === "connector") {
    if (!draft.connectorProfileId) return "Select a database connection.";
    if (!draft.connectorQuery.trim()) return "Enter a read-only SQL selection.";
    if (identityFieldsFromDraft(draft.connectorIdentityFields).length === 0) return "Enter at least one stable identity field.";
  }
  return null;
}

function validateProfileDraft(draft: ConnectorProfileDraft, options: ProfileValidationOptions = { credentialsRequired: true }): string | null {
  if (!draft.name.trim()) return "Enter a connection name.";
  if (!draft.server.trim()) return draft.connectorType === "postgres" ? "Enter the PostgreSQL host." : "Enter the SQL Server host or listener.";
  if (draft.port.trim() && !Number.isInteger(Number(draft.port))) return "Enter a valid database port.";
  if (!draft.database.trim()) return "Enter the database name.";
  if (options.credentialsRequired) {
    if (!draft.username.trim()) return "Enter a read-only username.";
    if (!draft.password) return "Enter the connector password.";
  } else if (draft.username.trim() || draft.password) {
    if (!draft.username.trim() || !draft.password) return "Enter both replacement user and replacement password, or leave both blank.";
  }
  if (draft.connectorType === "sql_server" && draft.driver === "custom" && !draft.customDriver.trim()) return "Enter the custom SQL Server driver name.";
  return null;
}

function formatDateTime(value: string | null): string {
  if (!value) return "Not scheduled";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: WORKSPACE_TIMEZONE }).format(new Date(value));
}

function formatLatestRun(schedule: FolderSchedule): string {
  if (!schedule.latest_run) return "No runs";
  const run = schedule.latest_run;
  return `${run.status}: ${run.queued_count} queued, ${run.skipped_count} skipped`;
}

function profileTestDetail(profile: ConnectorProfile): string {
  if (!profile.last_test_status) return "Connection not tested";
  const result = profile.last_test_status === "ok" ? "Connection test passed" : "Connection test failed";
  const message = profile.last_test_message?.trim();
  const testedAt = profile.last_tested_at ? ` (${formatDateTime(profile.last_tested_at)})` : "";
  return `${result}${message ? `: ${message}` : ""}${testedAt}`;
}

function schemaSnapshotSummary(schemaJson: Record<string, unknown>): string {
  const tables = schemaSnapshotTables(schemaJson);
  const columnCount = tables.reduce((total, table) => total + table.columns.length, 0);
  return `${tables.length} table${tables.length === 1 ? "" : "s"} and ${columnCount} column${columnCount === 1 ? "" : "s"} found.`;
}

function schemaSnapshotTables(schemaJson: Record<string, unknown>): SchemaSnapshotTableSummary[] {
  const rawTables = Array.isArray(schemaJson.tables) ? schemaJson.tables : Array.isArray(schemaJson.collections) ? schemaJson.collections : [];
  return rawTables.filter(isRecord).map((table, index) => {
    const schema = stringValue(table.schema);
    const name = stringValue(table.name) || stringValue(table.collection) || `table_${index + 1}`;
    const key = stringValue(table.key) || [schema, name].filter(Boolean).join(".") || name;
    const sampleMetadata = isRecord(table.sample_metadata) ? table.sample_metadata : {};
    const columns = Array.isArray(table.columns) ? table.columns.filter(isRecord).map((column, columnIndex) => ({
      name: stringValue(column.name) || `column_${columnIndex + 1}`,
      type: stringValue(column.type) || stringValue(column.data_type) || "unknown",
    })) : [];
    const primaryKeys = Array.isArray(table.primary_keys)
      ? table.primary_keys.map((item) => isRecord(item) ? stringValue(item.name) || stringValue(item.column) || stringValue(item.columns) : stringValue(item)).filter(Boolean)
      : [];
    const foreignKeys = Array.isArray(table.foreign_keys) ? table.foreign_keys.filter(isRecord).map((item) => ({
      name: stringValue(item.name),
      referencedTable: stringValue(item.referenced_table),
    })) : [];
    const indexes = Array.isArray(table.indexes) ? table.indexes.filter(isRecord).map((item) => ({
      name: stringValue(item.name),
    })) : [];

    return {
      key,
      columns,
      primaryKeys,
      foreignKeys,
      indexes,
      estimatedRowCount: numberValue(sampleMetadata.estimated_row_count ?? table.estimated_row_count),
    };
  });
}

function sourceTypeLabel(schedule: FolderSchedule): string {
  if (schedule.source_type === "snapshot") return "Browser snapshot";
  if (schedule.source_type === "local_folder") return "Watched folder";
  if (schedule.source_type === "minio_prefix") return "S3/MinIO prefix";
  if (schedule.source_type === "connector") {
    const connectorType = typeof schedule.source_config.connector_type === "string" ? schedule.source_config.connector_type : "database";
    return connectorTypeLabel(connectorType);
  }
  return connectorTypeLabel(schedule.source_type);
}

function normalizeCatalogJson(value: Record<string, unknown>): SchemaCatalogJson {
  const tables = Array.isArray(value.tables) ? value.tables.filter(isSchemaCatalogTable).map((table) => ({
    ...table,
    columns: Array.isArray(table.columns) ? table.columns.filter(isSchemaCatalogColumn) : [],
    synonyms: Array.isArray(table.synonyms) ? table.synonyms.filter(isString) : [],
  })) : [];
  const relationships = Array.isArray(value.relationships) ? value.relationships.filter(isSchemaCatalogRelationship).map((relationship) => ({
    ...relationship,
    left_columns: Array.isArray(relationship.left_columns) ? relationship.left_columns.filter(isString) : [],
    right_columns: Array.isArray(relationship.right_columns) ? relationship.right_columns.filter(isString) : [],
  })) : [];
  const businessRules = Array.isArray(value.business_rules) ? value.business_rules.filter(isString) : [];
  return {
    ...value,
    name: typeof value.name === "string" ? value.name : "",
    tables,
    relationships,
    business_rules: businessRules,
    ai_enrichment: value.ai_enrichment,
  };
}

function schemaCatalogAiEnrichmentStatus(value: Record<string, unknown>): string {
  const metadata = isRecord(value.ai_enrichment) ? value.ai_enrichment : {};
  return stringValue(metadata.status);
}

function schemaCatalogAiEnrichmentError(value: Record<string, unknown>): string {
  const metadata = isRecord(value.ai_enrichment) ? value.ai_enrichment : {};
  return stringValue(metadata.error_message);
}

function schemaCatalogPendingTableKeys(value: Record<string, unknown>): string[] {
  const metadata = isRecord(value.ai_enrichment) ? value.ai_enrichment : {};
  const statuses = Array.isArray(metadata.table_statuses) ? metadata.table_statuses.filter(isRecord) : [];
  if (statuses.length > 0) {
    return statuses
      .filter((item) => stringValue(item.status) !== "generated")
      .map((item) => stringValue(item.table_key))
      .filter(Boolean);
  }
  const catalog = normalizeCatalogJson(value);
  return (catalog.tables ?? []).filter(schemaCatalogTableNeedsEnrichment).map(schemaCatalogTableKey).filter(Boolean);
}

function aiDraftProgressFromCatalog(catalog: ConnectorSchemaCatalog, currentTable: string | null): AiDraftProgress {
  const metadata = isRecord(catalog.catalog_json.ai_enrichment) ? catalog.catalog_json.ai_enrichment : {};
  const statuses = Array.isArray(metadata.table_statuses) ? metadata.table_statuses.filter(isRecord) : [];
  const total = statuses.length || (normalizeCatalogJson(catalog.catalog_json).tables ?? []).length;
  const failed = statuses.filter((item) => stringValue(item.status) === "failed").length;
  const completed = statuses.filter((item) => ["generated", "failed"].includes(stringValue(item.status))).length;
  return { catalogId: catalog.id, completed, currentTable, failed, total };
}

function schemaCatalogTableKey(table: SchemaCatalogTable): string {
  if (typeof table.key === "string" && table.key.trim()) return table.key.trim().toLowerCase();
  const schema = typeof table.schema === "string" ? table.schema.trim() : "";
  const name = typeof table.name === "string" ? table.name.trim() : "";
  return `${schema ? `${schema}.` : ""}${name}`.toLowerCase();
}

function schemaCatalogTableNeedsEnrichment(table: SchemaCatalogTable): boolean {
  if (!stringValue(table.description).trim()) return true;
  return (table.columns ?? []).some((column) => !stringValue(column.description).trim());
}

function schemaCatalogReviewStats(catalog: SchemaCatalogJson): SchemaCatalogReviewStats {
  const stats: SchemaCatalogReviewStats = {
    allowedColumns: 0,
    allowedTables: 0,
    excludedTables: 0,
    missingDescriptions: 0,
    sensitiveColumns: 0,
    totalColumns: 0,
    totalTables: catalog.tables?.length ?? 0,
  };
  for (const table of catalog.tables ?? []) {
    const tableIncluded = table.allowed !== false && table.sensitive !== true;
    if (tableIncluded) stats.allowedTables += 1;
    else stats.excludedTables += 1;
    if (tableIncluded && !stringValue(table.description).trim()) stats.missingDescriptions += 1;
    for (const column of table.columns ?? []) {
      stats.totalColumns += 1;
      const columnIncluded = tableIncluded && column.allowed !== false && column.sensitive !== true;
      if (column.sensitive === true) stats.sensitiveColumns += 1;
      if (columnIncluded) stats.allowedColumns += 1;
      if (columnIncluded && !stringValue(column.description).trim()) stats.missingDescriptions += 1;
    }
  }
  return stats;
}

function schemaCatalogApprovalWarnings(stats: SchemaCatalogReviewStats, ownerGroupPath: string): string[] {
  const warnings: string[] = [];
  if (!ownerGroupPath) warnings.push("Select an owner Knowledge Space before enabling Live DB access.");
  if (stats.allowedTables === 0) warnings.push("Include at least one table before enabling Live DB access.");
  if (stats.allowedColumns === 0) warnings.push("Include at least one column before enabling Live DB access.");
  if (stats.missingDescriptions > 0) warnings.push(`${stats.missingDescriptions} included schema item${stats.missingDescriptions === 1 ? "" : "s"} still need descriptions.`);
  return warnings;
}

function schemaCatalogTableMatches(table: SchemaCatalogTable, search: string, filter: SchemaCatalogFilter): boolean {
  const tableIncluded = table.allowed !== false && table.sensitive !== true;
  const hasSensitive = table.sensitive === true || (table.columns ?? []).some((column) => column.sensitive === true);
  const matchesFilter =
    filter === "all" ||
    (filter === "included" && tableIncluded) ||
    (filter === "excluded" && !tableIncluded) ||
    (filter === "sensitive" && hasSensitive) ||
    (filter === "missing" && schemaCatalogTableNeedsEnrichment(table));
  if (!matchesFilter) return false;
  const query = search.trim().toLowerCase();
  if (!query) return true;
  return schemaCatalogTableSearchText(table).includes(query);
}

function schemaCatalogTableSearchText(table: SchemaCatalogTable): string {
  const parts = [
    table.key,
    table.schema,
    table.name,
    table.description,
    ...(table.synonyms ?? []),
  ];
  for (const column of table.columns ?? []) {
    parts.push(column.name, column.data_type, column.description, ...(column.synonyms ?? []));
  }
  return parts.map(stringValue).join(" ").toLowerCase();
}

function schemaCatalogAllowedRelationships(relationships: SchemaCatalogRelationship[]): number {
  return relationships.filter((relationship) => relationship.allowed !== false).length;
}

function schemaCatalogRelationshipLabel(relationship: SchemaCatalogRelationship): string {
  const leftColumns = (relationship.left_columns ?? []).join(", ");
  const rightColumns = (relationship.right_columns ?? []).join(", ");
  return `${relationship.left_table || "left table"}(${leftColumns || "columns"}) = ${relationship.right_table || "right table"}(${rightColumns || "columns"})`;
}

function schemaCatalogRelationshipSource(relationship: SchemaCatalogRelationship): string {
  return stringValue(relationship.source);
}

function schemaCatalogColumnsForTable(tables: SchemaCatalogTable[], tableKey: string): string[] {
  const table = tables.find((item) => schemaCatalogTableKey(item) === tableKey);
  return (table?.columns ?? []).map((column) => stringValue(column.name)).filter(Boolean);
}

function schemaCatalogRelationshipMatchesDraft(relationship: SchemaCatalogRelationship, draft: SchemaJoinDraft): boolean {
  const leftTable = stringValue(relationship.left_table).toLowerCase();
  const rightTable = stringValue(relationship.right_table).toLowerCase();
  const leftColumns = (relationship.left_columns ?? []).map((column) => column.toLowerCase()).join(",");
  const rightColumns = (relationship.right_columns ?? []).map((column) => column.toLowerCase()).join(",");
  const draftLeftColumn = draft.leftColumn.toLowerCase();
  const draftRightColumn = draft.rightColumn.toLowerCase();
  return (
    leftTable === draft.leftTable &&
    rightTable === draft.rightTable &&
    leftColumns === draftLeftColumn &&
    rightColumns === draftRightColumn
  ) || (
    leftTable === draft.rightTable &&
    rightTable === draft.leftTable &&
    leftColumns === draftRightColumn &&
    rightColumns === draftLeftColumn
  );
}

function schemaCatalogManualRelationshipName(draft: SchemaJoinDraft): string {
  return `manual_${draft.leftTable}_${draft.leftColumn}_${draft.rightTable}_${draft.rightColumn}`.replace(/[^a-zA-Z0-9_]+/g, "_");
}

function emptySchemaJoinDraft(): SchemaJoinDraft {
  return { description: "", leftColumn: "", leftTable: "", rightColumn: "", rightTable: "" };
}

function splitCommaList(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function uniqueGroupPaths(paths: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  paths.map((path) => path.trim()).filter(Boolean).forEach((path) => {
    if (seen.has(path)) return;
    seen.add(path);
    result.push(path);
  });
  return result;
}

function catalogOwnerGroupPath(catalog: ConnectorSchemaCatalog): string {
  return catalog.owner_group_path || catalog.group_path;
}

function catalogSharedGroupPaths(catalog: ConnectorSchemaCatalog): string[] {
  if (Array.isArray(catalog.shared_group_paths)) return uniqueGroupPaths(catalog.shared_group_paths);
  const raw = catalog.catalog_json.shared_group_paths;
  return Array.isArray(raw) ? uniqueGroupPaths(raw.filter(isString)) : [];
}


function catalogScopeSummary(catalog: ConnectorSchemaCatalog): string {
  const owner = catalogOwnerGroupPath(catalog);
  const shared = catalogSharedGroupPaths(catalog);
  if (!shared.length) return owner;
  return `${owner} + ${shared.length} shared`;
}

function latestConnectorCatalog(catalogs: ConnectorSchemaCatalog[]): ConnectorSchemaCatalog | null {
  return [...catalogs].sort((left, right) => catalogTimestamp(right).localeCompare(catalogTimestamp(left)))[0] ?? null;
}

function catalogTimestamp(catalog: ConnectorSchemaCatalog): string {
  return catalog.updated_at ?? catalog.created_at ?? "";
}


function catalogAccessStateLabel(value: string): string {
  if (value === "approved") return "Enabled";
  if (value === "disabled") return "Disabled";
  return "Not enabled";
}

function catalogAccessStateDescription(value: string): string {
  if (value === "approved") return "Live DB can answer from this approved review.";
  if (value === "disabled") return "Live DB will not use this review.";
  return "Save changes as a draft, then enable access when the review is ready.";
}

function catalogAccessStateHint(value: string): string {
  if (value === "approved") return "Available to Live DB";
  if (value === "disabled") return "Disabled for Live DB";
  return "Review required";
}

function connectorWorkspaceTabDetail(tab: ConnectorWorkspaceTab, counts: ConnectorWorkspaceTabsProps["counts"]): string {
  if (tab === "connections") return `${counts.connections} saved`;
  if (tab === "schema_reviews") return `${counts.schemaReviews} prepared`;
  if (tab === "live_access") return `${counts.liveAccess} enabled`;
  return counts.diagnostics > 0 ? `${counts.diagnostics} issue${counts.diagnostics === 1 ? "" : "s"}` : "clear";
}

function connectorWorkspaceTabCount(tab: ConnectorWorkspaceTab, counts: ConnectorWorkspaceTabsProps["counts"]): string {
  if (tab === "connections") return counts.connections.toString();
  if (tab === "schema_reviews") return counts.schemaReviews.toString();
  if (tab === "live_access") return counts.liveAccess.toString();
  return counts.diagnostics.toString();
}

function profileEndpointSummary(profile: ConnectorProfile): string {
  const host = profile.connector_type === "postgres"
    ? stringConfig(profile.public_config.host)
    : parseSqlServerServer(stringConfig(profile.public_config.server)).host || stringConfig(profile.public_config.host);
  const database = stringConfig(profile.public_config.database);
  return [host, database].filter(Boolean).join(" / ") || "Endpoint redacted";
}

function profileHealthLabel(profile: ConnectorProfile): string {
  if (profile.last_test_status === "ok") return "Passed";
  if (profile.last_test_status === "failed") return "Failed";
  return "Not tested";
}

function profileHealthPillClass(profile: ConnectorProfile): string {
  if (profile.last_test_status === "ok") return "sv-pill sv-pill-success";
  if (profile.last_test_status === "failed") return "sv-pill border-error-red/30 bg-error-container text-error-red";
  return "sv-pill";
}

function catalogReviewLabel(value: string): string {
  if (value === "approved") return "Live access enabled";
  if (value === "reviewed") return "Reviewed";
  if (value === "disabled") return "Disabled";
  return "Needs review";
}

function catalogReviewPillClass(value: string): string {
  if (value === "approved") return "sv-pill sv-pill-success";
  if (value === "disabled") return "sv-pill sv-pill-warning";
  if (value === "reviewed") return "sv-pill";
  return "sv-pill sv-pill-warning";
}

function catalogAccessPillClass(value: string): string {
  if (value === "approved") return "sv-pill sv-pill-success";
  if (value === "disabled") return "sv-pill sv-pill-warning";
  return "sv-pill";
}

function connectorSchemaAccessSummary(catalog: ConnectorSchemaCatalog): string {
  const catalogJson = normalizeCatalogJson(catalog.catalog_json);
  const stats = schemaCatalogReviewStats(catalogJson);
  const relationships = catalogJson.relationships ?? [];
  return `${stats.allowedTables}/${stats.totalTables} tables, ${stats.allowedColumns}/${stats.totalColumns} columns, ${schemaCatalogAllowedRelationships(relationships)}/${relationships.length} joins`;
}

function isSchemaCatalogTable(value: unknown): value is SchemaCatalogTable {
  return typeof value === "object" && value !== null;
}

function isSchemaCatalogColumn(value: unknown): value is SchemaCatalogColumn {
  return typeof value === "object" && value !== null;
}

function isSchemaCatalogRelationship(value: unknown): value is SchemaCatalogRelationship {
  return typeof value === "object" && value !== null;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(stringValue).filter(Boolean).join(", ");
  return "";
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function catalogName(catalog: ConnectorSchemaCatalog, profile: ConnectorProfile): string {
  const name = catalog.catalog_json.name;
  return typeof name === "string" && name.trim() ? name.trim() : `${profile.name} Live DB access`;
}

function connectorTypeLabel(value: string): string {
  if (value === "sql_server") return "SQL Server";
  if (value === "postgres") return "PostgreSQL";
  if (value === "mysql") return "MySQL";
  if (value === "mariadb") return "MariaDB";
  if (value === "mongodb") return "MongoDB";
  if (value === "opensearch") return "OpenSearch";
  if (value === "elasticsearch") return "Elasticsearch";
  if (value === "redis") return "Redis";
  if (value === "cassandra") return "Cassandra";
  if (value === "fake") return "Fake connector";
  return value.replace("_", " ");
}

function defaultProfileDraft(): ConnectorProfileDraft {
  return defaultProfileDraftForType("sql_server");
}

function defaultProfileDraftForType(connectorType: ConnectorProfileDraft["connectorType"]): ConnectorProfileDraft {
  return {
    connectorType,
    name: "",
    server: "",
    port: connectorType === "postgres" ? "5432" : "1433",
    database: "",
    username: "",
    password: "",
    driver: connectorType === "sql_server" ? "ODBC Driver 18 for SQL Server" : "",
    customDriver: "",
    sslMode: connectorType === "postgres" ? "prefer" : "",
  };
}

function profilePublicConfig(draft: ConnectorProfileDraft): Record<string, string | number | boolean> {
  if (draft.connectorType === "postgres") {
    return {
      host: draft.server.trim(),
      port: Number(draft.port.trim() || 5432),
      database: draft.database.trim(),
      sslmode: draft.sslMode || "prefer",
    };
  }
  const driver = draft.driver === "custom" ? draft.customDriver.trim() : draft.driver.trim();
  return {
    server: draft.port.trim() ? `${draft.server.trim()},${draft.port.trim()}` : draft.server.trim(),
    database: draft.database.trim(),
    driver: driver || "ODBC Driver 18 for SQL Server",
    encrypt: true,
    trust_server_certificate: true,
  };
}

function profileUpdateRequest(draft: ConnectorProfileDraft): UpdateConnectorProfileRequest {
  const request: UpdateConnectorProfileRequest = {
    name: draft.name.trim(),
    public_config: profilePublicConfig(draft),
  };
  if (draft.username.trim() && draft.password) {
    request.secrets = {
      username: draft.username.trim(),
      password: draft.password,
    };
  }
  return request;
}

function profileDraftFromProfile(profile: ConnectorProfile): ConnectorProfileDraft {
  if (profile.connector_type === "postgres") {
    return {
      connectorType: "postgres",
      name: profile.name,
      server: stringConfig(profile.public_config.host),
      port: stringConfig(profile.public_config.port) || "5432",
      database: stringConfig(profile.public_config.database),
      username: "",
      password: "",
      driver: "",
      customDriver: "",
      sslMode: stringConfig(profile.public_config.sslmode) || "prefer",
    };
  }
  const parsedServer = parseSqlServerServer(stringConfig(profile.public_config.server));
  const driver = stringConfig(profile.public_config.driver) || "ODBC Driver 18 for SQL Server";
  const knownDriver = driver === "ODBC Driver 18 for SQL Server" || driver === "ODBC Driver 17 for SQL Server";
  return {
    connectorType: "sql_server",
    name: profile.name,
    server: parsedServer.host,
    port: parsedServer.port || "1433",
    database: stringConfig(profile.public_config.database),
    username: "",
    password: "",
    driver: knownDriver ? driver : "custom",
    customDriver: knownDriver ? "" : driver,
    sslMode: "",
  };
}

function parseSqlServerServer(value: string): { host: string; port: string } {
  const [host, port] = value.split(",", 2);
  return { host: host?.trim() ?? "", port: port?.trim() ?? "" };
}

function stringConfig(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

type Props = {
  currentUser: AuthUser;
  groupsLoading: boolean;
  variant?: FolderIngestPanelVariant;
  writableSpacePaths: string[];
};

type ConnectorWorkspaceTab = "connections" | "schema_reviews" | "live_access" | "diagnostics";
type ConnectorMetricTone = "neutral" | "success" | "warning" | "danger";
type ConnectorReviewTab = "summary" | "tables" | "joins" | "access" | "raw_schema";

type ConnectorProfileDraft = {
  connectorType: Extract<ConnectorType, "sql_server" | "postgres">;
  name: string;
  server: string;
  port: string;
  database: string;
  username: string;
  password: string;
  driver: string;
  customDriver: string;
  sslMode: string;
};

type ProfileValidationOptions = {
  credentialsRequired: boolean;
};


type ConnectorProfileSetupProps = {
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

type ConnectorOverviewProps = {
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

type ConnectorReviewTabsProps = {
  onChange: (tab: ConnectorReviewTab) => void;
  value: ConnectorReviewTab;
};

type ConnectorLiveAccessPanelProps = {
  catalogsByProfile: Record<string, ConnectorSchemaCatalog[]>;
  connectorProfiles: ConnectorProfile[];
  isError: boolean;
  isLoading: boolean;
  onOpenCatalog: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog) => void;
};

type ConnectorDiagnosticsPanelProps = {
  catalogsByProfile: Record<string, ConnectorSchemaCatalog[]>;
  connectorProfiles: ConnectorProfile[];
  isError: boolean;
  isLoading: boolean;
  onProfileAction: (action: "test" | "introspect", id: string) => void;
  pendingActionId: string | null;
  pendingActionType: "test" | "introspect" | null;
};


type ConnectorProfilePanelProps = {
  draft: ConnectorProfileDraft;
  error: string | null;
  isCreating: boolean;
  isLoading: boolean;
  mutationError: unknown;
  onChange: (patch: Partial<ConnectorProfileDraft>) => void;
  onProfileAction: (action: "test" | "introspect", id: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  pendingActionId: string | null;
  pendingActionType: "test" | "introspect" | null;
  profiles: ConnectorProfile[];
  showExisting?: boolean;
};

type ConnectorProfileEditorState = {
  profile: ConnectorProfile;
  draft: ConnectorProfileDraft;
};

type ConnectorProfileEditorProps = {
  draft: ConnectorProfileDraft;
  error: string | null;
  isSaving: boolean;
  mutationError: unknown;
  onCancel: () => void;
  onChange: (patch: Partial<ConnectorProfileDraft>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  profile: ConnectorProfile;
};

type ConnectorProfileCardsProps = {
  catalogsByProfile?: Record<string, ConnectorSchemaCatalog[]>;
  emptyMessage: string;
  isLoading: boolean;
  onCreateAiDraft: (profile: ConnectorProfile) => void;
  onDeleteProfile: (profile: ConnectorProfile) => void;
  onEditProfile: (profile: ConnectorProfile) => void;
  onOpenCatalog: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog) => void;
  onProfileAction: (action: "test" | "introspect", id: string) => void;
  pendingAiDraftProfileId: string | null;
  pendingDeleteProfileId: string | null;
  pendingActionId: string | null;
  pendingActionType: "test" | "introspect" | null;
  profiles: ConnectorProfile[];
  writableSpacePaths: string[];
};

type ConnectorRowActionsProps = {
  catalog: ConnectorSchemaCatalog | null;
  onCreateAiDraft: (profile: ConnectorProfile) => void;
  onDeleteProfile: (profile: ConnectorProfile) => void;
  onEditProfile: (profile: ConnectorProfile) => void;
  onOpenCatalog: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog) => void;
  onProfileAction: (action: "test" | "introspect", id: string) => void;
  pendingActionId: string | null;
  pendingActionType: "test" | "introspect" | null;
  pendingAiDraftProfileId: string | null;
  pendingDeleteProfileId: string | null;
  profile: ConnectorProfile;
  writableSpacePaths: string[];
};

type ConnectorCatalogReadinessProps = {
  catalogsByProfile: Record<string, ConnectorSchemaCatalog[]>;
  connectorProfiles: ConnectorProfile[];
  isError: boolean;
  isLoading: boolean;
  onCreateAiDraft: (profile: ConnectorProfile) => void;
  onOpenCatalog: (profile: ConnectorProfile, catalog: ConnectorSchemaCatalog) => void;
  pendingAiDraftProfileId: string | null;
  writableSpacePaths: string[];
};

type ConnectorCatalogEditorState = {
  profile: ConnectorProfile;
  catalog: ConnectorSchemaCatalog;
};

type AiDraftProgress = {
  catalogId: string;
  completed: number;
  currentTable: string | null;
  failed: number;
  total: number;
};

type ConnectorSchemaSnapshotViewerState = {
  profile: ConnectorProfile | null;
  snapshot: ConnectorSchemaSnapshot;
};

type SchemaSnapshotModalProps = {
  onClose: () => void;
  viewer: ConnectorSchemaSnapshotViewerState | null;
};

type SchemaSnapshotMetricProps = {
  label: string;
  value: string;
};

type SchemaReviewMetricProps = {
  label: string;
  value: string;
};

type SchemaSnapshotTableSummary = {
  key: string;
  columns: SchemaSnapshotColumnSummary[];
  primaryKeys: string[];
  foreignKeys: SchemaSnapshotForeignKeySummary[];
  indexes: SchemaSnapshotIndexSummary[];
  estimatedRowCount: number | null;
};

type SchemaSnapshotColumnSummary = {
  name: string;
  type: string;
};

type SchemaSnapshotForeignKeySummary = {
  name: string;
  referencedTable: string;
};

type SchemaSnapshotIndexSummary = {
  name: string;
};

type ConnectorCatalogEditorProps = {
  catalog: ConnectorSchemaCatalog;
  clearanceOptions: ClearanceLevel[];
  isSaving: boolean;
  mutationError: unknown;
  onClose: () => void;
  onContinueAiEnrichment: () => void;
  onSave: (request: UpdateConnectorSchemaCatalogRequest) => void;
  profile: ConnectorProfile;
  writableSpacePaths: string[];
};

type SchemaCatalogJson = Record<string, unknown> & {
  name?: string;
  tables?: SchemaCatalogTable[];
  relationships?: SchemaCatalogRelationship[];
  business_rules?: string[];
  ai_enrichment?: unknown;
};

type SchemaCatalogTable = Record<string, unknown> & {
  key?: string;
  schema?: string;
  name?: string;
  allowed?: boolean;
  sensitive?: boolean;
  description?: string;
  synonyms?: string[];
  columns?: SchemaCatalogColumn[];
};

type SchemaCatalogColumn = Record<string, unknown> & {
  name?: string;
  data_type?: string;
  allowed?: boolean;
  sensitive?: boolean;
  description?: string;
  synonyms?: string[];
};

type SchemaCatalogRelationship = Record<string, unknown> & {
  name?: string;
  left_table?: string;
  left_columns?: string[];
  right_table?: string;
  right_columns?: string[];
  allowed?: boolean;
  description?: string;
  source?: string;
};

type SchemaJoinDraft = {
  description: string;
  leftColumn: string;
  leftTable: string;
  rightColumn: string;
  rightTable: string;
};

type SchemaCatalogFilter = "all" | "included" | "excluded" | "sensitive" | "missing";

type SchemaCatalogReviewStats = {
  allowedColumns: number;
  allowedTables: number;
  excludedTables: number;
  missingDescriptions: number;
  sensitiveColumns: number;
  totalColumns: number;
  totalTables: number;
};


type ScheduleListPanelProps = {
  emptyMessage: string;
  isError: boolean;
  isLoading: boolean;
  loadError: string;
  onAction: (action: "pause" | "resume" | "cancel", id: string) => void;
  pendingActionId: string | null;
  pendingActionPending: boolean;
  schedules: FolderSchedule[];
  title: string;
};

type SelectProps = {
  emptyLabel?: string;
  helper?: string;
  label: string;
  onChange: (value: string) => void;
  optionLabels?: Record<string, string>;
  options: string[];
  value: string;
};

type ClearanceSelectProps = {
  onChange: (value: ClearanceLevel) => void;
  options: ClearanceLevel[];
  value: ClearanceLevel;
};

type ScheduleCardProps = {
  onAction: (action: "pause" | "resume" | "cancel") => void;
  pendingAction: boolean;
  schedule: FolderSchedule;
};

type FolderSnapshotReviewProps = {
  label: string;
  onClear: () => void;
  onRemove: (file: File) => void;
  selection: ReturnType<typeof summarizeFolderFiles>;
};

type FolderSnapshotFileRowProps = {
  entry: FolderFileEntry;
  onRemove: (file: File) => void;
};

type IconActionProps = {
  disabled: boolean;
  icon: JSX.Element;
  label: string;
  onClick: () => void;
};
