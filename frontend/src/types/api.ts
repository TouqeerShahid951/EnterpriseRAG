export type ISODateString = string;
export type DocType = string;
export type AccountType =
  | "platform_admin"
  | "system_admin"
  | "user_manager"
  | "space_admin"
  | "contributor"
  | "reviewer"
  | "auditor"
  | "member";
export type ClearanceLevel =
  | "NATO_UNCLASSIFIED"
  | "NATO_RESTRICTED"
  | "NATO_CONFIDENTIAL"
  | "NATO_SECRET"
  | "COSMIC_TOP_SECRET";
export type UploadJobState = "scheduled" | "queued" | "processing" | "complete" | "failed" | "human_review" | "cancelled";
export type IngestJobOrigin = "upload" | "reingest" | "restore" | "folder" | "unknown";
export type DocumentIngestStatus = UploadJobState | "unknown";
export type UploadJobStage =
  | "scheduled"
  | "queued"
  | "reading_file"
  | "parsing_document"
  | "generating_metadata"
  | "chunking_document"
  | "embedding_chunks"
  | "indexing_vectors"
  | "saving_claims"
  | "finalizing"
  | "complete"
  | "failed"
  | "human_review"
  | "cancelled";
export type UploadJobStepState = "pending" | "active" | "complete" | "failed" | "needs_review" | "cancelled";
export type UploadJobProgressUnit = "pages" | "chunks" | "vectors" | "files" | "metadata";
export type ReviewStatus = "pending" | "approved" | "rejected";
export type FolderSourceType = "snapshot" | "minio_prefix";
export type FolderScheduleType = "one_time" | "recurring";
export type FolderScheduleStatus = "scheduled" | "active" | "paused" | "cancelled" | "complete" | "failed";
export type FolderRunStatus = "scheduled" | "running" | "complete" | "failed" | "cancelled";
export type FolderRunItemStatus = "scheduled" | "queued" | "skipped" | "failed";
export type EvaluationRunStatus = "queued" | "running" | "complete" | "partial" | "failed" | "cancelled";
export type EvaluationFailureStage =
  | "dataset"
  | "ingestion/indexing"
  | "retrieval"
  | "reranking/source_selection"
  | "answer_content"
  | "citation"
  | "faithfulness"
  | "degradation"
  | "runtime"
  | "latency";
export type {
  ArtifactFormat,
  ArtifactJobDetail,
  ArtifactJobStatus,
  ArtifactJobSummary,
  ConflictPair,
  EvidenceField,
  EvidenceWindow,
  FaithfulnessStatus,
  GeneratedArtifact,
  HighlightRange,
  QueryIntent,
  QueryRequest,
  RAGResponse,
  RagSseEvent,
  SourceAnchor,
  SourceRegion,
  SseEventBase,
  SseEventType,
} from "./query";

export interface User {
  user_id: string;
  email: string;
  account_type: AccountType;
  group_paths: string[];
  clearance_level: ClearanceLevel;
  permission_version: number;
  must_change_password?: boolean;
}

export interface UserAdmin {
  id: string;
  email: string;
  name: string;
  account_type: AccountType;
  group_paths: string[];
  clearance_level: ClearanceLevel;
  last_login_at: ISODateString | null;
  is_active: boolean;
  permission_version: number;
}

export interface RagConfigHealth {
  status: string;
  message: string;
  embedding_dimension: number | null;
  checked_at: ISODateString | null;
  chat_latency_ms: number | null;
  embed_latency_ms: number | null;
}

export interface IngestWorkerState {
  name: string;
  pool_size: number;
  active_jobs: number;
}

export interface IngestConfig {
  worker_concurrency: number;
  ocr_review_confidence_threshold: number;
  recommended_concurrency: number;
  worker_online: boolean;
  active_jobs: number;
  observed_pool_size: number;
  apply_status: string;
  workers: IngestWorkerState[];
  hazardous: boolean;
  updated_at: ISODateString | null;
}

export interface VllmServiceDeploymentLimits {
  max_model_len: number;
  gpu_memory_utilization: number;
  max_num_seqs: number;
  max_num_batched_tokens: number;
  kv_cache_memory_bytes?: string | null;
}

export interface VllmDeploymentConfig {
  source: string;
  apply_status: string;
  message?: string | null;
  text: VllmServiceDeploymentLimits;
  embeddings: VllmServiceDeploymentLimits;
  vision: VllmServiceDeploymentLimits;
}

