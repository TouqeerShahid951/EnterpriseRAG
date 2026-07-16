import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import { connectorApi, folderIngestApi, type UpdateConnectorSchemaCatalogRequest } from "@/lib/api/contracts";
import { clearanceLevelsAssignableBy } from "@/lib/auth/authz";
import { useToast } from "@/components/feedback/ToastProvider";
import { FolderScheduleWorkspace } from "@/features/connectors/components/folder-schedules/FolderScheduleWorkspace";
import {
  buildLocalFolderScheduleRequest,
  buildSnapshotScheduleRequest,
  defaultFolderScheduleDraftForVariant,
  isScheduleVisibleForPanelVariant,
  summarizeFolderFiles,
  type FolderIngestPanelVariant,
  type FolderScheduleDraft,
} from "@/features/ingestion/state/folderIngest";
import type { ClearanceLevel, ConnectorProfile, ConnectorSchemaCatalog, ConnectorSchemaSnapshot, ConnectorTestResponse, User as AuthUser } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";
import {
  aiDraftProgressFromCatalog,
  connectorTypeLabel,
  defaultProfileDraft,
  latestConnectorCatalog,
  profileDraftFromProfile,
  profilePublicConfig,
  profileUpdateRequest,
  schemaCatalogAiEnrichmentError,
  schemaCatalogAiEnrichmentStatus,
  schemaCatalogPendingTableKeys,
  schemaSnapshotSummary,
  validateDraft,
  validateProfileDraft,
  type AiDraftProgress,
  type ConnectorCatalogEditorState,
  type ConnectorProfileDraft,
  type ConnectorProfileEditorState,
  type ConnectorSchemaSnapshotViewerState,
  type ConnectorWorkspaceTab,
} from "@/features/connectors/utils/connectorPanelUtils";
import { ConnectorManagementModals } from "@/features/connectors/components/connector-workspace/ConnectorManagementModals";
import { ConnectorOverview } from "@/features/connectors/components/connector-workspace/ConnectorWorkspace";


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
  const scheduleLoadError = "Unable to load folder schedules.";

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
        <FolderScheduleWorkspace
          actionPending={actionMutation.isPending}
          clearanceOptions={clearanceOptions}
          createError={createMutation.error}
          createFailed={createMutation.isError}
          draft={draft}
          formError={formError}
          groupsLoading={groupsLoading}
          inputResetKey={folderInputResetKey}
          isSubmitting={isSubmitting}
          pendingActionId={actionMutation.variables?.id ?? null}
          scheduleLoadError={scheduleLoadError}
          schedules={visibleSchedules}
          schedulesFailed={schedulesQuery.isError}
          schedulesLoading={schedulesQuery.isLoading}
          selectedFiles={selectedFiles}
          selection={selection}
          submittingLabel={submittingLabel}
          submitLabel={submitLabel}
          writableSpacePaths={writableSpacePaths}
          onClearSnapshot={clearFolderSnapshot}
          onDraftChange={patchDraft}
          onFileSelection={handleFolderSnapshotSelection}
          onRemoveFile={removeFolderSnapshotFile}
          onScheduleAction={(action, id) => actionMutation.mutate({ action, id })}
          onSubmit={handleSubmit}
        />
      )}

      {isConnectorPanel ? (
        <ConnectorManagementModals
          createError={createProfileMutation.error}
          creating={createProfileMutation.isPending}
          deletePending={deleteProfileMutation.isPending}
          deleteProfile={deleteProfileConfirm}
          pendingActionId={profileActionMutation.isPending ? profileActionMutation.variables?.id ?? null : null}
          pendingActionType={profileActionMutation.isPending ? profileActionMutation.variables?.action ?? null : null}
          profileDraft={profileDraft}
          profileError={profileError}
          profilesLoading={profilesQuery.isLoading}
          schemaViewer={schemaViewer}
          setupOpen={connectorSetupOpen}
          onCloseDelete={() => setDeleteProfileConfirm(null)}
          onCloseSchemaViewer={() => setSchemaViewer(null)}
          onCloseSetup={closeConnectorSetup}
          onConfirmDelete={confirmDeleteProfile}
          onProfileAction={(action, id) => profileActionMutation.mutate({ action, id })}
          onProfileChange={(patch) => setProfileDraft((current) => ({ ...current, ...patch }))}
          onProfileSubmit={handleProfileSubmit}
        />
      ) : null}
    </section>
  );
}

type Props = {
  currentUser: AuthUser;
  groupsLoading: boolean;
  variant?: FolderIngestPanelVariant;
  writableSpacePaths: string[];
};
