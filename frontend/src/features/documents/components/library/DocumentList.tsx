import { useId, type Dispatch, type ReactNode, type SetStateAction } from "react";
import {
  ArchiveRestore,
  Eye,
  FileText,
  Loader2,
  Network,
  RotateCw,
  ShieldAlert,
  Trash2,
  XCircle,
} from "lucide-react";

import { documentsApi } from "@/lib/api/contracts";
import { clearanceLevelLabel, isGlobalAdmin } from "@/lib/auth/authz";
import {
  DocumentSkeleton,
  DocumentStatePill,
  EmptyState,
  IngestStatusPill,
} from "@/features/documents/components/library/DocumentPagePrimitives";
import { compactDocumentTopics, shortDocumentId } from "@/features/documents/components/library/documentListFormat";
import {
  canModifyDocument,
  canPermanentlyDeleteDocument,
  scopeLine,
  type DocumentAction,
  type DocumentMode,
} from "@/features/documents/utils/documentPageUtils";
import { graphEnrichmentForJob, graphEnrichmentTaskForJob, type GraphEnrichmentChip as GraphEnrichmentChipShape, type GraphEnrichmentTask } from "@/features/upload/state/uploadJobProgress";
import type { Document, GraphRAGStatus, User as AuthUser } from "@/types/api";
import { formatDate } from "@/lib/utils/format";

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

type RowActionTooltipProps = { children: (tooltipId: string) => ReactNode; label: string };

export function DocumentCompactList({
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

export function BulkToolbar({ count, mode, onAction, onClear, user }: BulkToolbarProps) {
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
