import type { ClearanceLevel, DocType, ISODateString } from "./common";

type FolderSourceType =
  | "snapshot"
  | "local_folder"
  | "minio_prefix"
  | "connector"
  | "sql_server"
  | "postgres"
  | "mysql"
  | "mariadb"
  | "mongodb"
  | "oracle"
  | "opensearch"
  | "elasticsearch"
  | "redis"
  | "cassandra"
  | "fake";

export type FolderScheduleType = "one_time" | "recurring";

export type FolderScheduleStatus = "scheduled" | "active" | "paused" | "cancelled" | "complete" | "failed";

type FolderRunStatus = "scheduled" | "running" | "complete" | "failed" | "cancelled";

type FolderRunItemStatus = "scheduled" | "queued" | "skipped" | "failed";

export type ConnectorType = "sql_server" | "postgres";

export type ConnectorIngestionMode = "json_snapshot" | "direct_chunks";

export type ConnectorDeletionPolicy = "keep_deleted_documents" | "mark_as_stale" | "archive_from_retrieval" | "delete_from_index_after_review";

export interface RecurrenceWindow {
  days_of_week: number[];
  start_time: string;
  end_time: string;
}

export interface ConnectorProfile {
  id: string;
  name: string;
  connector_type: ConnectorType | string;
  public_config: Record<string, unknown>;
  secrets_redacted: Record<string, string>;
  created_by: string | null;
  last_test_status: "ok" | "failed" | null;
  last_test_message: string | null;
  last_tested_at: ISODateString | null;
  created_at: ISODateString | null;
  updated_at: ISODateString | null;
}

export interface ConnectorTestResponse {
  status: "ok" | "failed";
  message: string;
  detail: Record<string, unknown>;
  profile: ConnectorProfile | null;
}

export interface ConnectorSchemaSnapshot {
  id: string;
  profile_id: string;
  connector_type: string;
  schema_json: Record<string, unknown>;
  status: "ok" | "failed";
  error_message: string | null;
  created_at: ISODateString | null;
}

export type ConnectorSchemaCatalogStatus = "draft" | "reviewed" | "approved" | "disabled";

export interface ConnectorSchemaCatalog {
  id: string;
  profile_id: string;
  connector_type: string;
  status: ConnectorSchemaCatalogStatus | string;
  group_path: string;
  owner_group_path?: string;
  shared_group_paths: string[];
  access_group_paths: string[];
  clearance_level: ClearanceLevel | string;
  catalog_json: Record<string, unknown>;
  created_by: string | null;
  approved_by: string | null;
  created_at: ISODateString | null;
  updated_at: ISODateString | null;
}

export interface FolderRunItem {
  id: string;
  run_id: string;
  schedule_id: string;
  source_path: string;
  filename: string;
  content_hash: string | null;
  size_bytes: number | null;
  content_type: string | null;
  status: FolderRunItemStatus;
  skip_code: string | null;
  skip_message: string | null;
  document_id: string | null;
  job_id: string | null;
  created_at: ISODateString | null;
  updated_at: ISODateString | null;
}

export interface FolderRun {
  id: string;
  schedule_id: string;
  status: FolderRunStatus;
  due_at: ISODateString;
  started_at: ISODateString | null;
  completed_at: ISODateString | null;
  error_code: string | null;
  error_message: string | null;
  created_at: ISODateString | null;
  updated_at: ISODateString | null;
  item_count: number;
  queued_count: number;
  skipped_count: number;
  failed_count: number;
}

export interface FolderSchedule {
  id: string;
  name: string;
  source_type: FolderSourceType;
  schedule_type: FolderScheduleType;
  status: FolderScheduleStatus;
  group_path: string;
  clearance_level: ClearanceLevel;
  doc_type: DocType | null;
  effective_date: ISODateString | null;
  expiry_date: ISODateString | null;
  description: string | null;
  timezone: string;
  scheduled_at: ISODateString | null;
  recurrence: Record<string, unknown>;
  source_config: Record<string, unknown>;
  created_by: string | null;
  last_run_at: ISODateString | null;
  next_run_at: ISODateString | null;
  created_at: ISODateString | null;
  updated_at: ISODateString | null;
  latest_run: FolderRun | null;
}
