import type { CreateLocalFolderScheduleRequest, CreateSnapshotScheduleRequest } from "../api/contracts";
import { defaultClearanceLevel } from "../authz";
import type { ClearanceLevel, ConnectorDeletionPolicy, ConnectorIngestionMode, ConnectorType, FolderScheduleType, RecurrenceWindow } from "../types/api";

export const WORKSPACE_TIMEZONE = "Asia/Karachi";
const FOLDER_SNAPSHOT_MAX_SUPPORTED_FILES = 100;
const FOLDER_SNAPSHOT_MAX_BYTES = 5 * 1024 * 1024 * 1024;

type FolderSourceMode = "snapshot" | "local_folder" | "connector";
export type FolderIngestPanelVariant = "folder_sources" | "database_connectors";

export interface FolderFileEntry {
  file: File;
  relativePath: string;
  supported: boolean;
}

export interface FolderSelectionSummary {
  entries: FolderFileEntry[];
  supportedEntries: FolderFileEntry[];
  unsupportedEntries: FolderFileEntry[];
  supportedBytes: number;
  validationMessages: string[];
}

export interface FolderScheduleDraft {
  sourceMode: FolderSourceMode;
  name: string;
  groupPath: string;
  clearanceLevel: ClearanceLevel;
  effectiveDate: string;
  expiryDate: string;
  description: string;
  scheduleType: FolderScheduleType;
  scheduledAt: string;
  timezone: string;
  recurrenceDays: number[];
  recurrenceStartTime: string;
  recurrenceEndTime: string;
  folderPath: string;
  connectorProfileId: string;
  connectorType: ConnectorType;
  connectorQuery: string;
  connectorIdentityFields: string;
  connectorIngestionMode: ConnectorIngestionMode;
  connectorDeletionPolicy: ConnectorDeletionPolicy;
  connectorBatchSize: number;
  connectorRowLimit: number;
}

export function defaultFolderScheduleDraft(effectiveDate: string): FolderScheduleDraft {
  return {
    sourceMode: "snapshot",
    name: "",
    groupPath: "",
    clearanceLevel: defaultClearanceLevel,
    effectiveDate,
    expiryDate: "",
    description: "",
    scheduleType: "one_time",
    scheduledAt: "",
    timezone: WORKSPACE_TIMEZONE,
    recurrenceDays: [0, 1, 2, 3, 4, 5, 6],
    recurrenceStartTime: "22:00",
    recurrenceEndTime: "06:00",
    folderPath: "",
    connectorProfileId: "",
    connectorType: "sql_server",
    connectorQuery: "",
    connectorIdentityFields: "",
    connectorIngestionMode: "json_snapshot",
    connectorDeletionPolicy: "keep_deleted_documents",
    connectorBatchSize: 500,
    connectorRowLimit: 5000,
  };
}

export function defaultFolderScheduleDraftForVariant(effectiveDate: string, variant: FolderIngestPanelVariant): FolderScheduleDraft {
  const draft = defaultFolderScheduleDraft(effectiveDate);
  if (variant === "database_connectors") {
    return { ...draft, sourceMode: "connector" };
  }
  return { ...draft, sourceMode: "snapshot", scheduleType: "one_time" };
}

export function isScheduleVisibleForPanelVariant(sourceType: string, variant: FolderIngestPanelVariant): boolean {
  if (variant === "database_connectors") return false;
  return sourceType === "local_folder" || sourceType === "snapshot";
}

