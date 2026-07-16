import type { ClearanceLevel, ISODateString } from "./common";

export type UploadJobState = "scheduled" | "queued" | "processing" | "complete" | "failed" | "human_review" | "cancelled";

export type IngestJobOrigin = "upload" | "reingest" | "restore" | "folder" | "connector" | "unknown";

export type DocumentIngestStatus = UploadJobState | "unknown";

export type UploadJobStage =
  | "scheduled"
  | "queued"
  | "reading_file"
  | "parsing_document"
  | "docling_repair"
  | "vision_layout_repair"
  | "image_analysis"
  | "generating_metadata"
  | "metadata_enrichment"
  | "chunking_document"
  | "embedding_chunks"
  | "indexing_vectors"
  | "saving_claims"
  | "finalizing"
  | "complete"
  | "failed"
  | "human_review"
  | "cancelled";

type UploadJobStepState = "pending" | "active" | "complete" | "failed" | "needs_review" | "cancelled";

type UploadJobProgressUnit = "pages" | "chunks" | "vectors" | "files" | "metadata" | "images";

interface GraphRAGWorkerState {
  name: string;
  pool_size: number;
  active_jobs: number;
}

interface GraphRAGActiveTask {
  task_id: string;
  task_name: string;
  worker: string;
  job_id: string | null;
  document_id: string | null;
  started_at: ISODateString | null;
  elapsed_seconds: number | null;
}

interface GraphRAGQueuedTask {
  task_id: string;
  task_name: string;
  job_id: string | null;
  document_id: string | null;
}

export interface GraphRAGStatus {
  enabled: boolean;
  queue_name: string;
  queued_jobs: number | null;
  queue_error: string | null;
  worker_online: boolean;
  worker_error: string | null;
  active_jobs: number;
  observed_pool_size: number;
  workers: GraphRAGWorkerState[];
  active_tasks: GraphRAGActiveTask[];
  queued_tasks: GraphRAGQueuedTask[];
}

export interface GraphRAGCancelResponse {
  task_id: string;
  job_id: string;
  document_id: string;
  status: "cancelled";
  message: string;
}

export interface UploadResponse {
  job_id: string;
  status: "queued";
}

export interface JobStatus {
  job_id: string;
  status: UploadJobState;
  progress_pct: number;
  stage: UploadJobStage;
  stage_label: string;
  stage_detail: string;
  stage_progress: UploadJobStageProgress | null;
  steps: UploadJobStep[];
  error_code: string | null;
  error_message: string | null;
  attempt_count: number;
  max_attempts: number;
  warnings: string[];
  parser_provenance: ParserProvenance | null;
  created_at: ISODateString | null;
  updated_at: ISODateString | null;
  completed_at: ISODateString | null;
  last_heartbeat_at: ISODateString | null;
}

export interface ParserProvenance {
  version: number;
  document_kind: string;
  page_count: number | null;
  primary_parser: string;
  secondary_parser: string | null;
  routing_mode: string;
  config: Record<string, unknown>;
  docling_selection: ParserDoclingSelection | null;
  parser_item_counts: Record<string, number>;
  parser_page_counts: Record<string, number>;
  quality_flag_counts: Record<string, number>;
  fallback: Record<string, string> | null;
  errors: Record<string, string>[];
}

interface ParserDoclingSelection {
  mode: string;
  budget_pages: number;
  batch_pages: number;
  weak_pages_total: number;
  selected_pages: ParserPageList;
  skipped_pages: ParserPageList;
}

interface ParserPageList {
  total: number;
  truncated: boolean;
  items: ParserPageEntry[];
}

interface ParserPageEntry {
  page_no: number;
  score: number;
  reasons: string[];
}

export interface IngestJob extends JobStatus {
  document_id: string;
  document_title: string;
  retry_of_job_id: string | null;
  group_path: string;
  clearance_level: ClearanceLevel;
  origin: IngestJobOrigin;
  uploaded_by: string | null;
  created_at: ISODateString | null;
  updated_at: ISODateString | null;
  completed_at: ISODateString | null;
}

export interface IngestJobListResponse {
  items: IngestJob[];
  total: number;
  limit: number;
  offset: number;
}

export interface IngestJobSummary {
  total: number;
  active: number;
  needs_attention: number;
  status_counts: Record<string, number>;
  stage_counts: Record<string, number>;
  origin_counts: Record<string, number>;
}

interface StaleIngestJob {
  job_id: string;
  document_id: string;
  document_title: string;
  group_path: string;
  attempt_count: number;
  max_attempts: number;
  last_activity_at: ISODateString | null;
  stale_for_seconds: number;
  recoverable: boolean;
  recovery_code: string | null;
  recovery_message: string;
}

export interface StaleIngestJobListResponse {
  items: StaleIngestJob[];
  total: number;
  recoverable: number;
  stale_after_seconds: number;
}

export interface IngestJobRecoveryResponse {
  job_id: string;
  status: "queued";
  next_attempt: number;
  message: string;
}

export interface IngestJobCancelResponse {
  job_id: string;
  status: UploadJobState;
  message: string;
}

export interface UploadJobStageProgress {
  unit: UploadJobProgressUnit;
  current: number;
  total: number;
  label: string | null;
}

export interface UploadJobStep {
  id: UploadJobStage;
  label: string;
  detail: string;
  state: UploadJobStepState;
}
