import type { ISODateString } from "./common";

interface AnalyticsRate {
  numerator: number;
  denominator: number;
  value: number | null;
}

export interface AnalyticsSummary {
  created_from: ISODateString;
  created_to: ISODateString;
  as_of: ISODateString;
  total_executions: number;
  terminal_executions: number;
  in_flight_executions: number;
  complete: number;
  partial: number;
  clarification: number;
  abstained: number;
  system_error: number;
  access_denied: number;
  cancelled: number;
  interrupted: number;
  artifact_submitted: number;
  answer_executions: number;
  unique_actor_count: number;
  verification_checked: number;
  verification_applicable: number;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  complete_rate: AnalyticsRate;
  abstention_rate: AnalyticsRate;
  system_error_rate: AnalyticsRate;
  verification_coverage: AnalyticsRate;
  timezone: "UTC";
  data_status: "available" | "empty";
}

export interface AnalyticsExecution {
  execution_id: string;
  trace_id: string;
  session_id: string;
  actor_id: string;
  permission_version: number;
  origin: string;
  work_kind: string;
  group_path: string | null;
  lifecycle: string;
  started_at: ISODateString;
  finished_at: ISODateString | null;
  outcome: string | null;
  answer_status: string | null;
  reason_code?: string | null;
  last_heartbeat_at?: ISODateString | null;
  liveness_status?: "untracked" | "active" | "heartbeat_expired" | "finished";
  degraded: boolean | null;
  degraded_reason: string | null;
  requested_source_mode: string | null;
  resolved_source_mode: string | null;
  initial_intent: string | null;
  final_intent: string | null;
  response_mode: string | null;
  latency_ms: number | null;
  verification_status: string | null;
  verification_method: string | null;
  faithfulness_score: number | null;
  retry_count: number;
  route_reroute_count: number;
  retrieved_hit_count: number | null;
  evidence_source_count: number | null;
  cited_source_count: number | null;
  max_retrieval_score: number | null;
  max_rerank_score: number | null;
  model_cohort: string | null;
  configuration_digest: string | null;
  application_image_digest: string | null;
  cohort_snapshot: Record<string, unknown> | null;
  retrieval_lineage_status:
    | "not_captured"
    | "available"
    | "truncated"
    | "unavailable"
    | "expired";
  retrieval_lineage: AnalyticsLineage | null;
  review_reasons: string[];
}

export interface AnalyticsEvidenceIdentity {
  doc_id?: string;
  chunk_id?: string;
  index_generation_id?: string;
}

export interface AnalyticsLineage {
  status?: string;
  truncated?: boolean;
  stages?: {
    name: string;
    attempt: number;
    status: string;
    candidate_count: number;
    truncated: boolean;
    candidates: (AnalyticsEvidenceIdentity & {
      candidate_key?: string;
      point_id?: string;
      rank?: number;
      retrieval_score?: number | null;
      rerank_score?: number | null;
      rerank_adjusted_score?: number | null;
    })[];
  }[];
  performance?: { node_timings?: { node: string; duration_ms: number }[] };
  generation?: { status?: string; source_count?: number; source_keys?: AnalyticsEvidenceIdentity[] };
  citation?: { status?: string; cited_source_count?: number; cited_source_keys?: AnalyticsEvidenceIdentity[] };
  quality?: {
    status?: string;
    method?: string;
    score_subject?: string;
    claim_ledger?: { status?: string; applicable_claims?: number; supported_claims?: number; unsupported_claims?: number; unknown_claims?: number; cited_claims?: number };
  };
}

export interface AnalyticsExecutionListResponse {
  items: AnalyticsExecution[];
  total: number;
  limit: number;
  offset: number;
  created_from: ISODateString;
  created_to: ISODateString;
  as_of: ISODateString;
  timezone: "UTC";
}

export interface AnalyticsSeriesBucket {
  started_at: ISODateString;
  ended_at: ISODateString;
  total_executions: number;
  answer_executions: number;
  complete: number;
  partial: number;
  clarification: number;
  abstained: number;
  system_error: number;
  access_denied: number;
  cancelled: number;
  interrupted: number;
  artifact_submitted: number;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  verification_checked: number;
  verification_applicable: number;
  faithfulness_score_mean: number | null;
}

export interface AnalyticsSeriesResponse {
  bucket_size: "hour" | "day";
  buckets: AnalyticsSeriesBucket[];
  created_from: ISODateString;
  created_to: ISODateString;
  as_of: ISODateString;
  timezone: "UTC";
}

export interface AnalyticsScoreStats {
  count: number;
  mean: number | null;
  p50: number | null;
  p95: number | null;
  buckets: [string, number][];
}

export interface AnalyticsStageDiagnostics {
  name: string;
  execution_count: number;
  candidate_count: number;
  serialized_candidate_count: number;
  retrieval_score: AnalyticsScoreStats;
  rerank_score: AnalyticsScoreStats;
  adjusted_rerank_score: AnalyticsScoreStats;
}

export interface AnalyticsTimingDiagnostics {
  node: string;
  execution_count: number;
  duration_count: number;
  p50_ms: number | null;
  p95_ms: number | null;
}

export interface AnalyticsRankMovement {
  status: "available" | "unavailable";
  count: number;
  mean_absolute: number | null;
  p50_absolute: number | null;
  p95_absolute: number | null;
  promoted: number;
  demoted: number;
  unchanged: number;
}

export interface AnalyticsEvidenceUtilization {
  status: "available" | "unavailable";
  execution_count: number;
  sent_source_count: number;
  cited_source_count: number;
  utilization_rate: number | null;
}

export interface AnalyticsQualityDiagnostics {
  status_counts: Record<string, number>;
  method_counts: Record<string, number>;
  support_status_counts: Record<string, number>;
  score: AnalyticsScoreStats;
  checked_count: number;
  applicable_count: number;
  claim_ledger: AnalyticsClaimLedger;
}

export interface AnalyticsClaimLedger {
  status: "available" | "unavailable";
  execution_count: number;
  applicable_claim_count: number;
  supported_claim_count: number;
  unsupported_claim_count: number;
  unknown_claim_count: number;
  cited_claim_count: number;
  uncited_claim_count: number;
  valid_quote_count: number;
  support_rate: AnalyticsRate;
  citation_coverage: AnalyticsRate;
}

export interface AnalyticsDocumentUsage {
  document_key: string;
  document_title: string | null;
  generation_id: string | null;
  execution_count: number;
  candidate_count: number;
}

export interface AnalyticsDocumentDiagnostics {
  status: "available" | "unavailable";
  documents_per_query: AnalyticsScoreStats;
  top_documents: AnalyticsDocumentUsage[];
  top_k_turnover: {
    status: "available" | "unavailable";
    comparable_attempt_count: number;
    mean_overlap: number | null;
    p50_overlap: number | null;
    p95_overlap: number | null;
    mean_added: number | null;
    mean_dropped: number | null;
  };
}

export interface AnalyticsCohortObservation {
  model_cohort: string;
  configuration_digest: string;
  application_image_digest: string | null;
  execution_count: number;
  first_observed_at: ISODateString | null;
}

export interface AnalyticsDiagnostics {
  capture_status_counts: Record<string, number>;
  stages: AnalyticsStageDiagnostics[];
  timings: AnalyticsTimingDiagnostics[];
  rank_movement: AnalyticsRankMovement;
  evidence_utilization: AnalyticsEvidenceUtilization;
  quality: AnalyticsQualityDiagnostics;
  documents: AnalyticsDocumentDiagnostics;
  cohorts: AnalyticsCohortObservation[];
  data_status: "available" | "empty";
}
