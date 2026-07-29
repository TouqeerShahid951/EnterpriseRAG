import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FolderPlus,
  Upload,
} from "lucide-react";

import { adminApi, documentsApi, ingestJobsApi } from "@/lib/api/contracts";
import {
  canManageSpaces,
  canUploadToSpace,
  canViewSpaceMetadata,
  isGlobalAdmin,
} from "@/lib/auth/authz";
import { useToast } from "@/components/feedback/ToastProvider";
import { InlineMessage } from "@/components/layout/Common";
import { PrudentiaWorkspace } from "@/components/layout/PrudentiaWorkspace";
import { Modal } from "@/components/layout/Modal";
import { DocumentInspector } from "@/features/documents/components/library/DocumentInspector";
import { ActiveDocumentsTab, FolderTab, TrashTab } from "@/features/documents/components/library/DocumentTabs";
import { KnowledgeSpacesOverview } from "@/features/documents/components/library/KnowledgeSpacesOverview";
import { SpacePanel, type SpacePanelState } from "@/features/documents/components/library/SpacePanel";
import { useDocumentActions } from "@/features/documents/state/useDocumentActions";
import {
  buildSpaceOverviewRows,
  createSpaceDraft,
  documentsForView,
  explorerTabKey,
  initialDocumentIngestFilterFromUrl,
  initialDocumentStateFilterFromUrl,
  initialExplorerTabFromUrl,
  initialStringParamFromUrl,
  mergeSpaceOptions,
  spaceFromPath,
  syncExplorerUrl,
  type DocumentIngestFilter,
  type DocumentStateFilter,
  type DocumentsView,
  type ExplorerTab,
  type SpaceDraft,
} from "@/features/documents/utils/documentPageUtils";
import type { RouteId } from "@/routes/routes";
import type { User as AuthUser } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";
import {
  buildGroupPath,
  flattenGroups,
  userSpacesFromPaths,
  type GroupOption,
} from "@/lib/utils/groups";