export interface AuditEvent {
  id: string;
  event_type: string;
  actor_id: string | null;
  actor_email: string | null;
  target_type: string | null;
  target_id: string | null;
  target_user_email: string | null;
  target_user_name: string | null;
  payload: Record<string, unknown>;
  created_at: ISODateString | null;
}

export interface AuditSummary {
  total: number;
  document_events: number;
  auth_events: number;
  system_events: number;
  actor_count: number;
  event_type_count: number;
  category_counts: Record<string, number>;
  target_type_counts: Record<string, number>;
  event_type_counts: Record<string, number>;
}

export interface AuditEventListResponse {
  items: AuditEvent[];
  total: number;
  limit: number;
  offset: number;
  summary: AuditSummary;
}

export interface RagConfig {
  source: "workspace" | "env" | string;
  provider: "ollama" | "vllm";
  base_url: string;
  host: string;
  port: number;
  embedding_base_url: string;
  embedding_host: string;
  embedding_port: number;
  reasoning_base_url?: string | null;
  reasoning_host?: string | null;
  reasoning_port?: number | null;
  routing_base_url?: string | null;
  routing_host?: string | null;
  routing_port?: number | null;
  faithfulness_base_url?: string | null;
  faithfulness_host?: string | null;
  faithfulness_port?: number | null;
  ingestion_base_url?: string | null;
  ingestion_host?: string | null;
  ingestion_port?: number | null;
  chat_model: string;
  embed_model: string;
  reasoning_model: string | null;
  routing_model: string | null;
  faithfulness_model: string | null;
  ingestion_model: string | null;
  vision_model: string | null;
  thinking_enabled: boolean;
  json_num_predict: number;
  retrieval_token_budget: number;
  reranker_model: string;
  chat_timeout_seconds: number;
  embed_timeout_seconds: number;
  health: RagConfigHealth;
}

export interface RagConfigTestResult {
  provider: "ollama" | "vllm";
  base_url: string;
  embedding_base_url: string;
  reasoning_base_url?: string | null;
  routing_base_url?: string | null;
  faithfulness_base_url?: string | null;
  ingestion_base_url?: string | null;
  chat_models: string[];
  embedding_models: string[];
  reasoning_models?: string[];
  routing_models?: string[];
  faithfulness_models?: string[];
  ingestion_models?: string[];
  vision_models?: string[];
  thinking_enabled: boolean;
  json_num_predict: number;
  retrieval_token_budget: number;
  reranker_model: string;
  health: RagConfigHealth;
}

export interface RerankerModelOption {
  model: string;
  default: boolean;
}

export interface RerankerModelsResponse {
  models: RerankerModelOption[];
}

export interface RagModelDiscoveryResult {
  provider: "ollama" | "vllm";
  base_url: string;
  embedding_base_url: string;
  reasoning_base_url?: string | null;
  routing_base_url?: string | null;
  faithfulness_base_url?: string | null;
  ingestion_base_url?: string | null;
  chat_models: string[];
  embedding_models: string[];
  reasoning_models?: string[];
  routing_models?: string[];
  faithfulness_models?: string[];
  ingestion_models?: string[];
  vision_models?: string[];
}

