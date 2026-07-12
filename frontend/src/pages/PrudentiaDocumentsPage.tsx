import { useEffect, useId, useMemo, useState, type CSSProperties, type Dispatch, type FormEvent, type ReactNode, type SetStateAction } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArchiveRestore,
  ChevronDown,
  ChevronRight,
  Download,
  Edit3,
  Eye,
  FileText,
  Folder,
  FolderPlus,
  Loader2,
  Network,
  Plus,
  RotateCw,
  Search,
  Share2,
  ShieldAlert,
  Shuffle,
  Trash2,
  Unlink,
  Upload,
  X,
  XCircle,
} from "lucide-react";

import { adminApi, documentsApi, ingestJobsApi } from "../api/contracts";
import {
  canManageSpaces,
  canUploadToSpace,
  canViewSpaceMetadata,
  canWriteDocument,
  clearanceLevelDescription,
  clearanceLevelLabel,
  clearanceLevelsAssignableBy,
  defaultClearanceLevel,
  hasExactGroupScope,
  isGlobalAdmin,
  isGroupPathInUserScope,
} from "../authz";
import { useToast } from "../components/feedback/ToastProvider";
import { Fact, InlineMessage, Skeleton } from "../components/layout/Common";
import { PrudentiaWorkspace } from "../components/layout/PrudentiaWorkspace";
import { Modal } from "../components/layout/Modal";
import { compactDocumentTopics, hasActiveDocumentFilters, resultCountLabel, shortDocumentId } from "./document/documentListFormat";
import type { RouteId } from "../routes";
import { graphEnrichmentForJob, graphEnrichmentTaskForJob, isUploadTerminalStatus, type GraphEnrichmentChip as GraphEnrichmentChipShape, type GraphEnrichmentTask } from "../state/uploadJobProgress";
import type { ClearanceLevel, Document, DocumentIngestStatus, GraphRAGStatus, User as AuthUser, VersionChainResponse } from "../types/api";
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

const INSPECTOR_TABS: Array<{ id: InspectorTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "governance", label: "Governance" },
  { id: "extracted", label: "Extracted" },
  { id: "versions", label: "Versions" },
];

