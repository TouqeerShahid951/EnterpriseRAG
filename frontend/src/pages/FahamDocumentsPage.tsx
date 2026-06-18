import { useEffect, useMemo, useState, type CSSProperties, type Dispatch, type FormEvent, type SetStateAction } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArchiveRestore,
  ChevronDown,
  ChevronRight,
  Download,
  Edit3,
  Eye,
  FileText,
  Folder,
  FolderOpen,
  FolderPlus,
  Plus,
  RotateCw,
  Search,
  ShieldAlert,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import { adminApi, documentsApi } from "../api/contracts";
import {
  canManageSpaces,
  canUploadToSpace,
  canViewSpaceMetadata,
  canWriteDocument,
  clearanceLevelDescription,
  clearanceLevelLabel,
  clearanceLevelsAssignableBy,
  defaultClearanceLevel,
  isGlobalAdmin,
  isGroupPathInUserScope,
} from "../authz";
import { useToast } from "../components/feedback/ToastProvider";
import { Fact, InlineMessage, Skeleton } from "../components/layout/Common";
import { FahamWorkspace } from "../components/layout/FahamWorkspace";
import { Modal } from "../components/layout/Modal";
import type { RouteId } from "../routes";
import { formatStageProgress, isUploadTerminalStatus } from "../state/uploadJobProgress";
import type { ClearanceLevel, Document, DocumentIngestStatus, User as AuthUser, VersionChainResponse } from "../types/api";
import type { UploadBatchItemView } from "../types/chat";
import { errorMessage, formatDate, formatDateTime } from "../utils/format";
import {
  buildGroupPath,
  flattenGroups,
  groupPathIssue,
  isDocumentInSpace,
  userSpacesFromPaths,
  type GroupOption,
} from "../utils/groups";

const SPACE_TABS_STORAGE_KEY = "agenticrag.knowledge-space-tabs.v1";