export function summarizeFolderFiles(files: File[]): FolderSelectionSummary {
  const entries = files.map((file) => {
    const relativePath = relativePathForFile(file);
    return {
      file,
      relativePath,
      supported: isSupportedFolderDocument(file, relativePath),
    };
  });
  const supportedEntries = entries.filter((entry) => entry.supported);
  const unsupportedEntries = entries.filter((entry) => !entry.supported);
  const supportedBytes = supportedEntries.reduce((total, entry) => total + entry.file.size, 0);
  const validationMessages: string[] = [];
  if (supportedEntries.length === 0 && entries.length > 0) {
    validationMessages.push("The selected folder does not contain any PDF, DOCX, JPG, PNG, or JSON files.");
  }
  if (supportedEntries.length > FOLDER_SNAPSHOT_MAX_SUPPORTED_FILES) {
    validationMessages.push(`Folder snapshots cannot exceed ${FOLDER_SNAPSHOT_MAX_SUPPORTED_FILES} supported files.`);
  }
  if (supportedBytes > FOLDER_SNAPSHOT_MAX_BYTES) {
    validationMessages.push("Folder snapshots cannot exceed 5 GB of supported files.");
  }
  return { entries, supportedEntries, unsupportedEntries, supportedBytes, validationMessages };
}

export function relativePathForFile(file: File): string {
  const browserPath = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
  return sanitizeRelativePath(browserPath || file.name);
}

export function buildRecurrence(draft: FolderScheduleDraft): RecurrenceWindow | null {
  if (draft.scheduleType !== "recurring") return null;
  return {
    days_of_week: draft.recurrenceDays,
    start_time: draft.recurrenceStartTime,
    end_time: draft.recurrenceEndTime,
  };
}

export function buildSnapshotScheduleRequest(draft: FolderScheduleDraft, entries: FolderFileEntry[]): CreateSnapshotScheduleRequest {
  return {
    files: entries.map((entry) => entry.file),
    relative_paths: entries.map((entry) => entry.relativePath),
    name: draft.name.trim(),
    group_path: draft.groupPath.trim(),
    clearance_level: draft.clearanceLevel,
    effective_date: draft.effectiveDate || null,
    expiry_date: draft.expiryDate || null,
    description: draft.description.trim() || null,
    schedule_type: draft.scheduleType,
    timezone: draft.timezone,
    scheduled_at: draft.scheduleType === "one_time" ? draft.scheduledAt || null : null,
    recurrence: buildRecurrence(draft),
  };
}

export function buildLocalFolderScheduleRequest(draft: FolderScheduleDraft): CreateLocalFolderScheduleRequest {
  return {
    name: draft.name.trim(),
    path: draft.folderPath.trim(),
    group_path: draft.groupPath.trim(),
    clearance_level: draft.clearanceLevel,
    effective_date: draft.effectiveDate || null,
    expiry_date: draft.expiryDate || null,
    description: draft.description.trim() || null,
    schedule_type: draft.scheduleType,
    timezone: draft.timezone,
    scheduled_at: draft.scheduleType === "one_time" ? draft.scheduledAt || null : null,
    recurrence: buildRecurrence(draft),
  };
}

export function identityFieldsFromDraft(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

export function formatFolderCount(count: number, singular: string): string {
  return `${count} ${singular}${count === 1 ? "" : "s"}`;
}

export function folderSnapshotLabel(entries: FolderFileEntry[]): string {
  const roots = [...new Set(entries.map((entry) => entry.relativePath.split("/")[0]).filter(Boolean))].sort();
  if (roots.length === 0) return "No folder selected";
  if (roots.length === 1) return roots[0];
  return `${roots.length} folders selected`;
}

function isSupportedFolderDocument(file: File, relativePath: string): boolean {
  const name = (relativePath || file.name).toLowerCase();
  return (
    file.type === "application/pdf"
    || file.type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    || file.type === "image/jpeg"
    || file.type === "image/png"
    || file.type === "application/json"
    || name.endsWith(".pdf")
    || name.endsWith(".docx")
    || name.endsWith(".jpg")
    || name.endsWith(".jpeg")
    || name.endsWith(".png")
    || name.endsWith(".json")
  );
}

function sanitizeRelativePath(path: string): string {
  return path.replace(/\\/g, "/").replace(/^\/+/, "").split("/").filter((part) => part && part !== "." && part !== "..").join("/");
}
