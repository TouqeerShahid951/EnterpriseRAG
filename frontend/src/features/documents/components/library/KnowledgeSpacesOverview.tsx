import { type CSSProperties } from "react";
import { ChevronRight, Edit3, Folder, RotateCw, Trash2 } from "lucide-react";

import { ContextMetric, EmptyState, SpaceOverviewSkeleton } from "@/features/documents/components/library/DocumentPagePrimitives";
import {
  sortedSpaceOverviewRows,
  spaceAttentionCount,
  spaceHealth,
  type SpaceOverviewRow,
} from "@/features/documents/utils/documentPageUtils";
import type { DocumentOverview } from "@/types/api";
import type { GroupOption } from "@/lib/utils/groups";

type TreeRowStyle = CSSProperties & { "--space-depth": number };

type KnowledgeSpacesOverviewProps = {
  canCreateSpace: boolean;
  canManageSpaces: boolean;
  canOpenSpaces: boolean;
  deletingSpacePath: string | null;
  isLoading: boolean;
  onCreateSpace: () => void;
  onDeleteSpace: (space: GroupOption) => void;
  onEditSpace: (space: GroupOption) => void;
  onOpenSpace: (path: string) => void;
  onShowJobs: () => void;
  onShowTrash: () => void;
  overview: DocumentOverview | null;
  rows: SpaceOverviewRow[];
};

export function KnowledgeSpacesOverview({
  canCreateSpace,
  canManageSpaces,
  canOpenSpaces,
  deletingSpacePath,
  isLoading,
  onCreateSpace,
  onDeleteSpace,
  onEditSpace,
  onOpenSpace,
  onShowJobs,
  onShowTrash,
  overview,
  rows,
}: KnowledgeSpacesOverviewProps) {
  const currentCount = overview?.current_versions ?? 0;
  const attentionCount = overview?.needs_attention ?? 0;
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
        <ContextMetric label="Documents" value={String(overview?.library_documents ?? 0)} loading={isLoading} />
        <ContextMetric label="Current" value={String(currentCount)} loading={isLoading} tone="success" />
        <ContextMetric label="Needs attention" value={String(attentionCount)} loading={isLoading} />
        <ContextMetric label="Trash" value={String(overview?.trash ?? 0)} loading={isLoading} />
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
                <p>Current failed, unknown, and review-required documents across visible spaces.</p>
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
