import { type Dispatch, type SetStateAction } from "react";
import { ArrowLeft } from "lucide-react";

import { DocumentFilters } from "@/features/documents/components/library/DocumentFilters";
import { BulkToolbar, DocumentCompactList } from "@/features/documents/components/library/DocumentList";
import type {
  DocumentAction,
  DocumentIngestFilter,
  DocumentStateFilter,
} from "@/features/documents/utils/documentPageUtils";
import type { GraphEnrichmentTask } from "@/features/upload/state/uploadJobProgress";
import type { RouteId } from "@/routes/routes";
import type { Document, GraphRAGStatus, User as AuthUser } from "@/types/api";
import type { GroupOption } from "@/lib/utils/groups";

export function FolderTab({
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

      <DocumentFilters
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

export function ActiveDocumentsTab({
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
      <DocumentFilters
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

export function TrashTab({
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
      <DocumentFilters
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