export function PrudentiaDocumentsPage({ onLogout, onNavigate, uploadJobs = [], user, view = "spaces" }: Props) {
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
  const [pendingIds, setPendingIds] = useState<Set<string>>(() => new Set());
  const [spacePanel, setSpacePanel] = useState<SpacePanelState>(null);
  const [spaceDraft, setSpaceDraft] = useState<SpaceDraft>(() => createSpaceDraft());
  const [deletingSpacePath, setDeletingSpacePath] = useState<string | null>(null);

  const activeDocsQuery = useQuery({ queryKey: ["documents", "list", "active"], queryFn: () => documentsApi.list({ state: "active" }), enabled: view !== "trash", staleTime: 5000, retry: false });
  const deletedDocsQuery = useQuery({ queryKey: ["documents", "list", "deleted"], queryFn: () => documentsApi.list({ state: "deleted" }), enabled: view === "trash", staleTime: 15000, retry: false });
  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, retry: false, enabled: canLoadSpaceDirectory });

  const activeDocuments = activeDocsQuery.data?.items ?? [];
  const deletedDocuments = deletedDocsQuery.data?.items ?? [];
  const allKnownDocuments = useMemo(() => [...activeDocuments, ...deletedDocuments], [activeDocuments, deletedDocuments]);
  const hasGraphEligibleDocuments = view !== "trash" && activeDocuments.some((document) => document.ingest_status === "complete");
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

  const updateDocumentTopicsMutation = useMutation({
    mutationFn: ({ document, topics }: DocumentTopicsMutation) =>
      documentsApi.updateTopics(document.id, { topics, llm_topics: [] }),
    onMutate: ({ document }) => {
      setPendingIds((current) => new Set([...current, document.id]));
    },
    onSuccess: (updated) => {
      notify({
        title: "Document topics updated",
        description: `${updated.title} now has ${updated.topics.length} topic${updated.topics.length === 1 ? "" : "s"}.`,
        tone: "success",
      });
      void refreshDocuments();
    },
    onError: (error) => notify({
      title: "Topic update failed",
      description: errorMessage(error, "Unable to update document topics."),
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

  const updateDocumentSharesMutation = useMutation({
    mutationFn: ({ document, groupPaths }: DocumentSharesMutation) =>
      documentsApi.updateShares(document.id, { group_paths: groupPaths }),
    onMutate: ({ document }) => {
      setPendingIds((current) => new Set([...current, document.id]));
    },
    onSuccess: (shares, { document }) => {
      notify({
        title: "Document sharing updated",
        description: `${document.title} is shared with ${shares.shared_group_paths.length} Knowledge Space${shares.shared_group_paths.length === 1 ? "" : "s"}.`,
        tone: "success",
      });
      void refreshDocuments();
      void queryClient.invalidateQueries({ queryKey: ["documents", "detail", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["documents", "shares", document.id] });
    },
    onError: (error) => notify({
      title: "Sharing update failed",
      description: errorMessage(error, "Unable to update document sharing."),
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

  const transferDocumentOwnerMutation = useMutation({
    mutationFn: ({ document, groupPath }: DocumentOwnerTransferMutation) =>
      documentsApi.transferOwnership(document.id, { group_path: groupPath }),
    onMutate: ({ document }) => {
      setPendingIds((current) => new Set([...current, document.id]));
    },
    onSuccess: (updated, { document }) => {
      notify({
        title: "Document ownership transferred",
        description: `${updated.title} now belongs to ${updated.owner_group_path}.`,
        tone: "success",
      });
      void refreshDocuments();
      void queryClient.invalidateQueries({ queryKey: ["documents", "detail", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["documents", "shares", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["ingest-jobs"] });
    },
    onError: (error) => notify({
      title: "Ownership transfer failed",
      description: errorMessage(error, "Unable to transfer document ownership."),
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

  const unshareDocumentMutation = useMutation({
    mutationFn: ({ document, groupPath }: DocumentUnshareMutation) =>
      documentsApi.unshare(document.id, { group_path: groupPath }),
    onMutate: ({ document }) => {
      setPendingIds((current) => new Set([...current, document.id]));
    },
    onSuccess: (_shares, { document, groupPath }) => {
      notify({ title: "Knowledge Space removed", description: `${groupPath} no longer has shared access.`, tone: "success" });
      void refreshDocuments();
      void queryClient.invalidateQueries({ queryKey: ["documents", "detail", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["documents", "shares", document.id] });
    },
    onError: (error) => notify({
      title: "Unshare failed",
      description: errorMessage(error, "Unable to remove document sharing."),
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

  const graphEnrichmentMutation = useMutation({
    mutationFn: (document: Document) => documentsApi.enrichGraph(document.id),
    onSuccess: async (response, document) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ingest-jobs", "graphrag-status"] }),
        queryClient.invalidateQueries({ queryKey: ["audit-log"] }),
      ]);
      notify({
        title: "Graph enrichment queued",
        description: `${document.title} queued as graph task for job ${response.job_id}.`,
        tone: "success",
      });
    },
    onError: (error) => notify({
      title: "Graph enrichment not queued",
      description: errorMessage(error, "Unable to queue graph enrichment."),
      tone: "error",
    }),
  });

  const graphCancelMutation = useMutation({
    mutationFn: ({ task }: { document: Document; task: GraphEnrichmentTask }) => {
      if (!task.jobId) throw new Error("Graph task is missing its ingestion job ID.");
      return ingestJobsApi.cancelGraphEnrichment(task.jobId, task.taskId);
    },
    onSuccess: async (response, { document }) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ingest-jobs", "graphrag-status"] }),
        queryClient.invalidateQueries({ queryKey: ["audit-log"] }),
      ]);
      notify({ title: "Graph enrichment cancelled", description: `${document.title}: ${response.message}`, tone: "success" });
    },
    onError: (error) => notify({
      title: "Graph enrichment not cancelled",
      description: errorMessage(error, "Unable to cancel graph enrichment."),
      tone: "error",
    }),
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

  const currentTabDocuments = documentsForView(view, visibleActiveTab, activeDocuments, deletedDocuments, documentSearch, statusFilter, ingestFilter, spaceFilter);
  const spaceOverviewRows = useMemo(() => buildSpaceOverviewRows(spaceOptions, activeDocuments, uploadJobs), [activeDocuments, spaceOptions, uploadJobs]);
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
                      cancellingGraphTaskId={graphCancelMutation.isPending ? graphCancelMutation.variables?.task.taskId ?? null : null}
                      documents={currentTabDocuments}
                      enrichingDocumentId={graphEnrichmentMutation.isPending ? graphEnrichmentMutation.variables?.id ?? null : null}
                      graphStatus={graphStatusQuery.data}
                      graphStatusError={graphStatusError}
                      ingestFilter={ingestFilter}
                      isLoading={activeDocsQuery.isLoading}
                      onBackToOverview={() => activateTab({ kind: "overview" })}
                      onBulkAction={(action) => performBulkAction(action, selectedDocuments)}
                      onDocumentAction={performDocumentAction}
                      onCancelGraph={(document, task) => graphCancelMutation.mutate({ document, task })}
                      onEnrichGraph={(document) => graphEnrichmentMutation.mutate(document)}
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
                    <OverviewTab
                      activeDocuments={activeDocuments}
                      canCreateSpace={isSpaceManager}
                      canManageSpaces={isSpaceManager}
                      canOpenSpaces
                      deletingSpacePath={deletingSpacePath}
                      deletedCount={deletedDocuments.length}
                      isLoading={activeDocsQuery.isLoading || isLoadingDirectory}
                      onCreateSpace={openCreateSpace}
                      onDeleteSpace={deleteSpace}
                      onEditSpace={openEditSpace}
                      onOpenSpace={openSpace}
                      onShowJobs={() => onNavigate("ingestion-jobs")}
                      onShowTrash={() => onNavigate("document-trash")}
                      rows={spaceOverviewRows}
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
                  onOwnerChange={(document, groupPath) => transferDocumentOwnerMutation.mutate({ document, groupPath })}
                  onSharesChange={(document, groupPaths) => updateDocumentSharesMutation.mutate({ document, groupPaths })}
                  onTopicsChange={(document, topics) => updateDocumentTopicsMutation.mutate({ document, topics })}
                  onUnshare={(document, groupPath) => unshareDocumentMutation.mutate({ document, groupPath })}
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
                      cancellingGraphTaskId={graphCancelMutation.isPending ? graphCancelMutation.variables?.task.taskId ?? null : null}
                      documents={currentTabDocuments}
                      enrichingDocumentId={graphEnrichmentMutation.isPending ? graphEnrichmentMutation.variables?.id ?? null : null}
                      graphStatus={graphStatusQuery.data}
                      graphStatusError={graphStatusError}
                      ingestFilter={ingestFilter}
                      isLoading={activeDocsQuery.isLoading}
                      onBulkAction={(action) => performBulkAction(action, selectedDocuments)}
                      onDocumentAction={performDocumentAction}
                      onCancelGraph={(document, task) => graphCancelMutation.mutate({ document, task })}
                      onEnrichGraph={(document) => graphEnrichmentMutation.mutate(document)}
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
                  onClearanceChange={(document, clearanceLevel) => updateDocumentClearanceMutation.mutate({ document, clearanceLevel })}
                  onDocumentAction={performDocumentAction}
                  onOwnerChange={(document, groupPath) => transferDocumentOwnerMutation.mutate({ document, groupPath })}
                  onSharesChange={(document, groupPaths) => updateDocumentSharesMutation.mutate({ document, groupPaths })}
                  onTopicsChange={(document, topics) => updateDocumentTopicsMutation.mutate({ document, topics })}
                  onUnshare={(document, groupPath) => unshareDocumentMutation.mutate({ document, groupPath })}
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


function OverviewTab({
  activeDocuments,
  canCreateSpace,
  canManageSpaces,
  canOpenSpaces,
  deletingSpacePath,
  deletedCount,
  isLoading,
  onCreateSpace,
  onDeleteSpace,
  onEditSpace,
  onOpenSpace,
  onShowJobs,
  onShowTrash,
  rows,
}: OverviewTabProps) {
  const currentCount = activeDocuments.filter((doc) => doc.is_current).length;
  const processingCount = activeDocuments.filter((doc) => isProcessingIngestStatus(doc.ingest_status)).length;
  const reviewCount = activeDocuments.filter((doc) => doc.ingest_status === "human_review").length;
  const failedCount = activeDocuments.filter((doc) => doc.ingest_status === "failed").length;
  const unknownCount = activeDocuments.filter((doc) => doc.ingest_status === "unknown").length;
  const attentionCount = processingCount + reviewCount + failedCount + unknownCount;
  const sortedRows = sortedSpaceOverviewRows(rows);
  const attentionRows = sortedRows.filter((row) => spaceAttentionCount(row) > 0).slice(0, 5);
  const emptyCount = rows.filter((row) => row.documentsCount === 0).length;

  return (
    <div className="knowledge-section knowledge-spaces-overview">
      <section className="knowledge-spaces-summary" aria-label="Knowledge Spaces summary">
        <div className="knowledge-spaces-summary-copy">
          <p className="sv-metadata">Knowledge Space Map</p>
          <h2>Governed document boundaries</h2>
          <p>Visible spaces, ingestion health, and document volume across the current corpus.</p>
        </div>
      </section>

      <div className="knowledge-spaces-metrics" aria-label="Knowledge Spaces metrics">
        <ContextMetric label="Spaces" value={String(rows.length)} loading={isLoading} />
        <ContextMetric label="Empty spaces" value={String(emptyCount)} loading={isLoading} />
        <ContextMetric label="Documents" value={String(activeDocuments.length)} loading={isLoading} />
        <ContextMetric label="Current" value={String(currentCount)} loading={isLoading} tone="success" />
        <ContextMetric label="Needs attention" value={String(attentionCount)} loading={isLoading} />
        <ContextMetric label="Trash" value={String(deletedCount)} loading={isLoading} />
      </div>

      <div className="knowledge-spaces-workbench">
        <section className="knowledge-space-directory-panel" aria-label="Knowledge Space directory">
          <div className="knowledge-space-panel-header">
            <div>
              <h3>Space directory</h3>
              <p>{emptyCount} empty, {attentionRows.length} with active attention signals.</p>
            </div>
            <span className="sv-pill">{rows.length} spaces</span>
          </div>
          {isLoading ? <SpaceOverviewSkeleton /> : null}
          {!isLoading && sortedRows.length > 0 ? (
            <div className="knowledge-space-overview-list">
              {sortedRows.map((row) => (
                <SpaceOverviewButton
                  key={row.space.path}
                  canManageSpaces={canManageSpaces}
                  canOpenSpaces={canOpenSpaces}
                  deletingSpacePath={deletingSpacePath}
                  onDeleteSpace={onDeleteSpace}
                  onEditSpace={onEditSpace}
                  onOpenSpace={onOpenSpace}
                  row={row}
                />
              ))}
            </div>
          ) : null}
          {!isLoading && sortedRows.length === 0 ? (
            <EmptyState action={canCreateSpace ? "Create Space" : undefined} onAction={canCreateSpace ? onCreateSpace : undefined} title="No Knowledge Spaces">
              No visible spaces are available for this account.
            </EmptyState>
          ) : null}
        </section>

        <aside className="knowledge-space-operations-panel" aria-label="Knowledge Space operations">
          <section className="knowledge-space-side-section">
            <div className="knowledge-space-panel-header">
              <div>
                <h3>Attention</h3>
                <p>Ingestion work and review states across visible spaces.</p>
              </div>
              <span className="sv-pill">{attentionCount}</span>
            </div>
            <SpaceAttentionList canOpenSpaces={canOpenSpaces} onOpenSpace={onOpenSpace} rows={attentionRows} />
          </section>

          <section className="knowledge-space-side-section">
            <div className="knowledge-space-panel-header">
              <div>
                <h3>Actions</h3>
                <p>Corpus operations for this workspace.</p>
              </div>
            </div>
            <div className="knowledge-space-action-list">
              <button type="button" onClick={onShowJobs}>
                <span>
                  <RotateCw size={16} />
                  <strong>Activity</strong>
                </span>
                <ChevronRight size={15} />
              </button>
              <button type="button" onClick={onShowTrash}>
                <span>
                  <Trash2 size={16} />
                  <strong>Trash</strong>
                </span>
                <ChevronRight size={15} />
              </button>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

function SpaceOverviewButton({
  canManageSpaces,
  canOpenSpaces,
  deletingSpacePath,
  onDeleteSpace,
  onEditSpace,
  onOpenSpace,
  row,
}: {
  canManageSpaces: boolean;
  canOpenSpaces: boolean;
  deletingSpacePath: string | null;
  onDeleteSpace: (space: GroupOption) => void;
  onEditSpace: (space: GroupOption) => void;
  onOpenSpace: (path: string) => void;
  row: SpaceOverviewRow;
}) {
  const health = spaceHealth(row);
  const style = { "--space-depth": row.space.depth } as TreeRowStyle;
  const rowBody = (
    <>
      <span className="knowledge-space-overview-icon">
        <Folder size={16} />
      </span>
      <span className="knowledge-space-overview-main">
        <strong>{row.space.name}</strong>
        <small>{row.space.path}</small>
      </span>
      <span className="knowledge-space-overview-stat">
        <strong>{row.documentsCount}</strong>
        <small>docs</small>
      </span>
      <span className="knowledge-space-overview-stat">
        <strong>{row.currentCount}</strong>
        <small>current</small>
      </span>
      <span className={`knowledge-space-health knowledge-space-health-${health.tone}`}>{health.label}</span>
      {canOpenSpaces ? <ChevronRight className="knowledge-space-row-chevron" size={15} aria-hidden="true" /> : null}
    </>
  );
  return (
    <div className={canOpenSpaces ? "knowledge-space-overview-row" : "knowledge-space-overview-row knowledge-space-overview-row-static"} style={style}>
      {canOpenSpaces ? (
        <button type="button" className="knowledge-space-overview-row-main" onClick={() => onOpenSpace(row.space.path)}>
          {rowBody}
        </button>
      ) : (
        <div className="knowledge-space-overview-row-main" aria-label={`${row.space.name} summary`}>
          {rowBody}
        </div>
      )}
      {canManageSpaces ? (
        <span className="knowledge-space-overview-actions">
          <button type="button" onClick={() => onEditSpace(row.space)} aria-label={`Edit ${row.space.name}`}>
            <Edit3 size={14} />
          </button>
          <button type="button" onClick={() => onDeleteSpace(row.space)} disabled={deletingSpacePath === row.space.path} aria-label={`Delete ${row.space.name}`}>
            <Trash2 size={14} />
          </button>
        </span>
      ) : null}
    </div>
  );
}

function SpaceAttentionList({ canOpenSpaces, onOpenSpace, rows }: { canOpenSpaces: boolean; onOpenSpace: (path: string) => void; rows: SpaceOverviewRow[] }) {
  if (!rows.length) {
    return <p className="knowledge-space-muted">No active ingestion or review issues in visible spaces.</p>;
  }
  const renderContent = (row: SpaceOverviewRow) => (
    <>
      <span>
        <strong>{row.space.name}</strong>
        <small>{row.space.path}</small>
      </span>
      <span className="knowledge-breakdown-pills">
        {row.failedCount > 0 ? <span className="sv-pill knowledge-status-failed">{row.failedCount} failed</span> : null}
        {row.reviewCount > 0 ? <span className="sv-pill knowledge-status-human_review">{row.reviewCount} review</span> : null}
        {row.processingCount > 0 ? <span className="sv-pill knowledge-status-processing">{row.processingCount} active</span> : null}
        {row.unknownCount > 0 ? <span className="sv-pill knowledge-status-unknown">{row.unknownCount} unknown</span> : null}
      </span>
    </>
  );
  return (
    <div className="knowledge-space-attention-list">
      {rows.map((row) => canOpenSpaces ? (
        <button key={row.space.path} type="button" onClick={() => onOpenSpace(row.space.path)}>
          {renderContent(row)}
        </button>
      ) : (
        <div key={row.space.path} className="knowledge-space-attention-row">
          {renderContent(row)}
        </div>
      ))}
    </div>
  );
}


function FolderTab({
  bulkSelection,
  canUploadDocuments,
  cancellingGraphTaskId,
  documents,
  enrichingDocumentId,
  graphStatus,
  graphStatusError,
  ingestFilter,
  isLoading,
  onBackToOverview,
  onBulkAction,
  onDocumentAction,
  onCancelGraph,
  onEnrichGraph,
  onNavigate,
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
          <p className="text-body-md text-on-surface-variant">Showing documents assigned to <strong>{space.path}</strong>.</p>
        </div>
        {onBackToOverview ? (
          <button type="button" onClick={onBackToOverview} className="sv-action-secondary knowledge-overview-return">
            <ArrowLeft size={16} /> Overview
          </button>
        ) : null}
      </div>

      <Filters
        ingestFilter={ingestFilter}
        onClear={() => {
          onSearchChange("");
          setStatusFilter("all");
          setIngestFilter("all");
        }}
        resultCount={documents.length}
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

      <DocumentCompactList
        cancellingGraphTaskId={cancellingGraphTaskId}
        documents={documents}
        enrichingDocumentId={enrichingDocumentId}
        emptyAction={canUploadDocuments ? "Upload document" : undefined}
        emptyTitle="No documents in this folder"
        isLoading={isLoading}
        mode="active"
        onAction={onDocumentAction}
        onCancelGraph={onCancelGraph}
        onEnrichGraph={onEnrichGraph}
        onEmptyAction={canUploadDocuments ? () => onNavigate("upload") : undefined}
        onSelectDocument={onSelectDocument}
        onSelectionChange={onSelectionChange}
        pendingIds={pendingIds}
        selectedDocumentId={selectedDocumentId}
        selectedIds={bulkSelection}
        user={user}
        graphStatus={graphStatus}
        graphStatusError={graphStatusError}
      />
    </div>
  );
}

function ActiveDocumentsTab({
  bulkSelection,
  canUploadDocuments,
  cancellingGraphTaskId,
  documents,
  enrichingDocumentId,
  graphStatus,
  graphStatusError,
  ingestFilter,
  isLoading,
  onBulkAction,
  onDocumentAction,
  onCancelGraph,
  onEnrichGraph,
  onNavigate,
  onSearchChange,
  onSelectDocument,
  onSelectionChange,
  pendingIds,
  search,
  selectedDocumentId,
  setIngestFilter,
  setSpaceFilter,
  setStatusFilter,
  spaceFilter,
  spaceOptions,
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
        onClear={() => {
          onSearchChange("");
          setStatusFilter("all");
          setIngestFilter("all");
          setSpaceFilter("");
        }}
        resultCount={documents.length}
        search={search}
        setIngestFilter={setIngestFilter}
        setSearch={onSearchChange}
        setSpaceFilter={setSpaceFilter}
        setStatusFilter={setStatusFilter}
        spaceFilter={spaceFilter}
        spaceOptions={spaceOptions}
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
      <DocumentCompactList
        cancellingGraphTaskId={cancellingGraphTaskId}
        documents={documents}
        enrichingDocumentId={enrichingDocumentId}
        emptyAction={canUploadDocuments ? "Upload document" : undefined}
        emptyTitle="No active documents match these filters"
        isLoading={isLoading}
        mode="active"
        onAction={onDocumentAction}
        onCancelGraph={onCancelGraph}
        onEnrichGraph={onEnrichGraph}
        onEmptyAction={canUploadDocuments ? () => onNavigate("upload") : undefined}
        onSelectDocument={onSelectDocument}
        onSelectionChange={onSelectionChange}
        pendingIds={pendingIds}
        selectedDocumentId={selectedDocumentId}
        selectedIds={bulkSelection}
        user={user}
        graphStatus={graphStatus}
        graphStatusError={graphStatusError}
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
  setSpaceFilter,
  setStatusFilter,
  spaceFilter,
  spaceOptions,
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
        onClear={() => {
          onSearchChange("");
          setStatusFilter("all");
          setIngestFilter("all");
          setSpaceFilter("");
        }}
        resultCount={documents.length}
        search={search}
        setIngestFilter={setIngestFilter}
        setSearch={onSearchChange}
        setSpaceFilter={setSpaceFilter}
        setStatusFilter={setStatusFilter}
        spaceFilter={spaceFilter}
        spaceOptions={spaceOptions}
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
      <DocumentCompactList
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


function DocumentCompactList({
  cancellingGraphTaskId,
  documents,
  emptyAction,
  emptyTitle,
  enrichingDocumentId,
  graphStatus,
  graphStatusError,
  isLoading,
  mode,
  onAction,
  onCancelGraph,
  onEnrichGraph,
  onEmptyAction,
  onSelectDocument,
  onSelectionChange,
  pendingIds,
  selectedDocumentId,
  selectedIds,
  user,
}: DocumentListProps) {
  const selectable = mode !== "readonly";
  const allSelected = selectable && documents.length > 0 && documents.every((doc) => selectedIds.has(doc.id));
  const someSelected = selectable && !allSelected && documents.some((doc) => selectedIds.has(doc.id));
  return (
    <div className="knowledge-doc-surface">
      {isLoading ? <DocumentSkeleton /> : null}
      {!isLoading && documents.length > 0 ? (
        <div className="knowledge-doc-list" role="table" aria-label="Documents">
          <div className="knowledge-doc-list-header" role="row">
            {selectable ? (
              <span role="columnheader">
                <input
                  type="checkbox"
                  checked={allSelected}
                  aria-label={allSelected ? "Clear document selection" : "Select all documents in this list"}
                  aria-checked={someSelected ? "mixed" : allSelected}
                  onChange={() => onSelectionChange(allSelected ? new Set() : new Set(documents.map((doc) => doc.id)))}
                  className="knowledge-doc-checkbox"
                />
              </span>
            ) : <span role="presentation" />}
            <span role="columnheader">Document</span>
            <span role="columnheader">Knowledge Space</span>
            <span role="columnheader">Status</span>
            <span role="columnheader">Effective</span>
            {mode !== "readonly" ? <span role="columnheader">Actions</span> : null}
          </div>
          <ul className="knowledge-doc-list-body">
            {documents.map((doc) => {
              const selected = selectedIds.has(doc.id);
              const pending = pendingIds.has(doc.id);
              const graphChip = doc.ingest_status === "complete"
                ? graphEnrichmentForJob({ jobId: "", status: "complete", documentId: doc.id }, graphStatus, graphStatusError)
                : null;
              const graphTask = doc.ingest_status === "complete"
                ? graphEnrichmentTaskForJob({ jobId: "", documentId: doc.id }, graphStatus)
                : null;
              const topicPreview = compactDocumentTopics([...doc.topics, ...doc.llm_topics], 3);
              const rowSelected = selectedDocumentId === doc.id;
              return (
                <li key={doc.id} aria-selected={rowSelected} className={rowSelected ? "knowledge-doc-row knowledge-doc-row-active" : "knowledge-doc-row"} role="row">
                  {selectable ? (
                    <label className="knowledge-doc-select" aria-label={selected ? `Deselect ${doc.title}` : `Select ${doc.title}`}>
                      <input
                        type="checkbox"
                        checked={selected}
                        disabled={pending}
                        onChange={() => {
                          const next = new Set(selectedIds);
                          if (next.has(doc.id)) next.delete(doc.id);
                          else next.add(doc.id);
                          onSelectionChange(next);
                        }}
                        className="knowledge-doc-checkbox"
                      />
                    </label>
                  ) : <span role="presentation" />}
                  <div className="knowledge-doc-primary" role="cell">
                    <button type="button" className="knowledge-document-open" onClick={() => onSelectDocument(doc.id)}>
                      <span className="knowledge-document-icon"><FileText size={16} /></span>
                      <span className="knowledge-document-copy">
                        <strong>{doc.title}</strong>
                        <small title={doc.id}>{shortDocumentId(doc.id)}</small>
                      </span>
                    </button>
                    {doc.summary || doc.description ? <p className="knowledge-doc-summary">{doc.summary || doc.description}</p> : null}
                    {topicPreview.visible.length ? (
                      <div className="knowledge-doc-topics" aria-label="Document topics">
                        {topicPreview.visible.map((topic) => <span key={topic} className="sv-pill">{topic}</span>)}
                        {topicPreview.remaining > 0 ? <span className="sv-pill">+{topicPreview.remaining}</span> : null}
                      </div>
                    ) : null}
                  </div>
                  <div className="knowledge-doc-scope" role="cell">
                    <span>{doc.owner_group_path ?? doc.group_path}</span>
                    <small>{scopeLine(doc)} - {clearanceLevelLabel(doc.clearance_level)}</small>
                  </div>
                  <div className="knowledge-doc-status-stack" role="cell">
                    <DocumentStatePill document={doc} />
                    <IngestStatusPill status={doc.ingest_status} />
                    {graphChip && graphChip.state !== "unavailable" ? <span className="sv-pill">{graphChip.label}</span> : null}
                  </div>
                  <div className="knowledge-doc-effective" role="cell">{formatDate(doc.effective_date)}</div>
                  {mode !== "readonly" && onAction && user ? (
                    <div className="knowledge-doc-actions" role="cell">
                      <DocumentRowActions
                        document={doc}
                        cancellingGraph={Boolean(graphTask && cancellingGraphTaskId === graphTask.taskId)}
                        enriching={enrichingDocumentId === doc.id}
                        graphChip={graphChip}
                        graphEnabled={Boolean(graphStatus?.enabled && !graphStatus.queue_error && !graphStatus.worker_error && !graphStatusError)}
                        graphTask={graphTask}
                        mode={mode}
                        onAction={onAction}
                        onCancelGraph={graphTask && onCancelGraph ? () => onCancelGraph(doc, graphTask) : undefined}
                        onEnrichGraph={onEnrichGraph ? () => onEnrichGraph(doc) : undefined}
                        pending={pending}
                        user={user}
                      />
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {!isLoading && documents.length === 0 ? (
        <EmptyState action={emptyAction} onAction={onEmptyAction} title={emptyTitle}>
          {mode === "trash" ? "Soft-deleted documents will appear here with restore and permanent delete actions." : "Open another folder or adjust the filters to find documents."}
        </EmptyState>
      ) : null}
    </div>
  );
}


function RowActionTooltip({ children, label }: RowActionTooltipProps) {
  const tooltipId = useId();

  return (
    <span className="knowledge-row-action-tooltip">
      {children(tooltipId)}
      <span id={tooltipId} role="tooltip" className="knowledge-action-tooltip">{label}</span>
    </span>
  );
}

function DocumentRowActions({ cancellingGraph = false, document, enriching = false, graphChip = null, graphEnabled = false, graphTask = null, mode, onAction, onCancelGraph, onEnrichGraph, pending, user }: DocumentRowActionsProps) {
  const writable = canModifyDocument(user, document);
  const canPermanent = canPermanentlyDeleteDocument(user, document);
  const cancelGraphTooltip = graphTask ? `Cancel ${graphTask.state} graph enrichment` : "Cancel graph enrichment";
  const enrichGraphTooltip = graphChip?.detail ?? graphChip?.label ?? (graphEnabled ? "Enrich graph" : "Graph enrichment unavailable");

  if (mode === "trash") {
    return (
      <div className="knowledge-row-actions">
        {writable ? (
          <RowActionTooltip label="Restore">
            {(tooltipId) => (
              <button type="button" onClick={() => onAction("restore", document)} disabled={pending} className="knowledge-icon-action" aria-describedby={tooltipId} aria-label={`Restore ${document.title}`}>
                <ArchiveRestore aria-hidden="true" size={15} />
              </button>
            )}
          </RowActionTooltip>
        ) : null}
        {canPermanent ? (
          <RowActionTooltip label="Permanently delete">
            {(tooltipId) => (
              <button type="button" onClick={() => onAction("permanent", document)} disabled={pending} className="knowledge-icon-action knowledge-icon-action-danger" aria-describedby={tooltipId} aria-label={`Permanently delete ${document.title}`}>
                <ShieldAlert aria-hidden="true" size={15} />
              </button>
            )}
          </RowActionTooltip>
        ) : null}
      </div>
    );
  }
  return (
    <div className="knowledge-row-actions">
      <RowActionTooltip label="View">
        {(tooltipId) => (
          <a href={documentsApi.contentUrl(document.id)} target="_blank" rel="noreferrer" className="knowledge-icon-action" aria-describedby={tooltipId} aria-label={`View ${document.title}`}>
            <Eye aria-hidden="true" size={15} />
          </a>
        )}
      </RowActionTooltip>
      {writable ? (
        <>
          {document.ingest_status === "complete" && graphTask && onCancelGraph ? (
            <RowActionTooltip label={cancelGraphTooltip}>
              {(tooltipId) => (
                <button
                  type="button"
                  onClick={onCancelGraph}
                  disabled={pending || cancellingGraph}
                  className="knowledge-icon-action knowledge-graph-action knowledge-icon-action-danger"
                  aria-describedby={tooltipId}
                  aria-label={`Cancel graph enrichment for ${document.title}`}
                >
                  {cancellingGraph ? <Loader2 aria-hidden="true" className="animate-spin" size={15} /> : <XCircle aria-hidden="true" size={15} />}
                </button>
              )}
            </RowActionTooltip>
          ) : null}
          {document.ingest_status === "complete" && graphEnabled && !graphTask && onEnrichGraph ? (
            <RowActionTooltip label={enriching ? "Queueing graph enrichment" : enrichGraphTooltip}>
              {(tooltipId) => (
                <button
                  type="button"
                  onClick={onEnrichGraph}
                  disabled={pending || enriching || Boolean(graphChip)}
                  className="knowledge-icon-action knowledge-graph-action"
                  aria-describedby={tooltipId}
                  aria-label={`Enrich graph for ${document.title}`}
                >
                  {enriching ? <Loader2 aria-hidden="true" className="animate-spin" size={15} /> : <Network aria-hidden="true" size={15} />}
                </button>
              )}
            </RowActionTooltip>
          ) : null}
          <RowActionTooltip label="Reingest">
            {(tooltipId) => (
              <button type="button" onClick={() => onAction("reingest", document)} disabled={pending} className="knowledge-icon-action" aria-describedby={tooltipId} aria-label={`Reingest ${document.title}`}>
                <RotateCw aria-hidden="true" size={15} />
              </button>
            )}
          </RowActionTooltip>
          <RowActionTooltip label="Move to Trash">
            {(tooltipId) => (
              <button type="button" onClick={() => onAction("trash", document)} disabled={pending} className="knowledge-icon-action knowledge-icon-action-danger" aria-describedby={tooltipId} aria-label={`Move ${document.title} to Trash`}>
                <Trash2 aria-hidden="true" size={15} />
              </button>
            )}
          </RowActionTooltip>
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

function DocumentInspector({ document, onClearanceChange, onClose, onDocumentAction, onOwnerChange, onSharesChange, onTopicsChange, onUnshare, pending, spaceOptions, user }: DocumentInspectorProps) {
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
  const [topicDraft, setTopicDraft] = useState<string[]>([]);
  const [topicInput, setTopicInput] = useState("");
  const [shareDraft, setShareDraft] = useState<string[]>([]);
  const [shareCandidate, setShareCandidate] = useState("");
  const [ownerCandidate, setOwnerCandidate] = useState("");
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("overview");
  const clearanceOptions = useMemo(() => clearanceLevelsAssignableBy(user), [user]);
  const selectedTopics = useMemo(() => uniqueTopicValues([...(selected?.topics ?? []), ...(selected?.llm_topics ?? [])]), [selected?.topics, selected?.llm_topics]);
  const selectedTopicKey = selectedTopics.join("\u001f");
  const selectedShareKey = (selected?.shared_group_paths ?? []).join("\u001f");
  const shareDraftKey = shareDraft.join("\u001f");
  const ownerGroupPath = selected?.owner_group_path ?? selected?.group_path ?? "";
  const shareOptions = useMemo(
    () => spaceOptions
      .filter((space) => space.path !== ownerGroupPath)
      .filter((space) => !shareDraft.includes(space.path)),
    [ownerGroupPath, shareDraft, spaceOptions],
  );
  const ownerOptions = useMemo(() => ownershipTransferOptions(user, ownerGroupPath, spaceOptions), [ownerGroupPath, spaceOptions, user]);
  useEffect(() => {
    if (selected) setClearanceDraft(selected.clearance_level);
  }, [selected?.id, selected?.clearance_level]);
  useEffect(() => {
    setShareDraft(selected?.shared_group_paths ?? []);
    setShareCandidate("");
  }, [selected?.id, selectedShareKey]);
  useEffect(() => {
    setOwnerCandidate("");
  }, [selected?.id, ownerGroupPath]);
  useEffect(() => {
    setTopicDraft(selectedTopics);
    setTopicInput("");
  }, [selected?.id, selectedTopicKey]);
  useEffect(() => {
    setInspectorTab("overview");
  }, [selected?.id]);
  if (!selected) return null;
  const writable = canModifyDocument(user, selected);
  const canPermanent = canPermanentlyDeleteDocument(user, selected);
  const isDeleted = Boolean(selected.deleted_at);
  const canTransferOwner = canTransferDocumentOwner(user, selected) && !isDeleted;
  const canEditClearance = writable && !isDeleted;
  const clearanceChanged = clearanceDraft !== selected.clearance_level;
  const canEditTopics = writable && !isDeleted;
  const topicDraftKey = uniqueTopicValues(topicDraft).join("\u001f");
  const topicsChanged = topicDraftKey !== selectedTopicKey;
  const canEditShares = isGlobalAdmin(user) && !isDeleted;
  const sharesChanged = shareDraftKey !== selectedShareKey;
  const flagEntries = Object.entries(selected.metadata_flags ?? {}).filter(([, value]) => Boolean(value));

  function addTopic(value: string) {
    const topic = value.trim();
    if (!topic || topic.length > 80 || topicDraft.length >= 32) return;
    setTopicDraft(uniqueTopicValues([...topicDraft, topic]).slice(0, 32));
    setTopicInput("");
  }

  function addShare(path: string) {
    const normalized = path.trim();
    if (!normalized || shareDraft.includes(normalized)) return;
    setShareDraft([...shareDraft, normalized].sort((a, b) => a.localeCompare(b)));
    setShareCandidate("");
  }

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
      <div className="knowledge-inspector-statusbar">
        <DocumentStatePill document={selected} />
        <IngestStatusPill status={selected.ingest_status} />
        <span className="sv-pill">{clearanceLevelLabel(selected.clearance_level)}</span>
      </div>
      <div className="knowledge-inspector-tabs" role="tablist" aria-label="Document inspector sections">
        {INSPECTOR_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={inspectorTab === tab.id}
            className={inspectorTab === tab.id ? "knowledge-inspector-tab-active" : "knowledge-inspector-tab"}
            onClick={() => setInspectorTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {inspectorTab === "overview" ? (
        <div className="knowledge-inspector-panel" role="tabpanel">
          <dl className="knowledge-detail-grid">
            <Fact label="Document ID" value={selected.id} />
            <Fact label="Owner Space" value={selected.owner_group_path ?? selected.group_path} />
            <Fact label="Shared Spaces" value={selected.shared_group_paths.length ? selected.shared_group_paths.join(", ") : "None"} />
            <Fact label="Uploaded by" value={selected.uploaded_by} />
            <Fact label="Created" value={formatDateTime(selected.created_at)} />
            <Fact label="Effective" value={formatDate(selected.effective_date)} />
            <Fact label="Language" value={selected.language || "Unknown"} />
          </dl>
          <InspectorSection title="Summary">
            <p>{selected.summary || selected.description || "No summary or description available."}</p>
          </InspectorSection>
        </div>
      ) : null}

      {inspectorTab === "governance" ? (
        <div className="knowledge-inspector-panel" role="tabpanel">
          <dl className="knowledge-detail-grid">
            <Fact label="Clearance" value={clearanceLevelLabel(selected.clearance_level)} />
            <Fact label="Governance" value={selected.governance_owner === "system" ? "System governed" : "Owner space"} />
            <Fact label="Ingestion Status" value={labelize(selected.ingest_status)} />
            <Fact label="Lifecycle" value={isDeleted ? "In Trash" : selected.is_current ? "Current" : "Superseded"} />
            <Fact label="Deleted" value={selected.deleted_at ? formatDateTime(selected.deleted_at) : "Not deleted"} />
            <Fact label="Expires" value={selected.expiry_date ? formatDate(selected.expiry_date) : "No expiry"} />
          </dl>
          <InspectorSection title="Owner Knowledge Space">
            <OwnerTransferControl
              canTransfer={canTransferOwner}
              currentGroupPath={ownerGroupPath}
              disabled={pending}
              onTransfer={() => onOwnerChange(selected, ownerCandidate)}
              options={ownerOptions}
              selectedCandidate={ownerCandidate}
              setSelectedCandidate={setOwnerCandidate}
            />
          </InspectorSection>
          <InspectorSection title="Shared Knowledge Spaces">
            <ShareControl
              canEdit={canEditShares}
              disabled={pending}
              draft={shareDraft}
              onAdd={addShare}
              onRemove={(path) => setShareDraft(shareDraft.filter((value) => value !== path))}
              onRevert={() => {
                setShareDraft(selected.shared_group_paths);
                setShareCandidate("");
              }}
              onSave={() => onSharesChange(selected, shareDraft)}
              onUnshare={(path) => onUnshare(selected, path)}
              options={shareOptions}
              ownerGroupPath={selected.owner_group_path ?? selected.group_path}
              selectedCandidate={shareCandidate}
              setSelectedCandidate={setShareCandidate}
              sharesChanged={sharesChanged}
              user={user}
            />
          </InspectorSection>
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
        </div>
      ) : null}

      {inspectorTab === "extracted" ? (
        <div className="knowledge-inspector-panel" role="tabpanel">
          {flagEntries.length > 0 ? (
            <InspectorSection title="Metadata Review Flags" defaultCollapsed resetKey={selected.id}>
              {flagEntries.map(([key, value]) => (
                <div key={key} className="knowledge-inspector-warning">
                  <strong>{labelize(key)}</strong>
                  <pre>{JSON.stringify(value, null, 2)}</pre>
                </div>
              ))}
            </InspectorSection>
          ) : null}
          <InspectorSection title="Topics">
            {canEditTopics ? (
              <TopicEditor
                changed={topicsChanged}
                disabled={pending}
                inputValue={topicInput}
                onAdd={addTopic}
                onInputChange={setTopicInput}
                onRemove={(topic) => setTopicDraft(topicDraft.filter((value) => value !== topic))}
                onRevert={() => {
                  setTopicDraft(selectedTopics);
                  setTopicInput("");
                }}
                onSave={() => onTopicsChange(selected, uniqueTopicValues(topicDraft))}
                values={topicDraft}
              />
            ) : (
              <ChipList values={selectedTopics} empty="No topics extracted yet." />
            )}
          </InspectorSection>
          <InspectorSection title="Entities">
            <KeyValueList
              empty="No entities extracted yet."
              items={selected.entities.slice(0, 12).map((entity) => ({ key: entity.type, value: entity.text }))}
            />
          </InspectorSection>
          <InspectorSection title="Cross References">
            <KeyValueList
              empty="No cross-references extracted yet."
              items={selected.cross_references.slice(0, 12).map((ref) => ({ key: ref.ref_type, value: ref.ref_text }))}
            />
          </InspectorSection>
          <InspectorSection title="Claims">
            <KeyValueList
              empty="No claims extracted yet."
              items={selected.claims.slice(0, 12).map((claim) => ({ key: `${claim.entity}.${claim.attribute}`, value: claim.value }))}
            />
          </InspectorSection>
        </div>
      ) : null}

      {inspectorTab === "versions" ? (
        <div className="knowledge-inspector-panel" role="tabpanel">
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
        </div>
      ) : null}
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

function Filters({ ingestFilter, onClear, resultCount, search, setIngestFilter, setSearch, setSpaceFilter, spaceFilter = "", spaceOptions = [], statusFilter, setStatusFilter }: FilterProps) {
  const hasFilters = hasActiveDocumentFilters(search, statusFilter, ingestFilter, spaceFilter);
  const showSpaceFilter = Boolean(setSpaceFilter);
  return (
    <div className="knowledge-toolbar">
      <label className="knowledge-toolbar-search relative">
        <span className="sr-only">Filter documents</span>
        <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
        <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter by document name, ID, or space..." className="sv-input sv-input-with-leading-icon" />
      </label>
      <div className={showSpaceFilter ? "knowledge-toolbar-controls knowledge-toolbar-controls-wide" : "knowledge-toolbar-controls"}>
        {setSpaceFilter ? (
          <select value={spaceFilter} onChange={(event) => setSpaceFilter(event.target.value)} className="sv-select sv-filter-select" aria-label="Knowledge Space filter">
            <option value="">All Spaces</option>
            {spaceOptions.map((space) => (
              <option key={space.path} value={space.path}>{space.path}</option>
            ))}
          </select>
        ) : null}
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as DocumentStateFilter)} className="sv-select sv-filter-select" aria-label="Lifecycle filter">
          <option value="all">All Lifecycle</option>
          <option value="current">Current</option>
          <option value="superseded">Superseded</option>
        </select>
        <select value={ingestFilter} onChange={(event) => setIngestFilter(event.target.value as DocumentIngestFilter)} className="sv-select sv-filter-select" aria-label="Ingestion filter">
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
      <div className="knowledge-toolbar-meta">
        <span>{resultCountLabel(resultCount)}</span>
        <button type="button" className="knowledge-filter-clear" disabled={!hasFilters} onClick={onClear}>
          Clear
        </button>
      </div>
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

function InspectorSection({ children, defaultCollapsed = false, resetKey, title }: InspectorSectionProps) {
  const contentId = useId();
  const collapsible = defaultCollapsed;
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  useEffect(() => {
    if (collapsible) setCollapsed(defaultCollapsed);
  }, [collapsible, defaultCollapsed, resetKey]);

  return (
    <section className={collapsed ? "knowledge-inspector-section knowledge-inspector-section-collapsed" : "knowledge-inspector-section"}>
      {collapsible ? (
        <h3>
          <button
            type="button"
            className="knowledge-inspector-section-toggle"
            aria-controls={contentId}
            aria-expanded={!collapsed}
            onClick={() => setCollapsed((value) => !value)}
          >
            <span>{title}</span>
            {collapsed ? <ChevronRight size={15} aria-hidden="true" /> : <ChevronDown size={15} aria-hidden="true" />}
          </button>
        </h3>
      ) : (
        <h3>{title}</h3>
      )}
      <div id={collapsible ? contentId : undefined} className={collapsible ? "knowledge-inspector-section-body" : undefined} hidden={collapsible && collapsed}>
        {children}
      </div>
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

function OwnerTransferControl({
  canTransfer,
  currentGroupPath,
  disabled,
  onTransfer,
  options,
  selectedCandidate,
  setSelectedCandidate,
}: OwnerTransferControlProps) {
  const canSubmit = canTransfer && Boolean(selectedCandidate) && !disabled;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (canSubmit) onTransfer();
  }

  return (
    <div className="knowledge-topic-editor">
      <label className="sv-field" htmlFor="document-owner-current">
        <span className="sv-label">Current owner</span>
        <input id="document-owner-current" className="sv-input" disabled readOnly value={currentGroupPath} />
      </label>
      {canTransfer ? (
        <form className="knowledge-topic-form" onSubmit={submit}>
          <label className="sv-field" htmlFor="document-owner-space">
            <span className="sv-label">Transfer to</span>
            <select
              id="document-owner-space"
              className="sv-select"
              disabled={disabled || options.length === 0}
              onChange={(event) => setSelectedCandidate(event.target.value)}
              value={selectedCandidate}
            >
              <option value="">Select space</option>
              {options.map((space) => (
                <option key={space.path} value={space.path}>
                  {space.name} {space.path}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="sv-action-primary" disabled={!canSubmit}>
            <Shuffle size={15} /> Transfer Ownership
          </button>
        </form>
      ) : null}
    </div>
  );
}

function ShareControl({
  canEdit,
  disabled,
  draft,
  onAdd,
  onRemove,
  onRevert,
  onSave,
  onUnshare,
  options,
  ownerGroupPath,
  selectedCandidate,
  setSelectedCandidate,
  sharesChanged,
  user,
}: ShareControlProps) {
  const canAdd = canEdit && Boolean(selectedCandidate) && !disabled;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (canAdd) onAdd(selectedCandidate);
  }

  if (!canEdit) {
    if (!draft.length) return <p className="text-body-md text-secondary">No shared Knowledge Spaces.</p>;
    return (
      <div className="knowledge-topic-chips">
        {draft.map((path) => (
          <span key={path} className="sv-pill knowledge-topic-pill">
            {path}
            {canUnshareTargetSpace(user, path) ? (
              <button type="button" disabled={disabled} onClick={() => onUnshare(path)} aria-label={`Remove ${path}`} title="Remove from this Knowledge Space">
                <Unlink size={13} />
              </button>
            ) : null}
          </span>
        ))}
      </div>
    );
  }

  return (
    <div className="knowledge-topic-editor">
      {draft.length ? (
        <div className="knowledge-topic-chips">
          {draft.map((path) => (
            <span key={path} className="sv-pill knowledge-topic-pill">
              {path}
              <button type="button" onClick={() => onRemove(path)} disabled={disabled} aria-label={`Remove ${path}`}>
                <X size={13} />
              </button>
            </span>
          ))}
        </div>
      ) : (
        <p className="text-body-md text-secondary">No shared Knowledge Spaces.</p>
      )}
      <form className="knowledge-topic-form" onSubmit={submit}>
        <label className="sv-field" htmlFor="document-share-space">
          <span className="sv-label">Knowledge Space</span>
          <select
            id="document-share-space"
            className="sv-select"
            disabled={disabled || options.length === 0}
            onChange={(event) => setSelectedCandidate(event.target.value)}
            value={selectedCandidate}
          >
            <option value="">Select space</option>
            {options.map((space) => (
              <option key={space.path} value={space.path}>
                {space.path === ownerGroupPath ? `${space.name} (${space.path})` : `${space.name} ${space.path}`}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="sv-action-secondary" disabled={!canAdd}>
          <Plus size={15} /> Add
        </button>
      </form>
      <div className="knowledge-topic-actions">
        <button type="button" className="sv-action-primary" disabled={!sharesChanged || disabled} onClick={onSave}>
          <Share2 size={15} /> Save Sharing
        </button>
        <button type="button" className="sv-action-secondary" disabled={!sharesChanged || disabled} onClick={onRevert}>
          Revert
        </button>
      </div>
    </div>
  );
}

function TopicEditor({ changed, disabled, inputValue, onAdd, onInputChange, onRemove, onRevert, onSave, values }: TopicEditorProps) {
  const trimmedInput = inputValue.trim();
  const inputExists = values.some((value) => value.toLowerCase() === trimmedInput.toLowerCase());
  const canAdd = Boolean(trimmedInput) && trimmedInput.length <= 80 && !inputExists && values.length < 32 && !disabled;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (canAdd) onAdd(trimmedInput);
  }

  return (
    <div className="knowledge-topic-editor">
      {values.length ? (
        <div className="knowledge-topic-chips">
          {values.map((value) => (
            <span key={value} className="sv-pill knowledge-topic-pill">
              {value}
              <button type="button" onClick={() => onRemove(value)} disabled={disabled} aria-label={`Remove ${value}`}>
                <X size={13} />
              </button>
            </span>
          ))}
        </div>
      ) : (
        <p className="text-body-md text-secondary">No topics saved yet.</p>
      )}
      <form className="knowledge-topic-form" onSubmit={submit}>
        <label className="sv-field" htmlFor="document-topic-input">
          <span className="sv-label">Topic</span>
          <input
            id="document-topic-input"
            className="sv-input"
            disabled={disabled || values.length >= 32}
            maxLength={80}
            onChange={(event) => onInputChange(event.target.value)}
            placeholder="Add topic"
            value={inputValue}
          />
        </label>
        <button type="submit" className="sv-action-secondary" disabled={!canAdd}>
          <Plus size={15} /> Add
        </button>
      </form>
      <div className="knowledge-topic-actions">
        <button type="button" className="sv-action-primary" disabled={!changed || disabled} onClick={onSave}>
          <Edit3 size={15} /> Save Topics
        </button>
        <button type="button" className="sv-action-secondary" disabled={!changed || disabled} onClick={onRevert}>
          Revert
        </button>
      </div>
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


function SpaceOverviewSkeleton() {
  return (
    <div className="knowledge-space-overview-list p-4">
      {Array.from({ length: 6 }).map((_, index) => (
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
  spaceFilter: string,
) {
  const source = view === "trash"
    ? deletedDocuments
    : view === "documents"
      ? activeDocuments
      : activeTab.kind === "space"
        ? activeDocuments.filter((doc) => documentAccessPaths(doc).includes(activeTab.path))
        : [];
  return source.filter((doc) => matchesSpace(doc, view, spaceFilter) && matchesDoc(doc, search) && matchesStatus(doc, statusFilter) && matchesIngestStatus(doc.ingest_status, ingestFilter));
}

function matchesSpace(doc: Document, view: DocumentsView, spaceFilter: string) {
  const selectedSpace = spaceFilter.trim();
  if (!selectedSpace || view === "spaces") return true;
  return isDocumentVisibleInSpace(doc, selectedSpace);
}

function matchesDoc(doc: Document, search: string) {
  const q = search.toLowerCase().trim();
  if (!q) return true;
  return [
    doc.title,
    doc.id,
    doc.owner_group_path ?? doc.group_path,
    ...doc.shared_group_paths,
    clearanceLevelLabel(doc.clearance_level),
    doc.summary ?? "",
    doc.description ?? "",
    ...doc.topics,
    ...doc.llm_topics,
    ...doc.entities.map((entity) => entity.text),
  ].join(" ").toLowerCase().includes(q);
}

function uniqueTopicValues(values: string[]): string[] {
  const seen = new Set<string>();
  const topics: string[] = [];
  values.forEach((value) => {
    const topic = value.trim();
    const key = topic.toLowerCase();
    if (topic && !seen.has(key)) {
      seen.add(key);
      topics.push(topic);
    }
  });
  return topics;
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
    const scopedDocuments = documents.filter((doc) => isDocumentVisibleInSpace(doc, space.path));
    const scopedJobs = uploadJobs.filter((job) => isDocumentInSpace(job.groupPath, space.path));
    return {
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

function mergeSpaceOptions(spaceOptions: GroupOption[], documents: Document[], selectedPath = "") {
  const seen = new Set<string>();
  const merged: GroupOption[] = [];
  spaceOptions.forEach((space) => {
    if (seen.has(space.path)) return;
    seen.add(space.path);
    merged.push(space);
  });
  documents
    .flatMap((doc) => documentAccessPaths(doc))
    .filter((path) => path && !seen.has(path))
    .sort((a, b) => a.localeCompare(b))
    .forEach((path) => {
      seen.add(path);
      merged.push(spaceFromPath(path));
    });
  const selected = selectedPath.trim();
  if (selected && !seen.has(selected)) merged.push(spaceFromPath(selected));
  return merged;
}

function documentAccessPaths(document: Document) {
  const paths = document.access_group_paths?.length
    ? document.access_group_paths
    : [document.owner_group_path ?? document.group_path, ...document.shared_group_paths];
  return Array.from(new Set(paths.filter(Boolean)));
}

function isDocumentVisibleInSpace(document: Document, spacePath: string) {
  return documentAccessPaths(document).some((path) => isDocumentInSpace(path, spacePath));
}

function scopeLine(document: Document) {
  if (!document.shared_group_paths.length) return "Owner only";
  return `Shared to ${document.shared_group_paths.length}`;
}

function sortedSpaceOverviewRows(rows: SpaceOverviewRow[]) {
  return [...rows].sort((a, b) => {
    const attentionDelta = spaceAttentionCount(b) - spaceAttentionCount(a);
    if (attentionDelta !== 0) return attentionDelta;
    const documentDelta = b.documentsCount - a.documentsCount;
    if (documentDelta !== 0) return documentDelta;
    return a.space.path.localeCompare(b.space.path);
  });
}

function spaceAttentionCount(row: SpaceOverviewRow) {
  return row.processingCount + row.reviewCount + row.failedCount + row.unknownCount;
}

function spaceHealth(row: SpaceOverviewRow): { label: string; tone: "active" | "danger" | "success" | "warning" } {
  if (row.failedCount > 0) return { label: `${row.failedCount} failed`, tone: "danger" };
  if (row.reviewCount > 0) return { label: `${row.reviewCount} review`, tone: "warning" };
  if (row.processingCount > 0) return { label: `${row.processingCount} active`, tone: "active" };
  if (row.unknownCount > 0) return { label: `${row.unknownCount} unknown`, tone: "warning" };
  return { label: "Healthy", tone: "success" };
}


function canModifyDocument(user: AuthUser, document: Document) {
  if (document.governance_owner === "system" && !isGlobalAdmin(user)) return false;
  return canWriteDocument(user, document.owner_group_path ?? document.group_path, document.clearance_level);
}

export function canTransferDocumentOwner(user: AuthUser, document: Document) {
  const ownerGroupPath = document.owner_group_path ?? document.group_path;
  return isGlobalAdmin(user) || (user.account_type === "space_admin" && hasExactGroupScope(user, ownerGroupPath));
}

export function ownershipTransferOptions(user: AuthUser, ownerGroupPath: string, spaceOptions: GroupOption[]) {
  const currentOwner = ownerGroupPath.trim();
  if (!currentOwner) return [];
  const candidates = spaceOptions.filter((space) => space.path !== currentOwner);
  if (isGlobalAdmin(user)) return candidates;
  if (user.account_type !== "space_admin" || !hasExactGroupScope(user, currentOwner)) return [];
  return candidates.filter((space) => hasExactGroupScope(user, space.path));
}

function canPermanentlyDeleteDocument(user: AuthUser, document: Document) {
  if (document.governance_owner === "system") return isGlobalAdmin(user);
  const groupPath = document.owner_group_path ?? document.group_path;
  return isGlobalAdmin(user) || (user.account_type === "space_admin" && isGroupPathInUserScope(user, groupPath));
}

function canUnshareTargetSpace(user: AuthUser, groupPath: string) {
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

function syncExplorerUrl({ activeTab, documentSearch, ingestFilter, selectedDocumentId, spaceFilter, statusFilter, view }: ExplorerUrlState) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.delete("tab");
  setUrlParam(url.searchParams, "space", view === "spaces" && activeTab.kind === "space" ? activeTab.path : view === "documents" || view === "trash" ? spaceFilter.trim() : "");
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
type ExplorerTab = { kind: "overview" } | { kind: "space"; path: string };
type DocumentAction = "reingest" | "trash" | "restore" | "permanent";
type DocumentMode = "active" | "trash" | "readonly";
type DocumentStateFilter = "all" | "current" | "superseded";
type DocumentIngestFilter = "all" | "indexed" | "active" | "processing" | "human_review" | "cancelled" | "failed" | "unknown";
type InspectorTab = "overview" | "governance" | "extracted" | "versions";
type SpaceDraft = { name: string; path: string; pathTouched: boolean };
type SpacePanelState = { kind: "create-space" } | { kind: "edit-space"; space: GroupOption } | null;
type TreeRowStyle = CSSProperties & { "--space-depth": number };
type RowActionTooltipProps = { children: (tooltipId: string) => ReactNode; label: string };

type ExplorerUrlState = {
  activeTab: ExplorerTab;
  documentSearch: string;
  ingestFilter: DocumentIngestFilter;
  selectedDocumentId: string | null;
  spaceFilter: string;
  statusFilter: DocumentStateFilter;
  view: DocumentsView;
};


type SpaceOverviewRow = {
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
  canCreateSpace: boolean;
  canManageSpaces: boolean;
  canOpenSpaces: boolean;
  deletingSpacePath: string | null;
  deletedCount: number;
  isLoading: boolean;
  onCreateSpace: () => void;
  onDeleteSpace: (space: GroupOption) => void;
  onEditSpace: (space: GroupOption) => void;
  onOpenSpace: (path: string) => void;
  onShowJobs: () => void;
  onShowTrash: () => void;
  rows: SpaceOverviewRow[];
};

type FolderTabProps = {
  bulkSelection: Set<string>;
  canUploadDocuments: boolean;
  cancellingGraphTaskId?: string | null;
  documents: Document[];
  enrichingDocumentId?: string | null;
  graphStatus?: GraphRAGStatus;
  graphStatusError?: string | null;
  ingestFilter: DocumentIngestFilter;
  isLoading: boolean;
  onBackToOverview?: () => void;
  onBulkAction: (action: DocumentAction) => void;
  onDocumentAction: (action: DocumentAction, document: Document) => void;
  onCancelGraph?: (document: Document, task: GraphEnrichmentTask) => void;
  onEnrichGraph?: (document: Document) => void;
  onNavigate: (route: RouteId) => void;
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

type DocumentSpaceFilterProps = {
  setSpaceFilter: (value: string) => void;
  spaceFilter: string;
  spaceOptions: GroupOption[];
};

type ActiveDocumentsTabProps = Omit<FolderTabProps, "space"> & DocumentSpaceFilterProps;

type TrashTabProps = Omit<FolderTabProps, "canUploadDocuments" | "onNavigate" | "space"> & DocumentSpaceFilterProps;


type DocumentListProps = {
  cancellingGraphTaskId?: string | null;
  documents: Document[];
  emptyAction?: string;
  emptyTitle: string;
  enrichingDocumentId?: string | null;
  graphStatus?: GraphRAGStatus;
  graphStatusError?: string | null;
  isLoading: boolean;
  mode: DocumentMode;
  onAction?: (action: DocumentAction, document: Document) => void;
  onCancelGraph?: (document: Document, task: GraphEnrichmentTask) => void;
  onEnrichGraph?: (document: Document) => void;
  onEmptyAction?: () => void;
  onSelectDocument: (id: string) => void;
  onSelectionChange: Dispatch<SetStateAction<Set<string>>> | ((ids: Set<string>) => void);
  pendingIds: Set<string>;
  selectedDocumentId: string | null;
  selectedIds: Set<string>;
  user: AuthUser | null;
};

type DocumentRowActionsProps = {
  cancellingGraph?: boolean;
  document: Document;
  enriching?: boolean;
  graphChip?: GraphEnrichmentChipShape | null;
  graphEnabled?: boolean;
  graphTask?: GraphEnrichmentTask | null;
  mode: Exclude<DocumentMode, "readonly">;
  onAction: (action: DocumentAction, document: Document) => void;
  onCancelGraph?: () => void;
  onEnrichGraph?: () => void;
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
  onOwnerChange: (document: Document, groupPath: string) => void;
  onSharesChange: (document: Document, groupPaths: string[]) => void;
  onTopicsChange: (document: Document, topics: string[]) => void;
  onUnshare: (document: Document, groupPath: string) => void;
  pending: boolean;
  spaceOptions: GroupOption[];
  user: AuthUser;
};

type DocumentClearanceMutation = {
  clearanceLevel: ClearanceLevel;
  document: Document;
};

type DocumentTopicsMutation = {
  document: Document;
  topics: string[];
};

type DocumentSharesMutation = {
  document: Document;
  groupPaths: string[];
};

type DocumentOwnerTransferMutation = {
  document: Document;
  groupPath: string;
};

type DocumentUnshareMutation = {
  document: Document;
  groupPath: string;
};

type InspectorSectionProps = { children: React.ReactNode; defaultCollapsed?: boolean; resetKey?: string; title: string };

type OwnerTransferControlProps = {
  canTransfer: boolean;
  currentGroupPath: string;
  disabled: boolean;
  onTransfer: () => void;
  options: GroupOption[];
  selectedCandidate: string;
  setSelectedCandidate: (path: string) => void;
};

type ShareControlProps = {
  canEdit: boolean;
  disabled: boolean;
  draft: string[];
  onAdd: (path: string) => void;
  onRemove: (path: string) => void;
  onRevert: () => void;
  onSave: () => void;
  onUnshare: (path: string) => void;
  options: GroupOption[];
  ownerGroupPath: string;
  selectedCandidate: string;
  setSelectedCandidate: (path: string) => void;
  sharesChanged: boolean;
  user: AuthUser;
};

type TopicEditorProps = {
  changed: boolean;
  disabled: boolean;
  inputValue: string;
  onAdd: (value: string) => void;
  onInputChange: (value: string) => void;
  onRemove: (value: string) => void;
  onRevert: () => void;
  onSave: () => void;
  values: string[];
};

type FilterProps = {
  ingestFilter: DocumentIngestFilter;
  onClear: () => void;
  resultCount: number;
  search: string;
  setIngestFilter: (value: DocumentIngestFilter) => void;
  setSearch: (value: string) => void;
  setSpaceFilter?: (value: string) => void;
  spaceFilter?: string;
  spaceOptions?: GroupOption[];
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
