import { useState, type JSX } from "react";
import { useQuery } from "@tanstack/react-query";
import { Ban, ChevronDown, ChevronRight, FileText, FolderOpen, PauseCircle, PlayCircle, X } from "lucide-react";

import { folderIngestApi } from "@/lib/api/contracts";
import { clearanceLevelDescription, clearanceLevelLabel } from "@/lib/auth/authz";
import { InlineMessage } from "@/components/layout/Common";
import { formatFolderCount, summarizeFolderFiles, type FolderFileEntry } from "@/features/ingestion/state/folderIngest";
import { formatFileSize } from "@/features/upload/state/pdfUploadBatch";
import { errorMessage } from "@/lib/utils/format";
import { formatDateTime, formatLatestRun, sourceTypeLabel } from "@/features/connectors/utils/connectorPanelUtils";
import type { ClearanceLevel, FolderRun, FolderSchedule, FolderScheduleStatus } from "@/types/api";

export function ScheduleListPanel({ emptyMessage, isError, isLoading, loadError, onAction, pendingActionId, pendingActionPending, schedules, title }: ScheduleListPanelProps) {
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

export function FolderSnapshotReview({ label, onClear, onRemove, selection }: FolderSnapshotReviewProps) {
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
        <button type="button" onClick={onClear} className="min-h-11 rounded-md border border-surface-border bg-surface-container-low px-3 py-2 text-label-md font-bold text-on-surface hover:border-primary">
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
    <li className="folder-snapshot-file-row flex items-center gap-3 border-b border-surface-border px-3 py-2 last:border-b-0">
      <FileText className="shrink-0 text-primary" size={16} />
      <span className="folder-snapshot-file-copy min-w-0 flex-1">
        <strong className="block truncate text-body-md text-on-surface">{entry.file.name}</strong>
        <small className="block truncate text-secondary">{entry.relativePath}</small>
      </span>
      <span className="folder-snapshot-file-size shrink-0 text-label-md text-secondary">{formatFileSize(entry.file.size)}</span>
      <span className={`${entry.supported ? "sv-pill sv-pill-success" : "sv-pill"} folder-snapshot-file-status shrink-0`}>{entry.supported ? "Supported" : "Skipped"}</span>
      <button
        type="button"
        onClick={() => onRemove(entry.file)}
        className="folder-snapshot-file-remove inline-flex h-11 w-11 shrink-0 items-center justify-center rounded text-secondary hover:bg-surface-container-low hover:text-on-surface"
        aria-label={`Remove ${entry.file.name}`}
      >
        <X size={15} />
      </button>
    </li>
  );
}

export function SelectField({ emptyLabel, helper, label, onChange, optionLabels = {}, options, value }: SelectProps) {
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

export function ClearanceSelect({ onChange, options, value }: ClearanceSelectProps) {
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
        <div className="flex flex-wrap gap-2">
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
    <button type="button" disabled={disabled} onClick={onClick} className="min-h-11 rounded-md border border-surface-border bg-surface px-3 py-2 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
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

function ScheduleStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-label-md font-bold uppercase tracking-wide text-secondary">{label}</dt>
      <dd className="mt-0.5 text-on-surface">{value}</dd>
    </div>
  );
}

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
