import type { ClearanceLevel, ISODateString } from "./api";

export type QueryIntent =
  | "factual_simple"
  | "multi_hop"
  | "temporal"
  | "contradictory"
  | "aggregation"
  | "conversational";

type ArtifactFormat = "docx" | "pptx" | "pdf";
type ArtifactJobProgressUnit = "sections" | "batches" | "slides" | "formats" | "files";
type ArtifactJobStatus =
  | "queued"
  | "planning"
  | "needs_input"
  | "retrieving"
  | "composing"
  | "validating"
  | "rendering"
  | "complete"
  | "partial"
  | "failed"
  | "cancelled";
export type FaithfulnessStatus = "pending" | "checked" | "skipped" | "failed";
export type QuerySourceMode = "auto" | "corpus_only" | "db_only" | "hybrid";
type QuerySourceKind = "connector_schema_catalog";

export interface QueryRequest {
  query: string;
  session_id: string | null;
  client_request_id?: string | null;
  group_path?: string | null;
  document_ids?: string[];
  source_mode?: QuerySourceMode;
  query_source_id?: string | null;
  allow_source_expansion?: boolean;
}

export interface QuerySource {
  id: string;
  kind: QuerySourceKind;
  name: string;
  description: string | null;
  connector_type: string;
  scope: "database_scope";
  group_path: string;
  clearance_level: ClearanceLevel;
}

interface SourceExpansion {
  available: boolean;
  reason: string;
  suggested_source_mode: QuerySourceMode;
}

export interface HighlightRange {
  start: number;
  end: number;
}

interface SourceRegion {
  page: number | null;
  bbox: [number, number, number, number] | null;
  text: string;
  region_type: string;
  confidence: number | null;
  image_asset_id?: string | null;
  image_source_kind?: string | null;
  extraction_method?: string | null;
}

export interface EvidenceField {
  label: string;
  value: string;
  supports_claim: boolean;
}

export interface EvidenceWindow {
  claim_id: string;
  claim: string;
  kind: "text" | "table_row";
  passage: string;
  highlight_ranges: HighlightRange[];
  support_status: "verified" | "semantic_fallback";
  support_score: number;
  source_start: number;
  source_end: number;
  quote_start: number | null;
  quote_end: number | null;
  truncated_start: boolean;
  truncated_end: boolean;
  table_title: string | null;
  fields: EvidenceField[];
}

export interface SourceAnchor {
  doc_id: string;
  doc_title: string;
  chunk_id: string;
  page: number | null;
  page_start: number | null;
  page_end: number | null;
  excerpt: string;
  group_path: string;
  clearance_level: ClearanceLevel;
  effective_date: ISODateString | null;
  highlight_ranges: HighlightRange[];
  source_regions?: SourceRegion[];
  evidence_windows?: EvidenceWindow[];
  attribution_status?: "pending" | "complete" | "unavailable";
}

interface ConflictPair {
  claim_a_id: string;
  claim_b_id: string;
  doc_a_id: string;
  doc_b_id: string;
  chunk_a_id: string;
  chunk_b_id: string;
  entity: string;
  attribute: string;
  value_a: string;
  value_b: string;
  effective_date_a: ISODateString | null;
  effective_date_b: ISODateString | null;
  source_a: SourceAnchor;
  source_b: SourceAnchor;
}

export interface QueryNodeTiming {
  node: string;
  duration_ms: number;
  execution_mode: string | null;
  detail: string | null;
  phase_timings_ms?: Record<string, number>;
}

type AnswerStatus = "complete" | "partial" | "clarification" | "abstained";

interface QueryCoverage {
  required_slots: string[];
  covered_slots: string[];
  completeness: "complete" | "partial" | "unknown" | "not_applicable";
  warnings: string[];
}

export interface RAGResponse {
  trace_id: string;
  answer: string;
  answer_status?: AnswerStatus;
  coverage?: QueryCoverage;
  sources: SourceAnchor[];
  artifacts?: GeneratedArtifact[];
  artifact_job?: ArtifactJobSummary | null;
  conflict_flag: boolean;
  conflict_detail: ConflictPair[] | null;
  faithfulness_score: number;
  faithfulness_status: FaithfulnessStatus;
  unfounded_claims: string[];
  intent: QueryIntent;
  session_id: string;
  latency_ms: number;
  node_timings?: QueryNodeTiming[];
  degraded: boolean;
  degraded_reason: string | null;
  source_mode?: string | null;
  source_decision_reason?: string | null;
  source_expansion?: SourceExpansion | null;
}

export interface GeneratedArtifact {
  id: string;
  filename: string;
  format: ArtifactFormat;
  content_type: string;
  size_bytes: number;
  download_url: string;
  created_at: ISODateString | null;
}

export interface ArtifactJobSummary {
  id: string;
  status: ArtifactJobStatus;
  stage: string;
  progress_pct: number;
  stage_label?: string;
  stage_detail?: string;
  stage_progress?: ArtifactJobStageProgress | null;
  requested_formats: ArtifactFormat[];
  clarification_questions: string[];
  artifacts: GeneratedArtifact[];
  error_code: string | null;
  error_message: string | null;
  attempt_count?: number;
  max_attempts?: number;
  created_at: ISODateString | null;
  updated_at: ISODateString | null;
  started_at?: ISODateString | null;
  completed_at?: ISODateString | null;
  last_heartbeat_at?: ISODateString | null;
  expires_at: ISODateString | null;
}

interface ArtifactJobStageProgress {
  unit: ArtifactJobProgressUnit;
  current: number;
  total: number;
  label?: string | null;
}

interface ArtifactStageTiming {
  duration_ms: number;
  started_at?: ISODateString | null;
  completed_at?: ISODateString | null;
}

export interface ArtifactJobDetail extends ArtifactJobSummary {
  plan?: unknown | null;
  evidence_manifest?: unknown | null;
  content_specification?: unknown | null;
  validation_results?: unknown | null;
  stage_timings?: Record<string, ArtifactStageTiming>;
  errors?: Record<string, unknown>[];
  attempt_count?: number;
  max_attempts?: number;
  started_at?: ISODateString | null;
  completed_at?: ISODateString | null;
  last_heartbeat_at?: ISODateString | null;
}

type SseEventType = "trace" | "intent" | "token" | "source" | "artifact" | "artifact_job" | "warning" | "done" | "verified" | "error";

interface SseEventBase<TType extends SseEventType, TData> {
  event: TType;
  data: TData;
}

export type RagSseEvent =
  | SseEventBase<"trace", { trace_id?: string; session_id?: string; node?: string; agent?: string | null; execution_mode?: string; detail?: string | null }>
  | SseEventBase<"intent", { intent: QueryIntent }>
  | SseEventBase<"token", { text: string }>
  | SseEventBase<"source", SourceAnchor>
  | SseEventBase<"artifact", GeneratedArtifact>
  | SseEventBase<"artifact_job", ArtifactJobSummary>
  | SseEventBase<"warning", { code: string; message?: string; retry_count?: number; score?: number; unfounded_claims?: string[] }>
  | SseEventBase<"done", RAGResponse>
  | SseEventBase<"verified", RAGResponse>
  | SseEventBase<"error", { code: string; message: string }>;