export function PrudentiaDocumentsPage({ onLogout, onNavigate, user, view = "spaces" }: Props) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const isSpaceManager = canManageSpaces(user);
  const canLoadSpaceDirectory = isSpaceManager || canViewSpaceMetadata(user);
  const [activeTab, setActiveTab] = useState<ExplorerTab>(() => initialExplorerTabFromUrl());
  const [documentSearch, setDocumentSearch] = useState(() => initialStringParamFromUrl("doc_q"));
  const [statusFilter, setStatusFilter] = useState<DocumentStateFilter>(() => initialDocumentStateFilterFromUrl());
  const [ingestFilter, setIngestFilter] = useState<DocumentIngestFilter>(() => initialDocumentIngestFilterFromUrl());
  const [spaceFilter, setSpaceFilter] = useState(() => initialStringParamFromUrl("space"));
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(() => initialStringParamFromUrl("doc") || null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [spacePanel, setSpacePanel] = useState<SpacePanelState>(null);
  const [spaceDraft, setSpaceDraft] = useState<SpaceDraft>(() => createSpaceDraft());
  const [deletingSpacePath, setDeletingSpacePath] = useState<string | null>(null);
  const {
    cancelGraphEnrichment,
    cancellingGraphTaskId,
    enrichGraph,
    enrichingDocumentId,
    pendingIds,
    performBulkAction,
    performDocumentAction,
    transferDocumentOwner,
    unshareDocument,
    updateDocumentClearance,
    updateDocumentShares,
    updateDocumentTopics,
  } = useDocumentActions({
    onDocumentRemoved: () => setSelectedDocumentId(null),
    onSelectionCleared: () => setSelectedIds(new Set()),
  });

  const activeDocsQuery = useQuery({ queryKey: ["documents", "list", "active"], queryFn: () => documentsApi.list({ state: "active" }), enabled: view !== "trash", staleTime: 5000, retry: false });
  const deletedDocsQuery = useQuery({ queryKey: ["documents", "list", "deleted"], queryFn: () => documentsApi.list({ state: "deleted" }), enabled: view === "trash", staleTime: 15000, retry: false });
  const overviewQuery = useQuery({
    queryKey: ["documents", "overview"],
    queryFn: documentsApi.overview,
    enabled: view === "spaces",
    refetchInterval: (query) => query.state.data?.processing_current ? 3000 : 15000,
    staleTime: 3000,
    retry: false,
  });
  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, retry: false, enabled: canLoadSpaceDirectory });

  const activeDocuments = activeDocsQuery.data?.items ?? [];
  const deletedDocuments = deletedDocsQuery.data?.items ?? [];
  const allKnownDocuments = useMemo(() => [...activeDocuments, ...deletedDocuments], [activeDocuments, deletedDocuments]);
  const hasGraphEligibleDocuments = view !== "trash" && activeDocuments.some((document) => document.ingest_status === "complete" && document.doc_type !== "abbreviation_glossary");
  const graphStatusQuery = useQuery({
    queryKey: ["ingest-jobs", "graphrag-status", "documents"],
    queryFn: ingestJobsApi.graphragStatus,
    enabled: hasGraphEligibleDocuments,
    refetchInterval: hasGraphEligibleDocuments ? 5000 : false,
    staleTime: 3000,
    retry: false,
  });
  const graphStatusError = graphStatusQuery.isError ? errorMessage(graphStatusQuery.error, "Unable to load graph enrichment status.") : null;
  const groups = groupsQuery.data?.items ?? [];
  const spaceOptions = useMemo(
    () => (canLoadSpaceDirectory ? flattenGroups(groups) : userSpacesFromPaths(user.group_paths)),
    [canLoadSpaceDirectory, groups, user.group_paths],
  );
  const documentSpaceOptions = useMemo(() => mergeSpaceOptions(spaceOptions, allKnownDocuments, spaceFilter), [allKnownDocuments, spaceFilter, spaceOptions]);
  const canUploadDocuments = view === "spaces"
    ? spaceOptions.some((space) => canUploadToSpace(user, space.path))
    : canUploadToSpace(user, user.group_paths[0] ?? "/") || isGlobalAdmin(user);
  const visibleActiveTab = activeTab;
  const selectedSpacePath = visibleActiveTab.kind === "space" ? visibleActiveTab.path : "";
  const selectedSpace = selectedSpacePath ? spaceOptions.find((space) => space.path === selectedSpacePath) ?? null : null;
  const canUploadToSelectedSpace = Boolean(selectedSpacePath && canUploadToSpace(user, selectedSpacePath));
  const selectedDocument = selectedDocumentId ? allKnownDocuments.find((doc) => doc.id === selectedDocumentId) ?? null : null;
  const hasSelectedDocument = Boolean(selectedDocument);
  const activeTabKey = explorerTabKey(activeTab);
  const isLoadingDirectory = canLoadSpaceDirectory && groupsQuery.isLoading;

  useEffect(() => {
    syncExplorerUrl({ activeTab, documentSearch, ingestFilter, selectedDocumentId, spaceFilter, statusFilter, view });
  }, [activeTab, documentSearch, ingestFilter, selectedDocumentId, spaceFilter, statusFilter, view]);

  useEffect(() => {
    setSelectedIds(new Set());
  }, [activeTabKey, view]);

  useEffect(() => {
    if (selectedDocumentId && !activeDocsQuery.isLoading && !deletedDocsQuery.isLoading && !allKnownDocuments.some((doc) => doc.id === selectedDocumentId)) {
      setSelectedDocumentId(null);
    }
  }, [activeDocsQuery.isLoading, allKnownDocuments, deletedDocsQuery.isLoading, selectedDocumentId]);

  const createSpaceMutation = useMutation({
    mutationFn: (draft: SpaceDraft) =>
      adminApi.createGroup({
        path: draft.path.trim(),
        name: draft.name.trim(),
      }),
    onSuccess: (space) => {
      openSpace(space.path);
      setSpacePanel(null);
      void queryClient.invalidateQueries({ queryKey: ["admin", "groups"] });
      notify({ title: "Knowledge Space created", description: space.path, tone: "success" });
    },
  });

  const updateSpaceMutation = useMutation({
    mutationFn: (draft: SpaceDraft) =>
      adminApi.updateGroup({
        path: draft.path.trim(),
        name: draft.name.trim(),
      }),
    onSuccess: (space) => {
      openSpace(space.path);
      setSpacePanel(null);
      void queryClient.invalidateQueries({ queryKey: ["admin", "groups"] });
      notify({ title: "Knowledge Space updated", description: space.path, tone: "success" });
    },
  });

  const deleteSpaceMutation = useMutation({
    mutationFn: (path: string) => adminApi.deleteGroup({ path }),
    onMutate: (path) => setDeletingSpacePath(path),
    onSuccess: (_, path) => {
      if (activeTab.kind === "space" && activeTab.path === path) activateTab({ kind: "overview" });
      setSpacePanel(null);
      void queryClient.invalidateQueries({ queryKey: ["admin", "groups"] });
      notify({ title: "Knowledge Space deleted", description: path, tone: "success" });
    },
    onError: (error) => notify({
      title: "Knowledge Space delete failed",
      description: errorMessage(error, "Unable to delete Knowledge Space."),
      tone: "error",
    }),
    onSettled: () => setDeletingSpacePath(null),
  });

  function activateTab(tab: ExplorerTab) {
    const nextKey = explorerTabKey(tab);
    if (nextKey !== activeTabKey) {
      setSelectedDocumentId(null);
    }
    setActiveTab(tab);
  }

  function openSpace(path: string) {
    activateTab({ kind: "space", path });
  }

  function resetSpaceMutations() {
    createSpaceMutation.reset();
    updateSpaceMutation.reset();
    deleteSpaceMutation.reset();
  }

  function openCreateSpace() {
    resetSpaceMutations();
    setSpaceDraft(createSpaceDraft());
    setSpacePanel({ kind: "create-space" });
  }

  function openEditSpace(space: GroupOption) {
    resetSpaceMutations();
    setSpaceDraft({
      name: space.name,
      path: space.path,
      pathTouched: true,
    });
    setSpacePanel({ kind: "edit-space", space });
  }

  function closeSpacePanel() {
    resetSpaceMutations();
    setSpacePanel(null);
  }

  function updateSpaceName(name: string) {
    setSpaceDraft((draft) => ({
      ...draft,
      name,
      path: draft.pathTouched ? draft.path : buildGroupPath("", name),
    }));
  }

  function submitSpaceForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!spacePanel) return;
    if (spacePanel.kind === "create-space") {
      createSpaceMutation.mutate(spaceDraft);
      return;
    }
    updateSpaceMutation.mutate(spaceDraft);
  }

  function deleteSpace(space: GroupOption) {
    resetSpaceMutations();
    if (window.confirm(`Delete Knowledge Space "${space.name}" (${space.path})? This only works for spaces with no documents or assigned users.`)) {
      deleteSpaceMutation.mutate(space.path);
    }
  }

  const currentTabDocuments = documentsForView(view, visibleActiveTab, activeDocuments, deletedDocuments, documentSearch, statusFilter, ingestFilter, spaceFilter);
  const spaceOverviewRows = useMemo(() => buildSpaceOverviewRows(spaceOptions, overviewQuery.data?.spaces ?? []), [overviewQuery.data?.spaces, spaceOptions]);
  const selectedDocuments = currentTabDocuments.filter((doc) => selectedIds.has(doc.id));
  const activeRoute: RouteId = view === "documents" ? "documents" : view === "trash" ? "document-trash" : "knowledge-spaces";
  const pageTitle = view === "documents" ? "Documents" : view === "trash" ? "Trash" : "Knowledge Spaces";
  const pageSubtitle = view === "documents"
    ? "Search and manage active documents across every Knowledge Space visible to you."
    : view === "trash"
      ? "Restore soft-deleted documents or permanently delete them when your role permits."
      : "Use the overview to monitor spaces, document volume, and ingestion attention across the corpus.";

  return (
    <PrudentiaWorkspace activeRoute={activeRoute} onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page" id="main-content">
        <div className="sv-page-inner sv-page-inner-workbench max-w-none">
          <header className="sv-page-header knowledge-page-header">
            <div>
              <p className="sv-eyebrow">Document Library</p>
              <h1 className="sv-page-title">{pageTitle}</h1>
              <p className="sv-page-subtitle">{pageSubtitle}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {view === "spaces" && isSpaceManager ? (
                <button type="button" onClick={() => openCreateSpace()} className="sv-action-secondary">
                  <FolderPlus size={16} />
                  New Space
                </button>
              ) : null}
              {view !== "trash" && canUploadDocuments ? (
                <button type="button" onClick={() => onNavigate("upload")} className="sv-action-primary">
                  <Upload size={16} />
                  Add Files
                </button>
              ) : null}
            </div>
          </header>

          {groupsQuery.isError && canLoadSpaceDirectory ? <InlineMessage tone="error">{errorMessage(groupsQuery.error, "Unable to load Knowledge Spaces.")}</InlineMessage> : null}
          {overviewQuery.isError && view === "spaces" ? <InlineMessage tone="error">{errorMessage(overviewQuery.error, "Unable to load the document overview.")}</InlineMessage> : null}
          {activeDocsQuery.isError && view !== "trash" ? <InlineMessage tone="error">{errorMessage(activeDocsQuery.error, "Unable to load documents.")}</InlineMessage> : null}
          {deletedDocsQuery.isError && view === "trash" ? <InlineMessage tone="warning">{errorMessage(deletedDocsQuery.error, "Unable to load Trash.")}</InlineMessage> : null}
          {deleteSpaceMutation.isError ? <InlineMessage tone="error">{errorMessage(deleteSpaceMutation.error, "Unable to delete Knowledge Space.")}</InlineMessage> : null}

          {view === "spaces" ? (
            <section className={hasSelectedDocument ? "knowledge-explorer-shell knowledge-explorer-shell-with-inspector" : "knowledge-explorer-shell"}>
              <section className="knowledge-explorer-main">
                <div className="knowledge-explorer-panel">
                  {visibleActiveTab.kind === "space" ? (
                    <FolderTab
                      bulkSelection={selectedIds}
                      canUploadDocuments={canUploadToSelectedSpace}
                      cancellingGraphTaskId={cancellingGraphTaskId}
                      documents={currentTabDocuments}
                      enrichingDocumentId={enrichingDocumentId}
                      graphStatus={graphStatusQuery.data}
                      graphStatusError={graphStatusError}
                      ingestFilter={ingestFilter}
                      isLoading={activeDocsQuery.isLoading}
                      onBackToOverview={() => activateTab({ kind: "overview" })}
                      onBulkAction={(action) => performBulkAction(action, selectedDocuments)}
                      onDocumentAction={performDocumentAction}
                      onCancelGraph={cancelGraphEnrichment}
                      onEnrichGraph={enrichGraph}
                      onNavigate={onNavigate}
                      onSearchChange={setDocumentSearch}
                      onSelectDocument={setSelectedDocumentId}
                      onSelectionChange={setSelectedIds}
                      pendingIds={pendingIds}
                      search={documentSearch}
                      selectedDocumentId={selectedDocumentId}
                      setIngestFilter={setIngestFilter}
                      setStatusFilter={setStatusFilter}
                      space={selectedSpace ?? spaceFromPath(visibleActiveTab.path)}
                      statusFilter={statusFilter}
                      user={user}
                    />
                  ) : (
                    <KnowledgeSpacesOverview
                      canCreateSpace={isSpaceManager}
                      canManageSpaces={isSpaceManager}
                      canOpenSpaces
                      deletingSpacePath={deletingSpacePath}
                      isLoading={overviewQuery.isLoading || overviewQuery.isError || isLoadingDirectory}
                      onCreateSpace={openCreateSpace}
                      onDeleteSpace={deleteSpace}
                      onEditSpace={openEditSpace}
                      onOpenSpace={openSpace}
                      onShowJobs={() => onNavigate("ingestion-jobs")}
                      onShowTrash={() => onNavigate("document-trash")}
                      overview={overviewQuery.data ?? null}
                      rows={spaceOverviewRows}
                    />
                  )}
                </div>
              </section>

              {hasSelectedDocument ? (
                <DocumentInspector
                  document={selectedDocument}
                  onClose={() => setSelectedDocumentId(null)}
                  onClearanceChange={updateDocumentClearance}
                  onDocumentAction={performDocumentAction}
                  onOwnerChange={transferDocumentOwner}
                  onSharesChange={updateDocumentShares}
                  onTopicsChange={updateDocumentTopics}
                  onUnshare={unshareDocument}
                  pending={pendingIds.has(selectedDocument!.id)}
                  spaceOptions={documentSpaceOptions}
                  user={user}
                />
              ) : null}
            </section>
          ) : (
            <section className={hasSelectedDocument ? "knowledge-document-workspace knowledge-document-workspace-with-inspector" : "knowledge-document-workspace"}>
              <section className="knowledge-explorer-main">
                <div className="knowledge-explorer-panel">
                  {view === "documents" ? (
                    <ActiveDocumentsTab
                      bulkSelection={selectedIds}
                      canUploadDocuments={canUploadDocuments}
                      cancellingGraphTaskId={cancellingGraphTaskId}
                      documents={currentTabDocuments}
                      enrichingDocumentId={enrichingDocumentId}
                      graphStatus={graphStatusQuery.data}
                      graphStatusError={graphStatusError}
                      ingestFilter={ingestFilter}
                      isLoading={activeDocsQuery.isLoading}
                      onBulkAction={(action) => performBulkAction(action, selectedDocuments)}
                      onDocumentAction={performDocumentAction}
                      onCancelGraph={cancelGraphEnrichment}
                      onEnrichGraph={enrichGraph}
                      onNavigate={onNavigate}
                      onSearchChange={setDocumentSearch}
                      onSelectDocument={setSelectedDocumentId}
                      onSelectionChange={setSelectedIds}
                      pendingIds={pendingIds}
                      search={documentSearch}
                      selectedDocumentId={selectedDocumentId}
                      setSpaceFilter={setSpaceFilter}
                      setIngestFilter={setIngestFilter}
                      setStatusFilter={setStatusFilter}
                      spaceFilter={spaceFilter}
                      spaceOptions={documentSpaceOptions}
                      statusFilter={statusFilter}
                      user={user}
                    />
                  ) : (
                    <TrashTab
                      bulkSelection={selectedIds}
                      documents={currentTabDocuments}
                      ingestFilter={ingestFilter}
                      isLoading={deletedDocsQuery.isLoading}
                      onBulkAction={(action) => performBulkAction(action, selectedDocuments)}
                      onDocumentAction={performDocumentAction}
                      onSearchChange={setDocumentSearch}
                      onSelectDocument={setSelectedDocumentId}
                      onSelectionChange={setSelectedIds}
                      pendingIds={pendingIds}
                      search={documentSearch}
                      selectedDocumentId={selectedDocumentId}
                      setSpaceFilter={setSpaceFilter}
                      setIngestFilter={setIngestFilter}
                      setStatusFilter={setStatusFilter}
                      spaceFilter={spaceFilter}
                      spaceOptions={documentSpaceOptions}
                      statusFilter={statusFilter}
                      user={user}
                    />
                  )}
                </div>
              </section>
              {hasSelectedDocument ? (
                <DocumentInspector
                  document={selectedDocument}
                  onClose={() => setSelectedDocumentId(null)}
                  onClearanceChange={updateDocumentClearance}
                  onDocumentAction={performDocumentAction}
                  onOwnerChange={transferDocumentOwner}
                  onSharesChange={updateDocumentShares}
                  onTopicsChange={updateDocumentTopics}
                  onUnshare={unshareDocument}
                  pending={pendingIds.has(selectedDocument!.id)}
                  spaceOptions={documentSpaceOptions}
                  user={user}
                />
              ) : null}
            </section>
          )}
        </div>

        {view === "spaces" ? <Modal
          description={spacePanel?.kind === "create-space" ? "Create a retrieval boundary for documents and answers." : "Update the display name for this Knowledge Space."}
          icon={<FolderPlus size={18} />}
          onClose={closeSpacePanel}
          open={Boolean(spacePanel)}
          size="md"
          title={spacePanel?.kind === "create-space" ? "Create Knowledge Space" : "Edit Knowledge Space"}
        >
          {spacePanel ? (
            <SpacePanel
              draft={spaceDraft}
              isCreate={spacePanel.kind === "create-space"}
              isPending={createSpaceMutation.isPending || updateSpaceMutation.isPending}
              mutationError={
                spacePanel.kind === "create-space"
                  ? createSpaceMutation.isError
                    ? createSpaceMutation.error
                    : null
                  : updateSpaceMutation.isError
                    ? updateSpaceMutation.error
                    : null
              }
              onChange={setSpaceDraft}
              onNameChange={updateSpaceName}
              onSubmit={submitSpaceForm}
              pathExists={new Set(spaceOptions.map((space) => space.path)).has(spaceDraft.path.trim())}
            />
          ) : null}
        </Modal> : null}
      </main>
    </PrudentiaWorkspace>
  );
}

type Props = { onLogout: () => void; onNavigate: (route: RouteId) => void; user: AuthUser; view?: DocumentsView };
