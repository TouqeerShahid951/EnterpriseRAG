import { useMemo, useState, type ChangeEvent, type FormEvent, type InputHTMLAttributes } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CalendarClock, ChevronDown, ChevronRight, Database, FileText, FolderOpen, Loader2, PauseCircle, PlayCircle } from "lucide-react";

import { folderIngestApi } from "../../api/contracts";
import { InlineMessage } from "../layout/Common";
import {
  buildMinioPrefixScheduleRequest,
  buildSnapshotScheduleRequest,
  defaultFolderScheduleDraft,
  FOLDER_SNAPSHOT_MAX_SUPPORTED_FILES,
  formatFolderCount,
  FOLDER_SNAPSHOT_MAX_BYTES,
  summarizeFolderFiles,
  WORKSPACE_TIMEZONE,
  type FolderScheduleDraft,
} from "../../state/folderIngest";
import { formatFileSize } from "../../state/pdfUploadBatch";
import type { DocType, FolderRun, FolderSchedule, FolderScheduleStatus } from "../../types/api";
import { errorMessage } from "../../utils/format";

const folderPickerAttributes = {
  webkitdirectory: "",
  directory: "",
} as InputHTMLAttributes<HTMLInputElement> & { webkitdirectory: string; directory: string };

const dayOptions = [
  { value: 0, label: "Mon" },
  { value: 1, label: "Tue" },
  { value: 2, label: "Wed" },
  { value: 3, label: "Thu" },
  { value: 4, label: "Fri" },
  { value: 5, label: "Sat" },
  { value: 6, label: "Sun" },
];

