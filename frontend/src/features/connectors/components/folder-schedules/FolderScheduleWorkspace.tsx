import type { FormEvent } from "react";
import { CalendarClock, Loader2 } from "lucide-react";

import { InlineMessage } from "@/components/layout/Common";
import {
  ClearanceSelect,
  FolderSnapshotReview,
  ScheduleListPanel,
  SelectField,
} from "@/features/connectors/components/folder-schedules/FolderSchedulePanels";
import {
  folderSnapshotLabel,
  summarizeFolderFiles,
  WORKSPACE_TIMEZONE,
  type FolderScheduleDraft,
} from "@/features/ingestion/state/folderIngest";
import type { ClearanceLevel, FolderSchedule } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";

const folderInputAttributes = { webkitdirectory: "", directory: "" };

type Props = {
  actionPending: boolean;
  clearanceOptions: ClearanceLevel[];
  createError: unknown;
  createFailed: boolean;
  draft: FolderScheduleDraft;
  formError: string | null;
  groupsLoading: boolean;
  inputResetKey: number;
  isSubmitting: boolean;
  pendingActionId: string | null;
  scheduleLoadError: string;
  schedules: FolderSchedule[];
  schedulesFailed: boolean;
  schedulesLoading: boolean;
  selectedFiles: File[];
  selection: ReturnType<typeof summarizeFolderFiles>;
  submittingLabel: string;
  submitLabel: string;
  writableSpacePaths: string[];
  onClearSnapshot: () => void;
  onDraftChange: (patch: Partial<FolderScheduleDraft>) => void;
  onFileSelection: (files: FileList | null) => void;
  onRemoveFile: (file: File) => void;
  onScheduleAction: (action: "pause" | "resume" | "cancel", id: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export function FolderScheduleWorkspace({
  actionPending,
  clearanceOptions,
  createError,
  createFailed,
  draft,
  formError,
  groupsLoading,
  inputResetKey,
  isSubmitting,
  pendingActionId,
  scheduleLoadError,
  schedules,
  schedulesFailed,
  schedulesLoading,
  selectedFiles,
  selection,
  submittingLabel,
  submitLabel,
  writableSpacePaths,
  onClearSnapshot,
  onDraftChange,
  onFileSelection,
  onRemoveFile,
  onScheduleAction,
  onSubmit,
}: Props) {
  return (
    <>
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

      <form onSubmit={onSubmit} className="space-y-5">
        <div className="rounded-lg border border-surface-border bg-surface-container-low p-4">
          <label className="sv-field">
            <span className="sv-label">Folder Snapshot</span>
            <input
              key={inputResetKey}
              type="file"
              multiple
              {...folderInputAttributes}
              onChange={(event) => onFileSelection(event.currentTarget.files)}
              className="sv-input file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-label-md file:font-bold file:text-on-primary"
            />
            <small className="text-secondary">Choose a local folder to upload a point-in-time copy. Future edits require a new snapshot.</small>
          </label>
          {selectedFiles.length > 0 ? (
            <FolderSnapshotReview
              label={folderSnapshotLabel(selection.entries)}
              onClear={onClearSnapshot}
              onRemove={onRemoveFile}
              selection={selection}
            />
          ) : (
            <p className="mt-3 rounded-md border border-dashed border-surface-border bg-surface px-3 py-2 text-body-sm text-secondary">No folder selected.</p>
          )}
        </div>

        <div className="grid items-start gap-4 md:grid-cols-2">
          <label className="sv-field">
            <span className="sv-label">Schedule Name</span>
            <input value={draft.name} onChange={(event) => onDraftChange({ name: event.target.value })} placeholder="Finance policies off-peak sync" className="sv-input" />
            <small className="text-secondary">Used to identify this ingestion schedule in activity history.</small>
          </label>
          <SelectField label="Knowledge Space" value={draft.groupPath} onChange={(groupPath) => onDraftChange({ groupPath })} options={["", ...writableSpacePaths]} emptyLabel={groupsLoading ? "Loading spaces" : "Select ingestion space"} helper="Files inherit this space for retrieval filtering." />
          <ClearanceSelect value={draft.clearanceLevel} onChange={(clearanceLevel) => onDraftChange({ clearanceLevel })} options={clearanceOptions} />
          <label className="sv-field">
            <span className="sv-label">Effective Date <span className="font-normal text-secondary">(optional)</span></span>
            <input type="date" value={draft.effectiveDate} onChange={(event) => onDraftChange({ effectiveDate: event.target.value })} className="sv-input" />
            <small className="text-secondary">Optional start date applied to ingested files.</small>
          </label>
          <label className="sv-field">
            <span className="sv-label">Expiry Date</span>
            <input type="date" value={draft.expiryDate} onChange={(event) => onDraftChange({ expiryDate: event.target.value })} className="sv-input" />
            <small className="text-secondary">Leave blank unless these files should expire from current use.</small>
          </label>
        </div>

        <label className="sv-field">
          <span className="sv-label">Start Time ({WORKSPACE_TIMEZONE})</span>
          <input type="datetime-local" value={draft.scheduledAt} onChange={(event) => onDraftChange({ scheduledAt: event.target.value })} className="sv-input" />
          <small className="text-secondary">Queue this snapshot at the selected local time.</small>
        </label>
        <label className="sv-field">
          <span className="sv-label">Description</span>
          <textarea value={draft.description} onChange={(event) => onDraftChange({ description: event.target.value })} placeholder="Optional shared context for staged folder files" className="sv-input min-h-20" />
          <small className="text-secondary">Shared context attached to every staged folder file.</small>
        </label>

        {formError ? <InlineMessage tone="warning">{formError}</InlineMessage> : null}
        {createFailed ? <InlineMessage tone="error">{errorMessage(createError, "Unable to schedule ingestion.")}</InlineMessage> : null}
        <button type="submit" disabled={isSubmitting || writableSpacePaths.length === 0} className="sv-action-primary w-full">
          {isSubmitting ? <Loader2 className="animate-spin" size={18} /> : <CalendarClock size={18} />}
          {isSubmitting ? submittingLabel : submitLabel}
        </button>
      </form>

      <ScheduleListPanel
        emptyMessage="No folder source schedules yet. Create one above to defer ingestion into an off-peak window."
        isError={schedulesFailed}
        isLoading={schedulesLoading}
        loadError={scheduleLoadError}
        pendingActionId={pendingActionId}
        pendingActionPending={actionPending}
        schedules={schedules}
        title="Folder source schedules"
        onAction={onScheduleAction}
      />
    </>
  );
}