export interface LoginResponse {
  user: User;
  csrf_token: string;
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

export interface ParserDoclingSelection {
  mode: string;
  budget_pages: number;
  batch_pages: number;
  weak_pages_total: number;
  selected_pages: ParserPageList;
  skipped_pages: ParserPageList;
}

export interface ParserPageList {
  total: number;
  truncated: boolean;
  items: ParserPageEntry[];
}

export interface ParserPageEntry {
  page_no: number;
  score: number;
  reasons: string[];
}

export interface IngestJob extends JobStatus {
  document_id: string;
  document_title: string;
  group_path: string;
  clearance_level: ClearanceLevel;
  origin: IngestJobOrigin;
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
  status_counts: Record<string, number>;
  stage_counts: Record<string, number>;
  origin_counts: Record<string, number>;
}

export interface StaleIngestJob {
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

export interface RecurrenceWindow {
  days_of_week: number[];
  start_time: string;
  end_time: string;
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

export interface Document {
  id: string;
  title: string;
  doc_type: DocType | null;
  group_path: string;
  clearance_level: ClearanceLevel;
  effective_date: ISODateString | null;
  expiry_date: ISODateString | null;
  description: string | null;
  summary: string | null;
  language: string | null;
  topics: string[];
  llm_topics: string[];
  auto_doc_type: string | null;
  extracted_dates: Record<string, unknown>;
  metadata_flags: Record<string, unknown>;
  entities: DocumentEntity[];
  cross_references: DocumentCrossReference[];
  claims: DocumentClaim[];
  is_current: boolean;
  ingest_status: DocumentIngestStatus;
  uploaded_by: string;
  superseded_by: string | null;
  deleted_at: ISODateString | null;
  created_at: ISODateString | null;
}

export interface DocumentEntity {
  text: string;
  type: string;
  start: number | null;
  end: number | null;
}

export interface DocumentCrossReference {
  ref_text: string;
  ref_type: string;
  position: number | null;
}

export interface DocumentClaim {
  id: string | null;
  chunk_id: string;
  entity: string;
  attribute: string;
  value: string;
}

export interface VersionNode {
  id: string;
  effective_date: ISODateString | null;
  is_current: boolean;
  superseded_by: string | null;
}

export interface VersionChainResponse {
  document_id: string;
  chain: VersionNode[];
}

export interface DeleteDocumentResponse {
  id: string;
  status: "soft_deleted" | "permanently_deleted";
}

export interface DocumentReingestResponse {
  document_id: string;
  job_id: string;
  status: "queued";
}

export interface Group {
  path: string;
  name: string;
  children: Group[];
}

export interface ReviewItem {
  id: string;
  batch_id: string;
  doc_id: string;
  doc_title: string;
  item_index: number;
  item_type: string;
  page_start: number | null;
  page_end: number | null;
  bbox: number[] | null;
  quality_flags: string[];
  confidence: number | null;
  partial_text: string;
  corrected_text: string | null;
  status: ReviewStatus;
  assigned_to: string | null;
  created_at: ISODateString | null;
  updated_at: ISODateString | null;
}

export interface ReviewDecisionResponse {
  id: string;
  status: ReviewStatus;
  batch_id: string;
  batch_status: ReviewStatus;
  batch_complete: boolean;
}

export interface EvaluationCase {
  id: string;
  question: string;
  question_type: string | null;
  difficulty: string | null;
  expected_answer: string | null;
  must_include: string[];
  must_not_include: string[];
  expected_source_docs: string[];
  acceptable_source_pages: number[];
  min_sources: number;
  must_cite_source: boolean;
  min_faithfulness_score: number;
  allow_degraded: boolean;
  latency_threshold_ms: number | null;
  metadata: Record<string, unknown>;
}

export interface EvaluationDatasetSummary {
  id: string;
  name: string;
  description: string | null;
  source_format: string;
  case_count: number;
  created_by: string | null;
  created_at: ISODateString | null;
  updated_at: ISODateString | null;
}

export interface EvaluationDatasetDetail extends EvaluationDatasetSummary {
  cases: EvaluationCase[];
  metadata: Record<string, unknown>;
}

export interface EvaluationRunSummary {
  id: string;
  dataset_id: string;
  dataset_name: string;
  status: EvaluationRunStatus;
  stage: string;
  progress_pct: number;
  case_count: number;
  completed_count: number;
  passed_count: number;
  failed_count: number;
  summary: Record<string, unknown>;
  group_path: string | null;
  document_ids: string[];
  error_code: string | null;
  error_message: string | null;
  created_at: ISODateString | null;
  updated_at: ISODateString | null;
  started_at: ISODateString | null;
  completed_at: ISODateString | null;
  last_heartbeat_at: ISODateString | null;
}

export interface EvaluationCaseResult {
  id: string;
  run_id: string;
  case_id: string;
  case_index: number;
  question: string;
  status: "ok" | "error";
  passed: boolean;
  primary_failure_stage: EvaluationFailureStage | null;
  failure_stages: EvaluationFailureStage[];
  checks: Record<string, unknown>;
  answer: string;
  sources: Record<string, unknown>[];
  diagnostic: Record<string, unknown>;
  trace_id: string | null;
  node_timings: Record<string, unknown>[];
  faithfulness_score: number | null;
  faithfulness_status: string | null;
  unfounded_claims: string[];
  degraded: boolean;
  degraded_reason: string | null;
  latency_ms: number;
  error_message: string | null;
  created_at: ISODateString | null;
}

export interface EvaluationRunDetail extends EvaluationRunSummary {
  cases: EvaluationCaseResult[];
  rag_config_snapshot: Record<string, unknown>;
  failure_breakdown: Record<string, number>;
  attempt_count: number;
  max_attempts: number;
}

export interface ApiError {
  status: number;
  code: string;
  message: string;
  details?: unknown;
  trace_id?: string;
}