export function FahamDocumentsPage({ onLogout, onNavigate, uploadJobs = [], user, view = "spaces" }: Props) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const isSpaceManager = canManageSpaces(user);
  const canLoadSpaceDirectory = isSpaceManager || canViewSpaceMetadata(user);
  const [activeTab, setActiveTab] = useState<ExplorerTab>(() => initialExplorerTabFromUrl());
  const [previousTabKey, setPreviousTabKey] = useState("overview");
  const [openSpaceTabs, setOpenSpaceTabs] = useState<string[]>(() => initialOpenSpaceTabsFromSession());
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(() => new Set());
  const [spaceSearch, setSpaceSearch] = useState("");
  const [documentSearch, setDocumentSearch] = useState(() => initialStringParamFromUrl("doc_q"));
  const [statusFilter, setStatusFilter] = useState<DocumentStateFilter>(() => initialDocumentStateFilterFromUrl());
  const [ingestFilter, setIngestFilter] = useState<DocumentIngestFilter>(() => initialDocumentIngestFilterFromUrl());
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(() => initialStringParamFromUrl("doc") || null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [pendingIds, setPendingIds] = useState<Set<string>>(() => new Set());
  const [spacePanel, setSpacePanel] = useState<SpacePanelState>(null);
  const [spaceDraft, setSpaceDraft] = useState<SpaceDraft>(() => createSpaceDraft());
  const [deletingSpacePath, setDeletingSpacePath] = useState<string | null>(null);

  const activeDocsQuery = useQuery({ queryKey: ["documents", "list", "active"], queryFn: () => documentsApi.list({ state: "active" }), enabled: view !== "trash", staleTime: 5000, retry: false });
  const deletedDocsQuery = useQuery({ queryKey: ["documents", "list", "deleted"], queryFn: () => documentsApi.list({ state: "deleted" }), enabled: view === "trash", staleTime: 15000, retry: false });
  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, retry: false, enabled: view === "spaces" && canLoadSpaceDirectory });

  const activeDocuments = activeDocsQuery.data?.items ?? [];
  const deletedDocuments = deletedDocsQuery.data?.items ?? [];
  const allKnownDocuments = useMemo(() => [...activeDocuments, ...deletedDocuments], [activeDocuments, deletedDocuments]);
  const groups = groupsQuery.data?.items ?? [];
  const spaceOptions = useMemo(
    () => (canLoadSpaceDirectory ? flattenGroups(groups) : userSpacesFromPaths(user.group_paths)),
    [canLoadSpaceDirectory, groups, user.group_paths],
  );
  const canUploadDocuments = view === "spaces"
    ? spaceOptions.some((space) => canUploadToSpace(user, space.path))
    : canUploadToSpace(user, user.group_paths[0] ?? "/") || isGlobalAdmin(user);
  const selectedSpacePath = activeTab.kind === "space" ? activeTab.path : "";
  const selectedSpace = selectedSpacePath ? spaceOptions.find((space) => space.path === selectedSpacePath) ?? null : null;
  const canUploadToSelectedSpace = Boolean(selectedSpacePath && canUploadToSpace(user, selectedSpacePath));
  const selectedDocument = selectedDocumentId ? allKnownDocuments.find((doc) => doc.id === selectedDocumentId) ?? null : null;
  const hasSelectedDocument = Boolean(selectedDocument);
  const activeTabKey = explorerTabKey(activeTab);
  const activeFolderTabs = openSpaceTabs
    .map((path) => spaceOptions.find((space) => space.path === path) ?? spaceFromPath(path))
    .filter(Boolean);
  const isLoadingDirectory = canLoadSpaceDirectory && groupsQuery.isLoading;

  useEffect(() => {
    const urlSpace = initialStringParamFromUrl("space");
    if (urlSpace && activeTab.kind === "space") {
      setOpenSpaceTabs((current) => (current.includes(urlSpace) ? current : [...current, urlSpace]));
    }
  }, []);

  useEffect(() => {
    sessionStorage.setItem(SPACE_TABS_STORAGE_KEY, JSON.stringify(openSpaceTabs));
  }, [openSpaceTabs]);

  useEffect(() => {
    const roots = rootSpaces(spaceOptions).map((space) => space.path);
    const scoped = user.group_paths.filter(Boolean);
    setExpandedPaths((current) => {
      const next = new Set([...current, ...roots, ...scoped]);
      if (next.size === current.size && [...next].every((path) => current.has(path))) return current;
      return next;
    });
  }, [spaceOptions, user.group_paths]);

  useEffect(() => {
    syncExplorerUrl({ activeTab, documentSearch, ingestFilter, selectedDocumentId, statusFilter, view });
  }, [activeTab, documentSearch, ingestFilter, selectedDocumentId, statusFilter, view]);

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
      setOpenSpaceTabs((current) => current.filter((item) => item !== path));
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

  const updateDocumentClearanceMutation = useMutation({
    mutationFn: ({ clearanceLevel, document }: DocumentClearanceMutation) =>
      documentsApi.updateClearance(document.id, { clearance_level: clearanceLevel }),
    onMutate: ({ document }) => {
      setPendingIds((current) => new Set([...current, document.id]));
    },
    onSuccess: (updated) => {
      notify({
        title: "Document clearance updated",
        description: `${updated.title} is now ${clearanceLevelLabel(updated.clearance_level)}.`,
        tone: "success",
      });
      void refreshDocuments();
    },
    onError: (error) => notify({
      title: "Clearance update failed",
      description: errorMessage(error, "Unable to update document clearance."),
      tone: "error",
    }),
    onSettled: (_data, _error, variables) => {
      if (!variables) return;
      setPendingIds((current) => {
        const next = new Set(current);
        next.delete(variables.document.id);
        return next;
      });
    },
  });

  function activateTab(tab: ExplorerTab) {
    const nextKey = explorerTabKey(tab);
    if (nextKey !== activeTabKey) {
      setPreviousTabKey(activeTabKey);
      setSelectedDocumentId(null);
    }
    setActiveTab(tab);
  }

  function openSpace(path: string) {
    setOpenSpaceTabs((current) => (current.includes(path) ? current : [...current, path]));
    setExpandedPaths((current) => new Set([...current, path]));
    activateTab({ kind: "space", path });
  }

  function closeSpaceTab(path: string) {
    setOpenSpaceTabs((current) => current.filter((item) => item !== path));
    if (activeTab.kind === "space" && activeTab.path === path) {
      const previous = tabFromKey(previousTabKey, openSpaceTabs.filter((item) => item !== path)) ?? { kind: "overview" as const };
      activateTab(previous);
    }
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
    if (window.confirm(`Delete Knowledge Space "${space.name}" (${space.path})? This only works for empty spaces with no child spaces or assigned users.`)) {
      deleteSpaceMutation.mutate(space.path);
    }
  }

  async function refreshDocuments() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["documents", "list"] }),
      queryClient.invalidateQueries({ queryKey: ["documents", "detail"] }),
      queryClient.invalidateQueries({ queryKey: ["documents", "versions"] }),
    ]);
  }

  async function performDocumentAction(action: DocumentAction, document: Document) {
    if (!confirmDocumentAction(action, [document])) return;
    await runDocumentActions(action, [document]);
  }

  async function performBulkAction(action: DocumentAction, documents: Document[]) {
    if (documents.length === 0 || !confirmDocumentAction(action, documents)) return;
    await runDocumentActions(action, documents);
  }

  async function runDocumentActions(action: DocumentAction, documents: Document[]) {
    setPendingIds((current) => new Set([...current, ...documents.map((doc) => doc.id)]));
    const results = await runBounded(documents, 4, async (document) => {
      await executeDocumentAction(action, document);
      return document;
    });
    setPendingIds((current) => {
      const next = new Set(current);
      documents.forEach((doc) => next.delete(doc.id));
      return next;
    });
    const failures = results.filter((result) => !result.ok);
    const successCount = results.length - failures.length;
    notify({
      title: failures.length ? "Document action partially failed" : "Documents updated",
      description: failures.length
        ? `${successCount} succeeded, ${failures.length} failed. ${failures[0]?.message ?? ""}`.trim()
        : `${successCount} document${successCount === 1 ? "" : "s"} updated.`,
      tone: failures.length ? "warning" : "success",
    });
    setSelectedIds(new Set());
    if (action === "trash" || action === "permanent") setSelectedDocumentId(null);
    await refreshDocuments();
  }

  async function executeDocumentAction(action: DocumentAction, document: Document) {
    if (action === "reingest") {
      await documentsApi.reingest(document.id);
      return;
    }
    if (action === "trash") {
      await documentsApi.remove(document.id);
      return;
    }
    if (action === "restore") {
      await documentsApi.restore(document.id);
      return;
    }
    await documentsApi.permanentlyRemove(document.id);
  }

  const currentTabDocuments = documentsForView(view, activeTab, activeDocuments, deletedDocuments, documentSearch, statusFilter, ingestFilter);
  const selectedDocuments = currentTabDocuments.filter((doc) => selectedIds.has(doc.id));
  const activeRoute: RouteId = view === "documents" ? "documents" : view === "trash" ? "document-trash" : "knowledge-spaces";
  const pageTitle = view === "documents" ? "Documents" : view === "trash" ? "Trash" : "Space Explorer";
  const pageSubtitle = view === "documents"
    ? "Search and manage active documents across every Knowledge Space visible to you."
    : view === "trash"
      ? "Restore soft-deleted documents or permanently delete them when your role permits."
      : "Browse the folder hierarchy and open focused tabs for documents stored directly in each Knowledge Space.";

  return (
    <FahamWorkspace activeRoute={activeRoute} onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page" id="main-content">
        <div className="sv-page-inner max-w-none">
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
          {activeDocsQuery.isError && view !== "trash" ? <InlineMessage tone="error">{errorMessage(activeDocsQuery.error, "Unable to load documents.")}</InlineMessage> : null}
          {deletedDocsQuery.isError && view === "trash" ? <InlineMessage tone="warning">{errorMessage(deletedDocsQuery.error, "Unable to load Trash.")}</InlineMessage> : null}
          {deleteSpaceMutation.isError ? <InlineMessage tone="error">{errorMessage(deleteSpaceMutation.error, "Unable to delete Knowledge Space.")}</InlineMessage> : null}

          {view === "spaces" ? (
            <section className={hasSelectedDocument ? "knowledge-explorer-shell knowledge-explorer-shell-with-inspector" : "knowledge-explorer-shell"}>
              <aside className="knowledge-folder-pane" aria-label="Knowledge Space folder tree">
                <div className="knowledge-folder-pane-header">
                  <div>
                    <p className="sv-metadata">Folders</p>
                    <h2>Knowledge Spaces</h2>
                  </div>
                  {isSpaceManager ? (
                    <button type="button" onClick={() => openCreateSpace()} className="knowledge-icon-button" aria-label="Create root Knowledge Space">
                      <Plus size={16} />
                    </button>
                  ) : null}
                </div>
                <label className="knowledge-tree-search">
                  <Search size={16} aria-hidden="true" />
                  <span className="sr-only">Search Knowledge Spaces</span>
                  <input value={spaceSearch} onChange={(event) => setSpaceSearch(event.target.value)} placeholder="Search folders..." />
                </label>
                <KnowledgeFolderTree
                  activePath={activeTab.kind === "space" ? activeTab.path : null}
                  deletingPath={deletingSpacePath}
                  documents={activeDocuments}
                  expandedPaths={expandedPaths}
                  isLoading={isLoadingDirectory}
                  isSpaceManager={isSpaceManager}
                  onDeleteSpace={deleteSpace}
                  onEditSpace={openEditSpace}
                  onOpenSpace={openSpace}
                  onToggle={(path) => {
                    setExpandedPaths((current) => {
                      const next = new Set(current);
                      if (next.has(path)) next.delete(path);
                      else next.add(path);
                      return next;
                    });
                  }}
                  search={spaceSearch}
                  spaces={spaceOptions}
                />
              </aside>

              <section className="knowledge-explorer-main">
                {activeFolderTabs.length > 0 ? (
                  <ExplorerTabs
                    activeTab={activeTab}
                    onActivate={activateTab}
                    onCloseSpace={closeSpaceTab}
                    openSpaces={activeFolderTabs}
                  />
                ) : null}

                <div className="knowledge-explorer-panel">
                  {activeTab.kind === "space" ? (
                  <FolderTab
                    bulkSelection={selectedIds}
                    canUploadDocuments={canUploadToSelectedSpace}
                    childSpaces={spaceOptions.filter((space) => space.parentPath === activeTab.path)}
                    documents={currentTabDocuments}
                    ingestFilter={ingestFilter}
                    isLoading={activeDocsQuery.isLoading}
                    onBulkAction={(action) => performBulkAction(action, selectedDocuments)}
                    onDocumentAction={performDocumentAction}
                    onNavigate={onNavigate}
                    onOpenSpace={openSpace}
                    onSearchChange={setDocumentSearch}
                    onSelectDocument={setSelectedDocumentId}
                    onSelectionChange={setSelectedIds}
                    pendingIds={pendingIds}
                    search={documentSearch}
                    selectedDocumentId={selectedDocumentId}
                    setIngestFilter={setIngestFilter}
                    setStatusFilter={setStatusFilter}
                    space={selectedSpace ?? spaceFromPath(activeTab.path)}
                    statusFilter={statusFilter}
                    user={user}
                  />
                  ) : (
                    <EmptyState title="Select a Knowledge Space">Choose a folder from the tree to open its direct documents in a tab.</EmptyState>
                  )}
                </div>
              </section>

              {hasSelectedDocument ? (
                <DocumentInspector
                  document={selectedDocument}
                  onClose={() => setSelectedDocumentId(null)}
                  onClearanceChange={(document, clearanceLevel) => updateDocumentClearanceMutation.mutate({ document, clearanceLevel })}
                  onDocumentAction={performDocumentAction}
                  pending={pendingIds.has(selectedDocument!.id)}
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
                      documents={currentTabDocuments}
                      ingestFilter={ingestFilter}
                      isLoading={activeDocsQuery.isLoading}
                      onBulkAction={(action) => performBulkAction(action, selectedDocuments)}
                      onDocumentAction={performDocumentAction}
                      onNavigate={onNavigate}
                      onSearchChange={setDocumentSearch}
                      onSelectDocument={setSelectedDocumentId}
                      onSelectionChange={setSelectedIds}
                      pendingIds={pendingIds}
                      search={documentSearch}
                      selectedDocumentId={selectedDocumentId}
                      setIngestFilter={setIngestFilter}
                      setStatusFilter={setStatusFilter}
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
                      setIngestFilter={setIngestFilter}
                      setStatusFilter={setStatusFilter}
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
                  onClearanceChange={(document, clearanceLevel) => updateDocumentClearanceMutation.mutate({ document, clearanceLevel })}
                  onDocumentAction={performDocumentAction}
                  pending={pendingIds.has(selectedDocument!.id)}
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
    </FahamWorkspace>
  );
}

function ExplorerTabs({ activeTab, onActivate, onCloseSpace, openSpaces }: ExplorerTabsProps) {
  return (
    <div className="knowledge-internal-tabs" role="tablist" aria-label="Open Knowledge Space tabs">
      {openSpaces.map((space) => (
        <button
          key={space.path}
          type="button"
          role="tab"
          aria-selected={activeTab.kind === "space" && activeTab.path === space.path}
          className={activeTab.kind === "space" && activeTab.path === space.path ? "knowledge-internal-tab-active" : "knowledge-internal-tab"}
          onClick={() => onActivate({ kind: "space", path: space.path })}
        >
          <Folder size={15} />
          <span>{space.name}</span>
          <small>{space.path}</small>
          <span
            role="button"
            tabIndex={0}
            className="knowledge-tab-close"
            aria-label={`Close ${space.name}`}
            onClick={(event) => {
              event.stopPropagation();
              onCloseSpace(space.path);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                event.stopPropagation();
                onCloseSpace(space.path);
              }
            }}
          >
            <X size={14} />
          </span>
        </button>
      ))}
    </div>
  );
}

function KnowledgeFolderTree({
  activePath,
  deletingPath,
  documents,
  expandedPaths,
  isLoading,
  isSpaceManager,
  onDeleteSpace,
  onEditSpace,
  onOpenSpace,
  onToggle,
  search,
  spaces,
}: KnowledgeFolderTreeProps) {
  const spaceByPath = new Map(spaces.map((space) => [space.path, space]));
  const childrenByParent = new Map<string, GroupOption[]>();
  for (const space of spaces) {
    const key = space.parentPath && spaceByPath.has(space.parentPath) ? space.parentPath : "";
    childrenByParent.set(key, [...(childrenByParent.get(key) ?? []), space]);
  }
  const query = search.trim().toLowerCase();

  function matches(space: GroupOption): boolean {
    if (!query) return true;
    if (space.name.toLowerCase().includes(query) || space.path.toLowerCase().includes(query)) return true;
    return (childrenByParent.get(space.path) ?? []).some(matches);
  }

  function renderRows(parentPath = ""): JSX.Element[] {
    return (childrenByParent.get(parentPath) ?? []).filter(matches).flatMap((space) => {
      const children = childrenByParent.get(space.path) ?? [];
      const expanded = expandedPaths.has(space.path) || Boolean(query);
      const directCount = documents.filter((doc) => doc.group_path === space.path).length;
      const descendantCount = documents.filter((doc) => isDocumentInSpace(doc.group_path, space.path)).length;
      return [
        <div key={space.path} className={activePath === space.path ? "knowledge-tree-row-active" : "knowledge-tree-row"} style={{ "--space-depth": space.depth } as TreeRowStyle}>
          <button type="button" className="knowledge-tree-toggle" onClick={() => onToggle(space.path)} disabled={children.length === 0} aria-label={expanded ? `Collapse ${space.name}` : `Expand ${space.name}`}>
            {children.length > 0 ? expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} /> : <span />}
          </button>
          <button type="button" className="knowledge-tree-folder" onClick={() => onOpenSpace(space.path)}>
            {activePath === space.path ? <FolderOpen size={16} /> : <Folder size={16} />}
            <span>
              <strong>{space.name}</strong>
              <small>{space.path}</small>
            </span>
          </button>
          <span className="knowledge-tree-count" title={`${descendantCount} documents in this folder and descendants`}>
            {directCount}
          </span>
          {isSpaceManager ? (
            <div className="knowledge-tree-actions">
              <button type="button" onClick={() => onEditSpace(space)} aria-label={`Edit ${space.name}`}>
                <Edit3 size={13} />
              </button>
              <button type="button" onClick={() => onDeleteSpace(space)} disabled={deletingPath === space.path} aria-label={`Delete ${space.name}`}>
                <Trash2 size={13} />
              </button>
            </div>
          ) : null}
        </div>,
        ...(expanded ? renderRows(space.path) : []),
      ];
    });
  }

  if (isLoading) return <SpaceSkeleton />;
  const rows = renderRows();
  if (rows.length === 0) {
    return <EmptyState title="No folders">No Knowledge Spaces match this view.</EmptyState>;
  }
  return <div className="knowledge-tree">{rows}</div>;
}

function OverviewTab({ activeDocuments, canUploadDocuments, deletedCount, isLoading, onCreateSpace, onNavigate, onOpenSpace, onShowJobs, onShowTrash, rows }: OverviewTabProps) {
  const currentCount = activeDocuments.filter((doc) => doc.is_current).length;
  const processingCount = activeDocuments.filter((doc) => isProcessingIngestStatus(doc.ingest_status)).length;
  const reviewCount = activeDocuments.filter((doc) => doc.ingest_status === "human_review").length;
  const failedCount = activeDocuments.filter((doc) => doc.ingest_status === "failed").length;
  const unknownCount = activeDocuments.filter((doc) => doc.ingest_status === "unknown").length;

  return (
    <div className="knowledge-section knowledge-overview">
      <div className="knowledge-section-header">
        <div>
          <h2 className="sv-section-title">Workspace overview</h2>
          <p className="text-body-md text-on-surface-variant">Open a folder from the left tree to manage documents directly inside that Knowledge Space.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={onCreateSpace} className="sv-action-secondary">
            <FolderPlus size={16} /> New Space
          </button>
          {canUploadDocuments ? (
            <button type="button" onClick={() => onNavigate("upload")} className="sv-action-primary">
              <Upload size={16} /> Upload
            </button>
          ) : null}
        </div>
      </div>
      <div className="knowledge-card-metrics" aria-label="Document lifecycle summary">
        <ContextMetric label="Active documents" value={String(activeDocuments.length)} loading={isLoading} />
        <ContextMetric label="Current" value={String(currentCount)} loading={isLoading} tone="success" />
        <ContextMetric label="Needs attention" value={String(processingCount + reviewCount + failedCount + unknownCount)} loading={isLoading} />
        <ContextMetric label="Trash" value={String(deletedCount)} loading={isLoading} />
      </div>
      <div className="knowledge-action-strip">
        <button type="button" onClick={onShowJobs}>Review Activity</button>
        <button type="button" onClick={onShowTrash}>Open Trash</button>
      </div>
      <section className="knowledge-job-block" aria-label="Knowledge Space breakdown">
        <div className="knowledge-job-block-header">
          <div>
            <h3>Folder breakdown</h3>
            <p>Counts include documents in each folder and its descendants.</p>
          </div>
          <span className="sv-pill">{rows.length} spaces</span>
        </div>
        {isLoading ? <DocumentSkeleton /> : null}
        {!isLoading && rows.length > 0 ? (
          <div className="knowledge-doc-surface">
            <table className="sv-table knowledge-doc-table knowledge-space-breakdown-table">
              <thead>
                <tr>
                  <th>Knowledge Space</th>
                  <th>Documents</th>
                  <th>Ingestion</th>
                  <th>Children</th>
                </tr>
              </thead>
              <tbody className="text-body-md">
                {rows.map((row) => (
                  <tr key={row.space.path} className="sv-table-row">
                    <td data-label="Knowledge Space">
                      <button type="button" className="knowledge-link-button" onClick={() => onOpenSpace(row.space.path)}>
                        <strong>{row.space.name}</strong>
                        <span>{row.space.path}</span>
                      </button>
                    </td>
                    <td data-label="Documents" className="text-secondary">
                      {row.documentsCount} total · {row.currentCount} current
                    </td>
                    <td data-label="Ingestion">
                      <div className="knowledge-breakdown-pills">
                        {row.processingCount > 0 ? <span className="sv-pill knowledge-status-processing">{row.processingCount} processing</span> : null}
                        {row.reviewCount > 0 ? <span className="sv-pill knowledge-status-human_review">{row.reviewCount} review</span> : null}
                        {row.failedCount > 0 ? <span className="sv-pill knowledge-status-failed">{row.failedCount} failed</span> : null}
                        {row.unknownCount > 0 ? <span className="sv-pill knowledge-status-unknown">{row.unknownCount} unknown</span> : null}
                        {row.processingCount + row.reviewCount + row.failedCount + row.unknownCount === 0 ? <span className="sv-pill sv-pill-success">Healthy</span> : null}
                      </div>
                    </td>
                    <td data-label="Children" className="text-secondary">{row.childCount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function FolderTab({
  bulkSelection,
  canUploadDocuments,
  childSpaces,
  documents,
  ingestFilter,
  isLoading,
  onBulkAction,
  onDocumentAction,
  onNavigate,
  onOpenSpace,
  onSearchChange,
  onSelectDocument,
  onSelectionChange,
  pendingIds,
  search,
  selectedDocumentId,
  setIngestFilter,
  setStatusFilter,
  space,
  statusFilter,
  user,
}: FolderTabProps) {
  const selectedCount = bulkSelection.size;
  return (
    <div className="knowledge-section">
      <div className="knowledge-section-header">
        <div>
          <div className="knowledge-breadcrumbs">
            {space.path.split("/").filter(Boolean).map((part, index, parts) => (
              <span key={`${part}-${index}`}>{index === parts.length - 1 ? part : `${part} /`}</span>
            ))}
          </div>
          <h2 className="sv-section-title">{space.name}</h2>
          <p className="text-body-md text-on-surface-variant">Showing documents directly in <strong>{space.path}</strong>. Open child folders to view their documents.</p>
        </div>
      </div>

      {childSpaces.length > 0 ? (
        <div className="knowledge-child-folder-grid" aria-label="Child folders">
          {childSpaces.map((child) => (
            <button key={child.path} type="button" onClick={() => onOpenSpace(child.path)}>
              <Folder size={16} />
              <span>
                <strong>{child.name}</strong>
                <small>{child.path}</small>
              </span>
            </button>
          ))}
        </div>
      ) : null}

      <Filters
        ingestFilter={ingestFilter}
        search={search}
        setIngestFilter={setIngestFilter}
        setSearch={onSearchChange}
        setStatusFilter={setStatusFilter}
        statusFilter={statusFilter}
      />

      {selectedCount > 0 ? (
        <BulkToolbar
          count={selectedCount}
          mode="active"
          onAction={onBulkAction}
          onClear={() => onSelectionChange(new Set())}
          user={user}
        />
      ) : null}

      <DocumentTable
        documents={documents}
        emptyAction={canUploadDocuments ? "Upload document" : undefined}
        emptyTitle="No documents in this folder"
        isLoading={isLoading}
        mode="active"
        onAction={onDocumentAction}
        onEmptyAction={canUploadDocuments ? () => onNavigate("upload") : undefined}
        onSelectDocument={onSelectDocument}
        onSelectionChange={onSelectionChange}
        pendingIds={pendingIds}
        selectedDocumentId={selectedDocumentId}
        selectedIds={bulkSelection}
        user={user}
      />
    </div>
  );
}

function ActiveDocumentsTab({
  bulkSelection,
  canUploadDocuments,
  documents,
  ingestFilter,
  isLoading,
  onBulkAction,
  onDocumentAction,
  onNavigate,
  onSearchChange,
  onSelectDocument,
  onSelectionChange,
  pendingIds,
  search,
  selectedDocumentId,
  setIngestFilter,
  setStatusFilter,
  statusFilter,
  user,
}: ActiveDocumentsTabProps) {
  return (
    <div className="knowledge-section">
      <div className="knowledge-section-header">
        <div>
          <h2 className="sv-section-title">Active documents</h2>
          <p className="text-body-md text-on-surface-variant">Search, inspect, and manage documents across all Knowledge Spaces visible to you.</p>
        </div>
      </div>
      <Filters
        ingestFilter={ingestFilter}
        search={search}
        setIngestFilter={setIngestFilter}
        setSearch={onSearchChange}
        setStatusFilter={setStatusFilter}
        statusFilter={statusFilter}
      />
      {bulkSelection.size > 0 ? (
        <BulkToolbar
          count={bulkSelection.size}
          mode="active"
          onAction={onBulkAction}
          onClear={() => onSelectionChange(new Set())}
          user={user}
        />
      ) : null}
      <DocumentTable
        documents={documents}
        emptyAction={canUploadDocuments ? "Upload document" : undefined}
        emptyTitle="No active documents match these filters"
        isLoading={isLoading}
        mode="active"
        onAction={onDocumentAction}
        onEmptyAction={canUploadDocuments ? () => onNavigate("upload") : undefined}
        onSelectDocument={onSelectDocument}
        onSelectionChange={onSelectionChange}
        pendingIds={pendingIds}
        selectedDocumentId={selectedDocumentId}
        selectedIds={bulkSelection}
        user={user}
      />
    </div>
  );
}

function TrashTab({
  bulkSelection,
  documents,
  ingestFilter,
  isLoading,
  onBulkAction,
  onDocumentAction,
  onSearchChange,
  onSelectDocument,
  onSelectionChange,
  pendingIds,
  search,
  selectedDocumentId,
  setIngestFilter,
  setStatusFilter,
  statusFilter,
  user,
}: TrashTabProps) {
  return (
    <div className="knowledge-section">
      <div className="knowledge-section-header">
        <div>
          <h2 className="sv-section-title">Trash</h2>
          <p className="text-body-md text-on-surface-variant">Soft-deleted documents stay here until restored or permanently deleted by an admin.</p>
        </div>
      </div>
      <Filters
        ingestFilter={ingestFilter}
        search={search}
        setIngestFilter={setIngestFilter}
        setSearch={onSearchChange}
        setStatusFilter={setStatusFilter}
        statusFilter={statusFilter}
      />
      {bulkSelection.size > 0 ? (
        <BulkToolbar
          count={bulkSelection.size}
          mode="trash"
          onAction={onBulkAction}
          onClear={() => onSelectionChange(new Set())}
          user={user}
        />
      ) : null}
      <DocumentTable
        documents={documents}
        emptyTitle="Trash is empty"
        isLoading={isLoading}
        mode="trash"
        onAction={onDocumentAction}
        onSelectDocument={onSelectDocument}
        onSelectionChange={onSelectionChange}
        pendingIds={pendingIds}
        selectedDocumentId={selectedDocumentId}
        selectedIds={bulkSelection}
        user={user}
      />
    </div>
  );
}

function JobsTab({ batchItems, canUploadDocuments, documents, isLoading, onNavigate }: JobsTabProps) {
  const processingBatchItems = batchItems.filter((item) => item.requestState !== "failed" && !isUploadTerminalStatus(item.job?.status));
  const attentionBatchItems = batchItems.filter((item) => item.requestState === "failed" || item.job?.status === "failed" || item.job?.status === "human_review" || item.job?.status === "cancelled");
  const activeDocuments = documents.filter((doc) => doc.ingest_status !== "complete");
  const processingCount = activeDocuments.filter((doc) => isProcessingIngestStatus(doc.ingest_status)).length + processingBatchItems.length;
  const failedCount = activeDocuments.filter((doc) => doc.ingest_status === "failed").length + attentionBatchItems.filter((item) => item.requestState === "failed" || item.job?.status === "failed").length;
  const reviewCount = activeDocuments.filter((doc) => doc.ingest_status === "human_review").length + attentionBatchItems.filter((item) => item.job?.status === "human_review").length;
  const unknownCount = activeDocuments.filter((doc) => doc.ingest_status === "unknown").length;
  const completeCount = documents.filter((doc) => doc.ingest_status === "complete").length + batchItems.filter((item) => item.job?.status === "complete").length;

  return (
    <div className="knowledge-section">
      <div className="knowledge-section-header">
        <div>
          <h2 className="sv-section-title">Uploads and Activity</h2>
          <p className="text-body-md text-on-surface-variant">Persistent document status plus live progress from uploads in this browser session.</p>
        </div>
        {canUploadDocuments ? (
          <button type="button" onClick={() => onNavigate("upload")} className="sv-action-primary">
            <Upload size={16} /> Open Intake
          </button>
        ) : null}
      </div>
      <div className="knowledge-job-metrics" aria-label="Activity summary">
        <ContextMetric label="Processing" value={String(processingCount)} loading={isLoading} />
        <ContextMetric label="Needs review" value={String(reviewCount)} loading={isLoading} />
        <ContextMetric label="Failed" value={String(failedCount)} loading={isLoading} />
        <ContextMetric label="Unknown" value={String(unknownCount)} loading={isLoading} />
        <ContextMetric label="Indexed" value={String(completeCount)} loading={isLoading} tone="success" />
      </div>
      {batchItems.length > 0 ? (
        <section className="knowledge-job-block" aria-label="Current browser upload activity">
          <div className="knowledge-job-block-header">
            <div>
              <h3>Current upload batch</h3>
              <p>Live progress from this browser session, including page/chunk/vector detail when available.</p>
            </div>
            <span className="sv-pill">{batchItems.length} recent</span>
          </div>
          <div className="knowledge-job-list">
            {batchItems.map((item) => <UploadJobCard item={item} key={item.id} />)}
          </div>
        </section>
      ) : null}
      <section className="knowledge-job-block" aria-label="Persistent ingestion status">
        <div className="knowledge-job-block-header">
          <div>
            <h3>Persistent ingestion status</h3>
            <p>Documents that are queued, processing, failed, unknown, or waiting for review.</p>
          </div>
          <span className="sv-pill">{activeDocuments.length} active</span>
        </div>
        <DocumentTable
          documents={activeDocuments}
          emptyAction={canUploadDocuments ? "Upload document" : undefined}
          emptyTitle="No active processing"
          isLoading={isLoading}
          mode="readonly"
          onEmptyAction={canUploadDocuments ? () => onNavigate("upload") : undefined}
          onSelectDocument={() => undefined}
          onSelectionChange={() => undefined}
          pendingIds={new Set()}
          selectedDocumentId={null}
          selectedIds={new Set()}
          user={null}
        />
      </section>
    </div>
  );
}

function UploadJobCard({ item }: { item: UploadBatchItemView }) {
  const job = item.job;
  const status: DocumentIngestStatus = item.requestState === "failed" ? "failed" : job?.status ?? "queued";
  const progressPct = job ? Math.max(0, Math.min(100, job.progressPct)) : item.requestState === "uploading" ? 8 : 0;
  const stageProgress = formatStageProgress(job?.stageProgress);
  const detail = item.requestState === "uploading"
    ? "Validating, scanning, storing, and queueing this document."
    : item.requestState === "failed"
      ? "The document did not reach the indexing queue."
      : job?.stageDetail ?? "Waiting for ingestion status.";

  return (
    <article className="knowledge-job-card">
      <div className="knowledge-job-card-main">
        <div>
          <h4>{item.fileName}</h4>
          <p>{item.groupPath} · {clearanceLevelLabel(item.clearanceLevel)} · {formatFileSizeForJob(item.fileSize)}</p>
        </div>
        <IngestStatusPill status={status} />
      </div>
      <p className="knowledge-job-card-detail">{detail}</p>
      {stageProgress ? <p className="knowledge-job-card-progress">{stageProgress}</p> : null}
      <div className="knowledge-job-progress" aria-label={`${item.fileName} ingestion progress`} aria-valuemax={100} aria-valuemin={0} aria-valuenow={progressPct} role="progressbar">
        <span style={{ width: `${progressPct}%` }} />
      </div>
    </article>
  );
}

function DocumentTable({
  documents,
  emptyAction,
  emptyTitle,
  isLoading,
  mode,
  onAction,
  onEmptyAction,
  onSelectDocument,
  onSelectionChange,
  pendingIds,
  selectedDocumentId,
  selectedIds,
  user,
}: DocumentTableProps) {
  const selectable = mode !== "readonly";
  const allSelected = selectable && documents.length > 0 && documents.every((doc) => selectedIds.has(doc.id));
  return (
    <div className="knowledge-doc-surface">
      {isLoading ? <DocumentSkeleton /> : null}
      {!isLoading && documents.length > 0 ? (
        <table className="sv-table knowledge-doc-table">
          <thead>
            <tr>
              {selectable ? (
                <th>
                  <button
                    type="button"
                    className="knowledge-checkbox-button"
                    onClick={() => onSelectionChange(allSelected ? new Set() : new Set(documents.map((doc) => doc.id)))}
                    aria-label={allSelected ? "Clear document selection" : "Select all documents in this table"}
                  >
                    {allSelected ? "☑" : "☐"}
                  </button>
                </th>
              ) : null}
              <th>Document</th>
              <th>Knowledge Space</th>
              <th>Clearance</th>
              <th>Lifecycle</th>
              <th>Ingestion</th>
              <th>Effective</th>
              {mode !== "readonly" ? <th>Actions</th> : null}
            </tr>
          </thead>
          <tbody className="text-body-md">
            {documents.map((doc) => {
              const selected = selectedIds.has(doc.id);
              const pending = pendingIds.has(doc.id);
              return (
                <tr key={doc.id} aria-selected={selectedDocumentId === doc.id} className="sv-table-row">
                  {selectable ? (
                    <td data-label="Select">
                      <button
                        type="button"
                        className="knowledge-checkbox-button"
                        onClick={() => {
                          const next = new Set(selectedIds);
                          if (next.has(doc.id)) next.delete(doc.id);
                          else next.add(doc.id);
                          onSelectionChange(next);
                        }}
                        aria-label={selected ? `Deselect ${doc.title}` : `Select ${doc.title}`}
                      >
                        {selected ? "☑" : "☐"}
                      </button>
                    </td>
                  ) : null}
                  <td data-label="Document">
                    <button type="button" className="knowledge-document-open" onClick={() => onSelectDocument(doc.id)}>
                      <FileText size={18} />
                      <span>
                        <strong>{doc.title}</strong>
                        <small>{doc.id}</small>
                      </span>
                    </button>
                    {doc.summary ? <p className="mt-1 max-w-xl text-body-md text-on-surface-variant">{doc.summary}</p> : null}
                    {doc.topics.length ? (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {doc.topics.slice(0, 4).map((topic) => <span key={topic} className="sv-pill">{topic}</span>)}
                      </div>
                    ) : null}
                  </td>
                  <td data-label="Knowledge Space" className="text-secondary">{doc.group_path}</td>
                  <td data-label="Clearance"><span className="sv-pill">{clearanceLevelLabel(doc.clearance_level)}</span></td>
                  <td data-label="Lifecycle"><DocumentStatePill document={doc} /></td>
                  <td data-label="Ingestion"><IngestStatusPill status={doc.ingest_status} /></td>
                  <td data-label="Effective" className="text-secondary">{formatDate(doc.effective_date)}</td>
                  {mode !== "readonly" && onAction && user ? (
                    <td data-label="Actions">
                      <DocumentRowActions document={doc} mode={mode} onAction={onAction} pending={pending} user={user} />
                    </td>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}
      {!isLoading && documents.length === 0 ? (
        <EmptyState action={emptyAction} onAction={onEmptyAction} title={emptyTitle}>
          {mode === "trash" ? "Soft-deleted documents will appear here with restore and permanent delete actions." : "Open another folder or adjust the filters to find documents."}
        </EmptyState>
      ) : null}
    </div>
  );
}

function DocumentRowActions({ document, mode, onAction, pending, user }: DocumentRowActionsProps) {
  const writable = canWriteDocument(user, document.group_path, document.clearance_level);
  const canPermanent = canPermanentlyDeleteDocument(user, document.group_path);
  if (mode === "trash") {
    return (
      <div className="knowledge-row-actions">
        {writable ? (
          <button type="button" onClick={() => onAction("restore", document)} disabled={pending} className="sv-action-secondary">
            <ArchiveRestore size={15} /> Restore
          </button>
        ) : null}
        {canPermanent ? (
          <button type="button" onClick={() => onAction("permanent", document)} disabled={pending} className="sv-action-danger">
            <ShieldAlert size={15} /> Delete
          </button>
        ) : null}
      </div>
    );
  }
  return (
    <div className="knowledge-row-actions">
      <a href={documentsApi.contentUrl(document.id)} target="_blank" rel="noreferrer" className="sv-action-secondary">
        <Eye size={15} /> View
      </a>
      {writable ? (
        <>
          <button type="button" onClick={() => onAction("reingest", document)} disabled={pending} className="sv-action-secondary">
            <RotateCw size={15} /> Reingest
          </button>
          <button type="button" onClick={() => onAction("trash", document)} disabled={pending} className="sv-action-danger">
            <Trash2 size={15} /> Trash
          </button>
        </>
      ) : null}
    </div>
  );
}

function BulkToolbar({ count, mode, onAction, onClear, user }: BulkToolbarProps) {
  const canPermanent = isGlobalAdmin(user) || user.account_type === "space_admin";
  return (
    <div className="knowledge-bulk-toolbar">
      <strong>{count} selected</strong>
      <span>Bulk actions run four requests at a time and report partial failures.</span>
      <div>
        {mode === "active" ? (
          <>
            <button type="button" onClick={() => onAction("reingest")} className="sv-action-secondary">
              <RotateCw size={15} /> Reingest
            </button>
            <button type="button" onClick={() => onAction("trash")} className="sv-action-danger">
              <Trash2 size={15} /> Move to Trash
            </button>
          </>
        ) : (
          <>
            <button type="button" onClick={() => onAction("restore")} className="sv-action-secondary">
              <ArchiveRestore size={15} /> Restore
            </button>
            {canPermanent ? (
              <button type="button" onClick={() => onAction("permanent")} className="sv-action-danger">
                <ShieldAlert size={15} /> Permanently Delete
              </button>
            ) : null}
          </>
        )}
        <button type="button" onClick={onClear} className="sv-action-secondary">Clear</button>
      </div>
    </div>
  );
}

function DocumentInspector({ document, onClearanceChange, onClose, onDocumentAction, pending, user }: DocumentInspectorProps) {
  const detailQuery = useQuery({
    queryKey: ["documents", "detail", document?.id],
    queryFn: () => documentsApi.get(document?.id ?? ""),
    enabled: Boolean(document?.id),
    retry: false,
  });
  const versionsQuery = useQuery<VersionChainResponse, Error>({
    queryKey: ["documents", "versions", document?.id],
    queryFn: () => documentsApi.versions(document?.id ?? ""),
    enabled: Boolean(document?.id),
    retry: false,
  });
  const selected = detailQuery.data ?? document;
  const [clearanceDraft, setClearanceDraft] = useState<ClearanceLevel>(document?.clearance_level ?? defaultClearanceLevel);
  const clearanceOptions = useMemo(() => clearanceLevelsAssignableBy(user), [user]);
  useEffect(() => {
    if (selected) setClearanceDraft(selected.clearance_level);
  }, [selected?.id, selected?.clearance_level]);
  if (!selected) return null;
  const writable = canWriteDocument(user, selected.group_path, selected.clearance_level);
  const canPermanent = canPermanentlyDeleteDocument(user, selected.group_path);
  const isDeleted = Boolean(selected.deleted_at);
  const canEditClearance = writable && !isDeleted;
  const clearanceChanged = clearanceDraft !== selected.clearance_level;
  const flagEntries = Object.entries(selected.metadata_flags ?? {}).filter(([, value]) => Boolean(value));

  return (
    <aside className="knowledge-inspector">
      <div className="knowledge-inspector-header">
        <div>
          <p className="sv-eyebrow">{isDeleted ? "Trash Inspector" : "Document Inspector"}</p>
          <h2>{selected.title}</h2>
        </div>
        <button type="button" onClick={onClose} className="knowledge-icon-button" aria-label="Close inspector">
          <X size={16} />
        </button>
      </div>
      {detailQuery.isError ? <InlineMessage tone="warning">{errorMessage(detailQuery.error, "Full document metadata could not be loaded.")}</InlineMessage> : null}
      <div className="knowledge-inspector-actions">
        {!isDeleted ? (
          <>
            <a href={documentsApi.contentUrl(selected.id)} target="_blank" rel="noreferrer" className="sv-action-secondary">
              <Eye size={15} /> View
            </a>
            <a href={documentsApi.contentUrl(selected.id)} download className="sv-action-secondary">
              <Download size={15} /> Download
            </a>
            {writable ? (
              <>
                <button type="button" onClick={() => onDocumentAction("reingest", selected)} disabled={pending} className="sv-action-secondary">
                  <RotateCw size={15} /> Reingest
                </button>
                <button type="button" onClick={() => onDocumentAction("trash", selected)} disabled={pending} className="sv-action-danger">
                  <Trash2 size={15} /> Move to Trash
                </button>
              </>
            ) : null}
          </>
        ) : (
          <>
            {writable ? (
              <button type="button" onClick={() => onDocumentAction("restore", selected)} disabled={pending} className="sv-action-secondary">
                <ArchiveRestore size={15} /> Restore
              </button>
            ) : null}
            {canPermanent ? (
              <button type="button" onClick={() => onDocumentAction("permanent", selected)} disabled={pending} className="sv-action-danger">
                <ShieldAlert size={15} /> Permanently Delete
              </button>
            ) : null}
          </>
        )}
      </div>
      <dl className="knowledge-detail-grid">
        <Fact label="Document ID" value={selected.id} />
        <Fact label="Knowledge Space" value={selected.group_path} />
        <Fact label="Clearance" value={clearanceLevelLabel(selected.clearance_level)} />
        <Fact label="Ingestion Status" value={labelize(selected.ingest_status)} />
        <Fact label="Lifecycle" value={isDeleted ? "In Trash" : selected.is_current ? "Current" : "Superseded"} />
        <Fact label="Uploaded by" value={selected.uploaded_by} />
        <Fact label="Created" value={formatDateTime(selected.created_at)} />
        <Fact label="Deleted" value={selected.deleted_at ? formatDateTime(selected.deleted_at) : "Not deleted"} />
        <Fact label="Effective" value={formatDate(selected.effective_date)} />
        <Fact label="Expires" value={selected.expiry_date ? formatDate(selected.expiry_date) : "No expiry"} />
        <Fact label="Language" value={selected.language || "Unknown"} />
      </dl>
      {canEditClearance ? (
        <InspectorSection title="Access Control">
          <label className="sv-field" htmlFor="document-clearance-level">
            <span className="sv-label">Clearance Level</span>
            <select
              id="document-clearance-level"
              className="sv-select"
              disabled={pending}
              onChange={(event) => setClearanceDraft(event.target.value as ClearanceLevel)}
              value={clearanceDraft}
            >
              {clearanceOptions.map((level) => (
                <option key={level} value={level}>
                  {clearanceLevelLabel(level)}
                </option>
              ))}
            </select>
            <small className="text-secondary">{clearanceLevelDescription(clearanceDraft)}</small>
          </label>
          <button
            type="button"
            className="sv-action-primary"
            disabled={!clearanceChanged || pending}
            onClick={() => onClearanceChange(selected, clearanceDraft)}
          >
            <Edit3 size={15} /> Save Clearance
          </button>
        </InspectorSection>
      ) : null}
      <InspectorSection title="Summary">
        <p>{selected.summary || selected.description || "No summary or description available."}</p>
      </InspectorSection>
      {flagEntries.length > 0 ? (
        <InspectorSection title="Metadata Review Flags">
          {flagEntries.map(([key, value]) => (
            <div key={key} className="knowledge-inspector-warning">
              <strong>{labelize(key)}</strong>
              <pre>{JSON.stringify(value, null, 2)}</pre>
            </div>
          ))}
        </InspectorSection>
      ) : null}
      <InspectorSection title="Topics">
        <ChipList values={[...selected.topics, ...selected.llm_topics]} empty="No topics extracted yet." />
      </InspectorSection>
      <InspectorSection title="Claims">
        <KeyValueList
          empty="No claims extracted yet."
          items={selected.claims.slice(0, 12).map((claim) => ({ key: `${claim.entity}.${claim.attribute}`, value: claim.value }))}
        />
      </InspectorSection>
      <InspectorSection title="Version History">
        {versionsQuery.isLoading ? <p className="text-secondary">Loading versions.</p> : null}
        {versionsQuery.isError ? <InlineMessage tone="warning">Version history could not be loaded.</InlineMessage> : null}
        {versionsQuery.data?.chain.length ? (
          <div className="knowledge-version-list">
            {versionsQuery.data.chain.map((version) => (
              <div key={version.id}>
                <strong>{version.id}</strong>
                <span className={version.is_current ? "sv-pill sv-pill-success" : "sv-pill"}>{version.is_current ? "Current" : "Superseded"}</span>
              </div>
            ))}
          </div>
        ) : !versionsQuery.isLoading ? (
          <p className="text-secondary">No version history recorded.</p>
        ) : null}
      </InspectorSection>
    </aside>
  );
}

function SpacePanel({
  draft,
  isCreate,
  isPending,
  mutationError,
  onChange,
  onNameChange,
  onSubmit,
  pathExists,
}: SpacePanelProps) {
  const pathIssue = isCreate ? groupPathIssue(draft.path, pathExists) : null;
  const canSubmit = draft.name.trim().length > 0 && (!isCreate || !pathIssue);

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <TextField autoComplete="off" disabled={isPending} helper="Shown in the folder tree and used to generate the default path." label="Space name" onChange={onNameChange} required value={draft.name} />
      {isCreate ? (
        <div className="sv-field">
          <label className="sv-label" htmlFor="space-path">
            Space path
          </label>
          <input
            id="space-path"
            className="sv-input text-code-sm"
            disabled={isPending}
            onChange={(event) => onChange((current) => ({ ...current, path: event.target.value.toLowerCase(), pathTouched: true }))}
            placeholder="/finance/procurement"
            required
            value={draft.path}
          />
          {pathIssue ? <small className="text-error-red">{pathIssue}</small> : <small className="text-secondary">Use a lowercase slash path like /finance.</small>}
          <div className="knowledge-path-preview">
            <span>Path preview</span>
            <strong>{draft.path || "Generated from the space name"}</strong>
          </div>
        </div>
      ) : (
        <ReadOnlyField label="Space path" value={draft.path} />
      )}
      {!isCreate ? <InlineMessage tone="warning">Space paths are immutable. Existing document ACL paths keep using this path.</InlineMessage> : null}
      {mutationError ? <InlineMessage tone="error">{errorMessage(mutationError, isCreate ? "Unable to create Knowledge Space." : "Unable to update Knowledge Space.")}</InlineMessage> : null}
      <div className="flex flex-wrap justify-end gap-2 border-t border-surface-border pt-4">
        <button type="submit" disabled={!canSubmit || isPending} className="sv-action-primary disabled:cursor-not-allowed disabled:opacity-60">
          {isPending ? "Saving" : isCreate ? "Create Space" : "Save Space"}
        </button>
      </div>
    </form>
  );
}

function Filters({ ingestFilter, search, setIngestFilter, setSearch, statusFilter, setStatusFilter }: FilterProps) {
  return (
    <div className="knowledge-toolbar">
      <label className="relative min-w-0 flex-1">
        <span className="sr-only">Filter documents</span>
        <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
        <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter by document name, ID, or space..." className="sv-input sv-input-with-leading-icon" />
      </label>
      <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as DocumentStateFilter)} className="sv-select sv-filter-select">
        <option value="all">All Lifecycle</option>
        <option value="current">Current</option>
        <option value="superseded">Superseded</option>
      </select>
      <select value={ingestFilter} onChange={(event) => setIngestFilter(event.target.value as DocumentIngestFilter)} className="sv-select sv-filter-select">
        <option value="all">All Ingestion</option>
        <option value="indexed">Indexed</option>
        <option value="active">Active Processing</option>
        <option value="processing">Processing</option>
        <option value="human_review">Needs Review</option>
        <option value="cancelled">Cancelled</option>
        <option value="failed">Failed</option>
        <option value="unknown">Unknown</option>
      </select>
    </div>
  );
}

function ContextMetric({ label, loading, tone, value }: { label: string; loading: boolean; tone?: "success"; value: string }) {
  return (
    <div className={tone === "success" ? "knowledge-context-metric knowledge-context-metric-success" : "knowledge-context-metric"} aria-busy={loading} data-cursor-glow>
      <span>{label}</span>
      {loading ? (
        <>
          <span className="sr-only">Loading {label.toLowerCase()}</span>
          <Skeleton className="mt-1 h-6 w-12" />
        </>
      ) : <strong>{value}</strong>}
    </div>
  );
}

function DocumentStatePill({ document }: { document: Document }) {
  if (document.deleted_at) return <span className="sv-pill knowledge-status-failed">In Trash</span>;
  return document.is_current ? <span className="sv-pill sv-pill-success">Current</span> : <span className="sv-pill">Superseded</span>;
}

function IngestStatusPill({ status }: { status: DocumentIngestStatus }) {
  const className = status === "cancelled" ? "sv-pill sv-pill-warning" : `sv-pill knowledge-status-${status}`;
  return <span className={className}>{ingestStatusLabel(status)}</span>;
}

function InspectorSection({ children, title }: InspectorSectionProps) {
  return (
    <section className="knowledge-inspector-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function ChipList({ empty, values }: { empty: string; values: string[] }) {
  const unique = Array.from(new Set(values.filter(Boolean)));
  if (!unique.length) return <p className="text-body-md text-secondary">{empty}</p>;
  return (
    <div className="flex flex-wrap gap-2">
      {unique.slice(0, 16).map((value) => <span key={value} className="sv-pill">{value}</span>)}
    </div>
  );
}

function KeyValueList({ empty, items }: { empty: string; items: Array<{ key: string; value: string }> }) {
  if (!items.length) return <p className="text-body-md text-secondary">{empty}</p>;
  return (
    <div className="space-y-2">
      {items.map((item, index) => (
        <div key={`${item.key}-${item.value}-${index}`} className="rounded-lg border border-surface-border bg-surface-card p-3 text-body-md">
          <span className="sv-metadata">{item.key}</span>
          <p className="mt-1 break-words font-semibold text-on-surface">{item.value}</p>
        </div>
      ))}
    </div>
  );
}

function EmptyState({ action, children, onAction, title }: EmptyStateProps) {
  return (
    <div className="knowledge-empty-state">
      <h3>{title}</h3>
      <p>{children}</p>
      {action && onAction ? (
        <button type="button" onClick={onAction} className="sv-action-primary">
          {action}
        </button>
      ) : null}
    </div>
  );
}

function SpaceSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="knowledge-skeleton-row" />
      ))}
    </div>
  );
}

function DocumentSkeleton() {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: 5 }).map((_, index) => (
        <div key={index} className="knowledge-skeleton-row" />
      ))}
    </div>
  );
}

function TextField({ autoComplete, disabled, helper, label, onChange, required, type = "text", value }: TextFieldProps) {
  const id = label.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return (
    <label className="sv-field" htmlFor={id}>
      <span className="sv-label">{label}</span>
      <input autoComplete={autoComplete} className="sv-input" disabled={disabled} id={id} onChange={(event) => onChange(event.target.value)} required={required} type={type} value={value} />
      {helper ? <small className="text-secondary">{helper}</small> : null}
    </label>
  );
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="sv-metadata">{label}</span>
      <p className="mt-1 break-all rounded-lg border border-surface-border bg-surface-container-low p-3 text-body-md font-semibold text-on-surface">{value}</p>
    </div>
  );
}

function documentsForView(
  view: DocumentsView,
  activeTab: ExplorerTab,
  activeDocuments: Document[],
  deletedDocuments: Document[],
  search: string,
  statusFilter: DocumentStateFilter,
  ingestFilter: DocumentIngestFilter,
) {
  const source = view === "trash"
    ? deletedDocuments
    : view === "documents"
      ? activeDocuments
      : activeTab.kind === "space"
        ? activeDocuments.filter((doc) => doc.group_path === activeTab.path)
        : [];
  return source.filter((doc) => matchesDoc(doc, search) && matchesStatus(doc, statusFilter) && matchesIngestStatus(doc.ingest_status, ingestFilter));
}

function matchesDoc(doc: Document, search: string) {
  const q = search.toLowerCase().trim();
  if (!q) return true;
  return [
    doc.title,
    doc.id,
    doc.group_path,
    clearanceLevelLabel(doc.clearance_level),
    doc.summary ?? "",
    doc.description ?? "",
    ...doc.topics,
    ...doc.llm_topics,
    ...doc.entities.map((entity) => entity.text),
  ].join(" ").toLowerCase().includes(q);
}

function matchesStatus(doc: Document, status: DocumentStateFilter) {
  return status === "all" || (status === "current" ? doc.is_current : !doc.is_current);
}

function matchesIngestStatus(status: DocumentIngestStatus, filter: DocumentIngestFilter) {
  if (filter === "all") return true;
  if (filter === "indexed") return status === "complete";
  if (filter === "active") return status !== "complete";
  if (filter === "processing") return isProcessingIngestStatus(status);
  return status === filter;
}

function isProcessingIngestStatus(status: DocumentIngestStatus) {
  return status === "queued" || status === "scheduled" || status === "processing";
}

function isActiveUploadJob(item: UploadBatchItemView) {
  if (item.requestState === "uploading") return true;
  if (item.requestState === "failed") return false;
  return !isUploadTerminalStatus(item.job?.status);
}

function isFailedUploadJob(item: UploadBatchItemView) {
  return item.requestState === "failed" || item.job?.status === "failed";
}

function buildSpaceOverviewRows(spaces: GroupOption[], documents: Document[], uploadJobs: UploadBatchItemView[]): SpaceOverviewRow[] {
  return spaces.map((space) => {
    const scopedDocuments = documents.filter((doc) => isDocumentInSpace(doc.group_path, space.path));
    const scopedJobs = uploadJobs.filter((job) => isDocumentInSpace(job.groupPath, space.path));
    return {
      childCount: spaces.filter((candidate) => candidate.parentPath === space.path).length,
      currentCount: scopedDocuments.filter((doc) => doc.is_current).length,
      documentsCount: scopedDocuments.length,
      failedCount: scopedDocuments.filter((doc) => doc.ingest_status === "failed").length + scopedJobs.filter(isFailedUploadJob).length,
      processingCount: scopedDocuments.filter((doc) => isProcessingIngestStatus(doc.ingest_status)).length + scopedJobs.filter(isActiveUploadJob).length,
      reviewCount: scopedDocuments.filter((doc) => doc.ingest_status === "human_review").length + scopedJobs.filter((job) => job.job?.status === "human_review").length,
      unknownCount: scopedDocuments.filter((doc) => doc.ingest_status === "unknown").length,
      space,
    };
  });
}

function rootSpaces(spaces: GroupOption[]) {
  const paths = new Set(spaces.map((space) => space.path));
  return spaces.filter((space) => !space.parentPath || !paths.has(space.parentPath));
}

function canPermanentlyDeleteDocument(user: AuthUser, groupPath: string) {
  return isGlobalAdmin(user) || (user.account_type === "space_admin" && isGroupPathInUserScope(user, groupPath));
}

function confirmDocumentAction(action: DocumentAction, documents: Document[]) {
  if (action === "trash") {
    return window.confirm(`Move ${documents.length} document${documents.length === 1 ? "" : "s"} to Trash? Indexed vectors will be removed immediately.`);
  }
  if (action === "permanent") {
    const expected = documents.length === 1 ? "DELETE" : `DELETE ${documents.length}`;
    const entered = window.prompt(`Permanent deletion removes database records and source files. Type ${expected} to continue.`);
    return entered === expected;
  }
  return true;
}

async function runBounded<T>(
  items: T[],
  concurrency: number,
  worker: (item: T) => Promise<unknown>,
): Promise<Array<{ item: T; ok: true } | { item: T; ok: false; message: string }>> {
  const results: Array<{ item: T; ok: true } | { item: T; ok: false; message: string }> = [];
  let index = 0;
  async function next() {
    while (index < items.length) {
      const item = items[index];
      index += 1;
      try {
        await worker(item);
        results.push({ item, ok: true });
      } catch (error) {
        results.push({ item, ok: false, message: errorMessage(error, "Request failed.") });
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, next));
  return results;
}

function ingestStatusLabel(status: DocumentIngestStatus) {
  if (status === "human_review") return "Needs review";
  if (status === "processing") return "Processing";
  if (status === "scheduled") return "Scheduled";
  if (status === "queued") return "Queued";
  if (status === "cancelled") return "Cancelled";
  if (status === "failed") return "Failed";
  if (status === "unknown") return "Unknown";
  return "Indexed";
}

function labelize(value: string | null | undefined) {
  if (!value) return "Unknown";
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatFileSizeForJob(bytes: number) {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

function spaceFromPath(path: string): GroupOption {
  const name = path.split("/").filter(Boolean).at(-1)?.replace(/-/g, " ") || path;
  return {
    depth: Math.max(0, path.split("/").filter(Boolean).length - 1),
    name: name.replace(/\b\w/g, (letter) => letter.toUpperCase()),
    parentPath: null,
    path,
  };
}

function initialExplorerTabFromUrl(): ExplorerTab {
  const space = initialStringParamFromUrl("space");
  if (space) return { kind: "space", path: space };
  return { kind: "overview" };
}

function initialOpenSpaceTabsFromSession() {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(sessionStorage.getItem(SPACE_TABS_STORAGE_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string" && item.startsWith("/")) : [];
  } catch {
    return [];
  }
}

function initialDocumentStateFilterFromUrl(): DocumentStateFilter {
  const value = initialStringParamFromUrl("lifecycle");
  return isDocumentStateFilter(value) ? value : "all";
}

function initialDocumentIngestFilterFromUrl(): DocumentIngestFilter {
  const value = initialStringParamFromUrl("ingest");
  return isDocumentIngestFilter(value) ? value : "all";
}

function initialStringParamFromUrl(name: string) {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get(name)?.trim() ?? "";
}

function syncExplorerUrl({ activeTab, documentSearch, ingestFilter, selectedDocumentId, statusFilter, view }: ExplorerUrlState) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.delete("tab");
  setUrlParam(url.searchParams, "space", view === "spaces" && activeTab.kind === "space" ? activeTab.path : "");
  setUrlParam(url.searchParams, "doc", selectedDocumentId ?? "");
  setUrlParam(url.searchParams, "doc_q", documentSearch.trim());
  setUrlParam(url.searchParams, "lifecycle", statusFilter === "all" ? "" : statusFilter);
  setUrlParam(url.searchParams, "ingest", ingestFilter === "all" ? "" : ingestFilter);
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== current) window.history.replaceState(window.history.state, "", next);
}

function setUrlParam(params: URLSearchParams, key: string, value: string) {
  if (value) params.set(key, value);
  else params.delete(key);
}

function explorerTabKey(tab: ExplorerTab) {
  return tab.kind === "space" ? `space:${tab.path}` : tab.kind;
}

function tabFromKey(key: string, openSpaceTabs: string[]): ExplorerTab | null {
  if (key === "overview" || key === "jobs" || key === "trash") return { kind: key };
  if (key.startsWith("space:")) {
    const path = key.slice("space:".length);
    return openSpaceTabs.includes(path) ? { kind: "space", path } : null;
  }
  return null;
}

function isDocumentStateFilter(value: string): value is DocumentStateFilter {
  return value === "all" || value === "current" || value === "superseded";
}

function isDocumentIngestFilter(value: string): value is DocumentIngestFilter {
  return value === "all" || value === "indexed" || value === "active" || value === "processing" || value === "human_review" || value === "cancelled" || value === "failed" || value === "unknown";
}

function createSpaceDraft(): SpaceDraft {
  return {
    name: "",
    path: "",
    pathTouched: false,
  };
}

type Props = { onLogout: () => void; onNavigate: (route: RouteId) => void; uploadJobs?: UploadBatchItemView[]; user: AuthUser; view?: DocumentsView };
type DocumentsView = "spaces" | "documents" | "trash";
type ExplorerTab = { kind: "overview" } | { kind: "jobs" } | { kind: "trash" } | { kind: "space"; path: string };
type DocumentAction = "reingest" | "trash" | "restore" | "permanent";
type DocumentMode = "active" | "trash" | "readonly";
type DocumentStateFilter = "all" | "current" | "superseded";
type DocumentIngestFilter = "all" | "indexed" | "active" | "processing" | "human_review" | "cancelled" | "failed" | "unknown";
type SpaceDraft = { name: string; path: string; pathTouched: boolean };
type SpacePanelState = { kind: "create-space" } | { kind: "edit-space"; space: GroupOption } | null;
type TreeRowStyle = CSSProperties & { "--space-depth": number };

type ExplorerUrlState = {
  activeTab: ExplorerTab;
  documentSearch: string;
  ingestFilter: DocumentIngestFilter;
  selectedDocumentId: string | null;
  statusFilter: DocumentStateFilter;
  view: DocumentsView;
};

type ExplorerTabsProps = {
  activeTab: ExplorerTab;
  onActivate: (tab: ExplorerTab) => void;
  onCloseSpace: (path: string) => void;
  openSpaces: GroupOption[];
};

type KnowledgeFolderTreeProps = {
  activePath: string | null;
  deletingPath: string | null;
  documents: Document[];
  expandedPaths: Set<string>;
  isLoading: boolean;
  isSpaceManager: boolean;
  onDeleteSpace: (space: GroupOption) => void;
  onEditSpace: (space: GroupOption) => void;
  onOpenSpace: (path: string) => void;
  onToggle: (path: string) => void;
  search: string;
  spaces: GroupOption[];
};

type SpaceOverviewRow = {
  childCount: number;
  currentCount: number;
  documentsCount: number;
  failedCount: number;
  processingCount: number;
  reviewCount: number;
  unknownCount: number;
  space: GroupOption;
};

type OverviewTabProps = {
  activeDocuments: Document[];
  canUploadDocuments: boolean;
  deletedCount: number;
  isLoading: boolean;
  onCreateSpace: () => void;
  onNavigate: (route: RouteId) => void;
  onOpenSpace: (path: string) => void;
  onShowJobs: () => void;
  onShowTrash: () => void;
  rows: SpaceOverviewRow[];
};

type FolderTabProps = {
  bulkSelection: Set<string>;
  canUploadDocuments: boolean;
  childSpaces: GroupOption[];
  documents: Document[];
  ingestFilter: DocumentIngestFilter;
  isLoading: boolean;
  onBulkAction: (action: DocumentAction) => void;
  onDocumentAction: (action: DocumentAction, document: Document) => void;
  onNavigate: (route: RouteId) => void;
  onOpenSpace: (path: string) => void;
  onSearchChange: (value: string) => void;
  onSelectDocument: (id: string) => void;
  onSelectionChange: Dispatch<SetStateAction<Set<string>>> | ((ids: Set<string>) => void);
  pendingIds: Set<string>;
  search: string;
  selectedDocumentId: string | null;
  setIngestFilter: (value: DocumentIngestFilter) => void;
  setStatusFilter: (value: DocumentStateFilter) => void;
  space: GroupOption;
  statusFilter: DocumentStateFilter;
  user: AuthUser;
};

type ActiveDocumentsTabProps = Omit<FolderTabProps, "childSpaces" | "onOpenSpace" | "space">;

type TrashTabProps = Omit<FolderTabProps, "canUploadDocuments" | "childSpaces" | "onNavigate" | "onOpenSpace" | "space">;

type JobsTabProps = {
  batchItems: UploadBatchItemView[];
  canUploadDocuments: boolean;
  documents: Document[];
  isLoading: boolean;
  onNavigate: (route: RouteId) => void;
};

type DocumentTableProps = {
  documents: Document[];
  emptyAction?: string;
  emptyTitle: string;
  isLoading: boolean;
  mode: DocumentMode;
  onAction?: (action: DocumentAction, document: Document) => void;
  onEmptyAction?: () => void;
  onSelectDocument: (id: string) => void;
  onSelectionChange: Dispatch<SetStateAction<Set<string>>> | ((ids: Set<string>) => void);
  pendingIds: Set<string>;
  selectedDocumentId: string | null;
  selectedIds: Set<string>;
  user: AuthUser | null;
};

type DocumentRowActionsProps = {
  document: Document;
  mode: Exclude<DocumentMode, "readonly">;
  onAction: (action: DocumentAction, document: Document) => void;
  pending: boolean;
  user: AuthUser;
};

type BulkToolbarProps = {
  count: number;
  mode: "active" | "trash";
  onAction: (action: DocumentAction) => void;
  onClear: () => void;
  user: AuthUser;
};

type DocumentInspectorProps = {
  document: Document | null;
  onClearanceChange: (document: Document, clearanceLevel: ClearanceLevel) => void;
  onClose: () => void;
  onDocumentAction: (action: DocumentAction, document: Document) => void;
  pending: boolean;
  user: AuthUser;
};

type DocumentClearanceMutation = {
  clearanceLevel: ClearanceLevel;
  document: Document;
};

type InspectorSectionProps = { children: React.ReactNode; title: string };

type FilterProps = {
  ingestFilter: DocumentIngestFilter;
  search: string;
  setIngestFilter: (value: DocumentIngestFilter) => void;
  setSearch: (value: string) => void;
  statusFilter: DocumentStateFilter;
  setStatusFilter: (value: DocumentStateFilter) => void;
};

type SpacePanelProps = {
  draft: SpaceDraft;
  isCreate: boolean;
  isPending: boolean;
  mutationError: unknown;
  onChange: Dispatch<SetStateAction<SpaceDraft>>;
  onNameChange: (name: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  pathExists: boolean;
};

type TextFieldProps = {
  autoComplete?: string;
  disabled?: boolean;
  helper?: string;
  label: string;
  onChange: (value: string) => void;
  required?: boolean;
  type?: string;
  value: string;
};

type EmptyStateProps = {
  action?: string;
  children?: string;
  onAction?: () => void;
  title: string;
};