export function FolderIngestPanel({ docTypes, groupsLoading, writableSpacePaths }: Props) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<FolderScheduleDraft>(() => defaultFolderScheduleDraft(""));
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const selection = useMemo(() => summarizeFolderFiles(selectedFiles), [selectedFiles]);
  const schedulesQuery = useQuery({
    queryKey: ["folder-ingest", "schedules"],
    queryFn: folderIngestApi.listSchedules,
    retry: false,
  });
  const createMutation = useMutation({
    mutationFn: () => {
      if (draft.sourceMode === "snapshot") {
        return folderIngestApi.createSnapshot(buildSnapshotScheduleRequest(draft, selection.entries));
      }
      return folderIngestApi.createMinioPrefix(buildMinioPrefixScheduleRequest(draft));
    },
    onSuccess: () => {
      setSelectedFiles([]);
      setFormError(null);
      setDraft((current) => ({ ...current, name: "", bucket: "", prefix: "" }));
      void queryClient.invalidateQueries({ queryKey: ["folder-ingest", "schedules"] });
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

  function handleFolderChange(event: ChangeEvent<HTMLInputElement>) {
    setSelectedFiles(Array.from(event.target.files ?? []));
    event.target.value = "";
  }

  function toggleDay(day: number) {
    const next = draft.recurrenceDays.includes(day)
      ? draft.recurrenceDays.filter((value) => value !== day)
      : [...draft.recurrenceDays, day].sort();
    patchDraft({ recurrenceDays: next });
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

  const isSubmitting = createMutation.isPending;
  const visibleSchedules = schedulesQuery.data?.items ?? [];
  const snapshotDisabled = isSubmitting || draft.sourceMode !== "snapshot";

  return (
    <section className="sv-panel p-5" aria-labelledby="folder-ingest-title">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4 border-b border-surface-border pb-4">
        <div>
          <p className="sv-eyebrow">Scheduled Folder Ingestion</p>
          <h2 id="folder-ingest-title" className="sv-section-title">Attach a folder for off-peak indexing</h2>
          <p className="mt-1 text-body-md text-on-surface-variant">
            Store and scan files now, then enqueue parsing, embedding, and indexing when the selected schedule is due.
          </p>
        </div>
        <span className="sv-pill">Timezone: {WORKSPACE_TIMEZONE}</span>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="grid gap-3 md:grid-cols-2" role="radiogroup" aria-label="Folder source mode">
          <SourceModeButton
            active={draft.sourceMode === "snapshot"}
            detail="Pick a local folder once. Browser access is a snapshot, not a watched folder."
            icon={<FolderOpen size={18} />}
            label="Browser folder"
            onClick={() => patchDraft({ sourceMode: "snapshot", scheduleType: "one_time" })}
          />
          <SourceModeButton
            active={draft.sourceMode === "minio_prefix"}
            detail="Sync a recurring S3/MinIO bucket prefix using backend service credentials."
            icon={<Database size={18} />}
            label="S3/MinIO prefix"
            onClick={() => patchDraft({ sourceMode: "minio_prefix" })}
          />
        </div>

        {draft.sourceMode === "snapshot" ? (
          <div className="rounded-lg border border-surface-border bg-surface-container-low p-4">
            <label className="sv-field">
              <span className="sv-label">Folder Snapshot</span>
              <input
                {...folderPickerAttributes}
                type="file"
                multiple
                disabled={snapshotDisabled}
                onChange={handleFolderChange}
                className="sv-input file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-bold file:text-on-primary"
              />
              <small className="text-secondary">
                Directory picker preserves relative paths as metadata. Limit: {FOLDER_SNAPSHOT_MAX_SUPPORTED_FILES} supported files or {formatFileSize(FOLDER_SNAPSHOT_MAX_BYTES)} total.
              </small>
            </label>
            {selectedFiles.length > 0 ? (
              <div className="mt-3 rounded-md border border-surface-border bg-surface px-3 py-2 text-body-md text-on-surface-variant">
                <strong className="text-on-surface">{formatFolderCount(selection.supportedEntries.length, "supported file")}</strong>
                {" "}selected across {formatFolderCount(selection.entries.length, "folder item")}; {formatFileSize(selection.supportedBytes)} will be staged.
                {selection.unsupportedEntries.length > 0 ? (
                  <span className="block text-secondary">{formatFolderCount(selection.unsupportedEntries.length, "unsupported item")} will be recorded as skipped.</span>
                ) : null}
              </div>
            ) : null}
            {selection.validationMessages.map((message) => <InlineMessage key={message} tone="warning">{message}</InlineMessage>)}
          </div>
        ) : (
          <div className="grid gap-4 rounded-lg border border-surface-border bg-surface-container-low p-4 md:grid-cols-2">
            <label className="sv-field">
              <span className="sv-label">Bucket</span>
              <input value={draft.bucket} onChange={(event) => patchDraft({ bucket: event.target.value })} placeholder="enterprise-docs" className="sv-input" />
            </label>
            <label className="sv-field">
              <span className="sv-label">Prefix</span>
              <input value={draft.prefix} onChange={(event) => patchDraft({ prefix: event.target.value })} placeholder="finance/policies/" className="sv-input" />
            </label>
            <p className="md:col-span-2 text-body-md text-on-surface-variant">
              Credentials stay on the backend. This stores only bucket, prefix, schedule, and metadata.
            </p>
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <label className="sv-field">
            <span className="sv-label">Schedule Name</span>
            <input value={draft.name} onChange={(event) => patchDraft({ name: event.target.value })} placeholder="Finance policies off-peak sync" className="sv-input" />
          </label>
          <SelectField label="Knowledge Space" value={draft.groupPath} onChange={(value) => patchDraft({ groupPath: value })} options={["", ...writableSpacePaths]} emptyLabel={groupsLoading ? "Loading spaces" : "Select ingestion space"} />
          <label className="sv-field">
            <span className="sv-label">Effective Date <span className="font-normal text-secondary">(optional)</span></span>
            <input type="date" value={draft.effectiveDate} onChange={(event) => patchDraft({ effectiveDate: event.target.value })} className="sv-input" />
          </label>
          <label className="sv-field">
            <span className="sv-label">Expiry Date</span>
            <input type="date" value={draft.expiryDate} onChange={(event) => patchDraft({ expiryDate: event.target.value })} className="sv-input" />
          </label>
          <SelectField label="Document Type" value={draft.docType} onChange={(value) => patchDraft({ docType: value as DocType })} options={docTypes} />
          <SelectField
            label="Schedule Type"
            value={draft.scheduleType}
            onChange={(value) => patchDraft({ scheduleType: value as FolderScheduleDraft["scheduleType"] })}
            options={draft.sourceMode === "snapshot" ? ["one_time"] : ["one_time", "recurring"]}
          />
        </div>

        {draft.scheduleType === "one_time" ? (
          <label className="sv-field">
            <span className="sv-label">Start Time ({WORKSPACE_TIMEZONE})</span>
            <input type="datetime-local" value={draft.scheduledAt} onChange={(event) => patchDraft({ scheduledAt: event.target.value })} className="sv-input" />
          </label>
        ) : (
          <div className="grid gap-4 rounded-lg border border-surface-border bg-surface-container-low p-4 md:grid-cols-[1fr_auto_auto]">
            <fieldset>
              <legend className="sv-label mb-2">Recurring Days</legend>
              <div className="flex flex-wrap gap-2">
                {dayOptions.map((day) => (
                  <label key={day.value} className="inline-flex items-center gap-2 rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-label-md font-bold text-on-surface">
                    <input type="checkbox" checked={draft.recurrenceDays.includes(day.value)} onChange={() => toggleDay(day.value)} />
                    {day.label}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="sv-field">
              <span className="sv-label">Window Start</span>
              <input type="time" value={draft.recurrenceStartTime} onChange={(event) => patchDraft({ recurrenceStartTime: event.target.value })} className="sv-input" />
            </label>
            <label className="sv-field">
              <span className="sv-label">Window End</span>
              <input type="time" value={draft.recurrenceEndTime} onChange={(event) => patchDraft({ recurrenceEndTime: event.target.value })} className="sv-input" />
            </label>
          </div>
        )}

        <label className="sv-field">
          <span className="sv-label">Description</span>
          <textarea value={draft.description} onChange={(event) => patchDraft({ description: event.target.value })} placeholder="Optional shared context for staged folder files" className="sv-input min-h-20" />
        </label>

        {formError ? <InlineMessage tone="warning">{formError}</InlineMessage> : null}
        {createMutation.isError ? <InlineMessage tone="error">{errorMessage(createMutation.error, "Unable to create folder ingestion schedule.")}</InlineMessage> : null}
        <button type="submit" disabled={isSubmitting || writableSpacePaths.length === 0} className="sv-action-primary w-full">
          {isSubmitting ? <Loader2 className="animate-spin" size={18} /> : <CalendarClock size={18} />}
          {isSubmitting ? "Creating folder schedule" : "Create folder ingestion schedule"}
        </button>
      </form>

      <div className="mt-6 border-t border-surface-border pt-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="sv-section-title">Folder schedules</h3>
          <p className="text-label-md text-secondary">{visibleSchedules.length} visible</p>
        </div>
        {schedulesQuery.isError ? <InlineMessage tone="error">{errorMessage(schedulesQuery.error, "Unable to load folder schedules.")}</InlineMessage> : null}
        {schedulesQuery.isLoading ? <p className="mt-3 text-body-md text-secondary">Loading schedules...</p> : null}
        {!schedulesQuery.isLoading && visibleSchedules.length === 0 ? (
          <p className="mt-3 rounded-md border border-surface-border bg-surface-container-low p-3 text-body-md text-on-surface-variant">
            No folder schedules yet. Create one above to defer ingestion into an off-peak window.
          </p>
        ) : null}
        <div className="mt-3 grid gap-3">
          {visibleSchedules.slice(0, 5).map((schedule) => (
            <ScheduleCard key={schedule.id} schedule={schedule} pendingAction={actionMutation.variables?.id === schedule.id && actionMutation.isPending} onAction={(action) => actionMutation.mutate({ action, id: schedule.id })} />
          ))}
        </div>
      </div>
    </section>
  );
}

function SourceModeButton({ active, detail, icon, label, onClick }: SourceModeButtonProps) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`rounded-lg border p-4 text-left transition ${active ? "border-primary bg-primary/10" : "border-surface-border bg-surface-container-low hover:border-primary/50"}`}
    >
      <span className="flex items-center gap-2 text-body-md font-extrabold text-on-surface">
        <span className="text-primary">{icon}</span>
        {label}
      </span>
      <span className="mt-1 block text-body-md text-on-surface-variant">{detail}</span>
    </button>
  );
}

function SelectField({ emptyLabel, label, onChange, options, value }: SelectProps) {
  return (
    <label className="sv-field">
      <span className="sv-label">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} className="sv-select">
        {options.map((option) => <option key={option || "empty"} value={option}>{option || emptyLabel || option}</option>)}
      </select>
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
            {schedule.source_type === "snapshot" ? "Browser snapshot" : "S3/MinIO prefix"} · {schedule.group_path} · {schedule.schedule_type === "recurring" ? "Recurring window" : "One-time start"}
          </p>
        </div>
        <div className="flex gap-2">
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
                <span>{runItemsQuery.data?.total ?? 0} files</span>
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
    <button type="button" disabled={disabled} onClick={onClick} className="rounded-md border border-surface-border bg-surface px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
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

function validateDraft(draft: FolderScheduleDraft, selection: ReturnType<typeof summarizeFolderFiles>, writableSpacePaths: string[]): string | null {
  if (!draft.name.trim()) return "Enter a schedule name.";
  if (!draft.groupPath || !writableSpacePaths.includes(draft.groupPath)) return "Select a writable Knowledge Space.";
  if (draft.scheduleType === "one_time" && !draft.scheduledAt) return "Choose the one-time start time.";
  if (draft.scheduleType === "recurring" && draft.recurrenceDays.length === 0) return "Select at least one recurring day.";
  if (draft.sourceMode === "snapshot") {
    if (selection.entries.length === 0) return "Choose a folder snapshot.";
    if (selection.validationMessages.length > 0) return selection.validationMessages[0] ?? "Selected folder is invalid.";
  }
  if (draft.sourceMode === "minio_prefix" && (!draft.bucket.trim() || !draft.prefix.trim())) {
    return "Enter both MinIO bucket and prefix.";
  }
  return null;
}

function formatDateTime(value: string | null): string {
  if (!value) return "Not scheduled";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: WORKSPACE_TIMEZONE }).format(new Date(value));
}

function formatLatestRun(schedule: FolderSchedule): string {
  if (!schedule.latest_run) return "No runs";
  const run = schedule.latest_run;
  return `${run.status}: ${run.queued_count} queued, ${run.skipped_count} skipped`;
}

type Props = {
  docTypes: DocType[];
  groupsLoading: boolean;
  writableSpacePaths: string[];
};

type SelectProps = {
  emptyLabel?: string;
  label: string;
  onChange: (value: string) => void;
  options: string[];
  value: string;
};

type SourceModeButtonProps = {
  active: boolean;
  detail: string;
  icon: JSX.Element;
  label: string;
  onClick: () => void;
};

type ScheduleCardProps = {
  onAction: (action: "pause" | "resume" | "cancel") => void;
  pendingAction: boolean;
  schedule: FolderSchedule;
};

type IconActionProps = {
  disabled: boolean;
  icon: JSX.Element;
  label: string;
  onClick: () => void;
};
