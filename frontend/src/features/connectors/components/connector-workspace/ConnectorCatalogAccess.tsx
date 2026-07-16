import { Ban, CheckCircle2, Loader2, Plus, Save, Sparkles, X } from "lucide-react";

import { InlineMessage } from "@/components/layout/Common";
import { ClearanceSelect, SelectField } from "@/features/connectors/components/folder-schedules/FolderSchedulePanels";
import { SchemaReviewStat } from "@/features/connectors/components/connector-workspace/ConnectorCatalogPrimitives";
import {
  catalogAccessStateDescription,
  catalogAccessStateLabel,
  schemaCatalogAllowedRelationships,
  schemaCatalogReviewStats,
  type SchemaCatalogRelationship,
} from "@/features/connectors/utils/connectorPanelUtils";
import type { ClearanceLevel, ConnectorSchemaCatalogStatus } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";

type CatalogAccessPanelProps = {
  catalogStatus: string;
  clearanceLevel: ClearanceLevel;
  clearanceOptions: ClearanceLevel[];
  groupOptions: string[];
  ownerGroupPath: string;
  shareCandidate: string;
  shareOptions: string[];
  sharedGroupPaths: string[];
  onAddSharedGroupPath: (path: string) => void;
  onClearanceChange: (value: ClearanceLevel) => void;
  onOwnerGroupPathChange: (value: string) => void;
  onShareCandidateChange: (value: string) => void;
  onSharedGroupPathsChange: (value: string[]) => void;
};

export function CatalogAccessPanel({
  catalogStatus,
  clearanceLevel,
  clearanceOptions,
  groupOptions,
  ownerGroupPath,
  shareCandidate,
  shareOptions,
  sharedGroupPaths,
  onAddSharedGroupPath,
  onClearanceChange,
  onOwnerGroupPathChange,
  onShareCandidateChange,
  onSharedGroupPathsChange,
}: CatalogAccessPanelProps) {
  return (
    <section className="space-y-4 rounded-md border border-surface-border bg-surface p-3">
      <div>
        <p className="sv-label">Live DB Access</p>
        <strong className="mt-1 block text-body-md text-on-surface">{catalogAccessStateLabel(catalogStatus)}</strong>
        <p className="mt-1 text-body-md text-on-surface-variant">{catalogAccessStateDescription(catalogStatus)}</p>
      </div>
      <SelectField label="Owner Space" value={ownerGroupPath} onChange={onOwnerGroupPathChange} options={groupOptions} emptyLabel="Select space" helper="Primary owner for this review." />
      <div className="grid gap-2 border-t border-surface-border pt-3">
        <span className="sv-label">Shared Spaces</span>
        <div className="flex gap-2">
          <select value={shareCandidate} onChange={(event) => onShareCandidateChange(event.target.value)} className="sv-select min-w-0 flex-1">
            <option value="">Select space</option>
            {shareOptions.map((path) => <option key={path} value={path}>{path}</option>)}
          </select>
          <button type="button" disabled={!shareCandidate} onClick={() => onAddSharedGroupPath(shareCandidate)} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50" aria-label="Add shared Knowledge Space">
            <Plus size={14} />
          </button>
        </div>
        {sharedGroupPaths.length ? (
          <div className="flex flex-wrap gap-1">
            {sharedGroupPaths.map((path) => (
              <span key={path} className="inline-flex max-w-full items-center gap-1 rounded-md border border-surface-border px-2 py-1 text-label-md text-on-surface">
                <span className="truncate">{path}</span>
                <button type="button" onClick={() => onSharedGroupPathsChange(sharedGroupPaths.filter((value) => value !== path))} aria-label={`Remove ${path}`} className="text-secondary hover:text-error-red">
                  <X size={13} />
                </button>
              </span>
            ))}
          </div>
        ) : <small className="text-secondary">Owner only</small>}
      </div>
      <ClearanceSelect value={clearanceLevel} onChange={onClearanceChange} options={clearanceOptions} />
    </section>
  );
}

type CatalogReviewActionsProps = {
  approvalWarnings: string[];
  canContinueAiEnrichment: boolean;
  catalogStatus: string;
  isSaving: boolean;
  mutationError: unknown;
  ownerGroupPath: string;
  relationships: SchemaCatalogRelationship[];
  reviewStats: ReturnType<typeof schemaCatalogReviewStats>;
  onClose: () => void;
  onContinueAiEnrichment: () => void;
  onEditAccess: () => void;
  onSave: (status?: ConnectorSchemaCatalogStatus) => void;
};

export function CatalogReviewActions({
  approvalWarnings,
  canContinueAiEnrichment,
  catalogStatus,
  isSaving,
  mutationError,
  ownerGroupPath,
  relationships,
  reviewStats,
  onClose,
  onContinueAiEnrichment,
  onEditAccess,
  onSave,
}: CatalogReviewActionsProps) {
  return (
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
          <strong className="mt-1 block text-body-md text-on-surface">{catalogAccessStateLabel(catalogStatus)}</strong>
          <small className="mt-1 block text-secondary">{catalogAccessStateDescription(catalogStatus)}</small>
        </div>
        <button type="button" onClick={onEditAccess} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-label-md font-bold text-on-surface hover:border-primary">
          Edit Access Settings
        </button>
        {mutationError ? <InlineMessage tone="error">{errorMessage(mutationError, "Unable to save database access review.")}</InlineMessage> : null}
        {canContinueAiEnrichment ? (
          <button type="button" disabled={isSaving} onClick={onContinueAiEnrichment} className="sv-action-secondary justify-center disabled:opacity-50">
            <Sparkles size={16} />
            Continue AI Enrichment
          </button>
        ) : null}
        <button type="button" disabled={isSaving || !ownerGroupPath} onClick={() => onSave()} className="sv-action-secondary justify-center disabled:opacity-50">
          {isSaving ? <Loader2 className="animate-spin" size={16} /> : <Save size={16} />}
          Save Review
        </button>
        <button type="button" disabled={isSaving || !ownerGroupPath} onClick={() => onSave("approved")} className="sv-action-primary justify-center disabled:opacity-50">
          {isSaving ? <Loader2 className="animate-spin" size={16} /> : <CheckCircle2 size={16} />}
          Enable Live DB Access
        </button>
        {catalogStatus === "approved" ? (
          <button type="button" disabled={isSaving} onClick={() => onSave("disabled")} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-label-md font-bold text-error-red hover:border-error-red disabled:opacity-50">
            <span className="inline-flex items-center justify-center gap-2"><Ban size={16} />Disable Live DB Access</span>
          </button>
        ) : null}
        <button type="button" onClick={onClose} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-label-md font-bold text-on-surface hover:border-primary">
          Close
        </button>
      </div>
    </aside>
  );
}
