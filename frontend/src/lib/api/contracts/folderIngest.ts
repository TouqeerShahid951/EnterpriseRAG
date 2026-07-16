import type {
  ClearanceLevel,
  ConnectorDeletionPolicy,
  ConnectorIngestionMode,
  FolderRun,
  FolderRunItem,
  FolderSchedule,
  FolderScheduleType,
  RecurrenceWindow,
} from "@/types/api";
import { apiClient } from "./apiClient";

export interface CreateSnapshotScheduleRequest {
  files: File[];
  relative_paths: string[];
  name: string;
  group_path: string;
  clearance_level?: ClearanceLevel | null;
  effective_date?: string | null;
  expiry_date?: string | null;
  doc_type?: string | null;
  description?: string | null;
  schedule_type: FolderScheduleType;
  timezone: string;
  scheduled_at?: string | null;
  recurrence?: RecurrenceWindow | null;
}

export interface CreateLocalFolderScheduleRequest {
  name: string;
  path: string;
  group_path: string;
  clearance_level?: ClearanceLevel | null;
  effective_date?: string | null;
  expiry_date?: string | null;
  doc_type?: string | null;
  description?: string | null;
  schedule_type: FolderScheduleType;
  timezone: string;
  scheduled_at?: string | null;
  recurrence?: RecurrenceWindow | null;
}

interface LocalFolderDirectory {
  name: string;
  path: string;
  has_children: boolean;
}

export interface LocalFolderListResponse {
  root_path: string;
  current_path: string;
  parent_path?: string | null;
  items: LocalFolderDirectory[];
}

export interface CreateConnectorScheduleRequest {
  name: string;
  connector_profile_id: string;
  selection: Record<string, unknown>;
  identity_fields: string[];
  ingestion_mode: ConnectorIngestionMode;
  deletion_policy: ConnectorDeletionPolicy;
  batch_size: number;
  row_limit: number;
  group_path: string;
  clearance_level?: ClearanceLevel | null;
  effective_date?: string | null;
  expiry_date?: string | null;
  doc_type?: string | null;
  description?: string | null;
  schedule_type: FolderScheduleType;
  timezone: string;
  scheduled_at?: string | null;
  recurrence?: RecurrenceWindow | null;
}

export interface UpdateFolderScheduleRequest {
  schedule_type: FolderScheduleType;
  timezone: string;
  scheduled_at?: string | null;
  recurrence?: RecurrenceWindow | null;
}

function localFolderListPath(path?: string | null): string {
  const params = new URLSearchParams();
  const trimmed = path?.trim();
  if (trimmed) {
    params.set("path", trimmed);
  }
  const query = params.toString();
  return `/api/v1/folder-ingest/local-folders${query ? `?${query}` : ""}`;
}

export const folderIngestApi = {
  listSchedules: () => apiClient.get<{ items: FolderSchedule[]; total: number }>("/api/v1/folder-ingest/schedules"),
  listLocalFolders: (path?: string | null) => apiClient.get<LocalFolderListResponse>(localFolderListPath(path)),
  createSnapshot: (request: CreateSnapshotScheduleRequest) => {
    const formData = new FormData();
    request.files.forEach((file) => formData.append("files", file));
    request.relative_paths.forEach((relativePath) => formData.append("relative_paths", relativePath));
    formData.set("name", request.name);
    formData.set("group_path", request.group_path);
    if (request.clearance_level) formData.set("clearance_level", request.clearance_level);
    if (request.effective_date) formData.set("effective_date", request.effective_date);
    if (request.expiry_date) formData.set("expiry_date", request.expiry_date);
    if (request.doc_type) formData.set("doc_type", request.doc_type);
    if (request.description) formData.set("description", request.description);
    formData.set("schedule_type", request.schedule_type);
    formData.set("timezone", request.timezone);
    if (request.scheduled_at) formData.set("scheduled_at", request.scheduled_at);
    formData.set("recurrence_json", JSON.stringify(request.recurrence ?? {}));
    return apiClient.postForm<FolderSchedule>("/api/v1/folder-ingest/schedules/snapshot", formData);
  },
  createLocalFolder: (request: CreateLocalFolderScheduleRequest) =>
    apiClient.postJson<FolderSchedule>("/api/v1/folder-ingest/schedules/local-folder", request),
  createConnector: (request: CreateConnectorScheduleRequest) =>
    apiClient.postJson<FolderSchedule>("/api/v1/folder-ingest/schedules/connector", request),
  updateSchedule: (scheduleId: string, request: UpdateFolderScheduleRequest) =>
    apiClient.request<FolderSchedule>(`/api/v1/folder-ingest/schedules/${encodeURIComponent(scheduleId)}`, {
      method: "PATCH",
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
    }),
  pauseSchedule: (scheduleId: string) =>
    apiClient.postJson<{ id: string; status: FolderSchedule["status"] }>(`/api/v1/folder-ingest/schedules/${encodeURIComponent(scheduleId)}/pause`, null),
  resumeSchedule: (scheduleId: string) =>
    apiClient.postJson<{ id: string; status: FolderSchedule["status"] }>(`/api/v1/folder-ingest/schedules/${encodeURIComponent(scheduleId)}/resume`, null),
  cancelSchedule: (scheduleId: string) =>
    apiClient.postJson<{ id: string; status: FolderSchedule["status"] }>(`/api/v1/folder-ingest/schedules/${encodeURIComponent(scheduleId)}/cancel`, null),
  listRuns: (scheduleId: string) =>
    apiClient.get<{ items: FolderRun[]; total: number }>(`/api/v1/folder-ingest/schedules/${encodeURIComponent(scheduleId)}/runs`),
  listRunItems: (runId: string) =>
    apiClient.get<{ items: FolderRunItem[]; total: number }>(`/api/v1/folder-ingest/runs/${encodeURIComponent(runId)}/items`),
};
