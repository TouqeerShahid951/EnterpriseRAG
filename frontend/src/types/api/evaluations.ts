import type { ISODateString } from "./common";

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

interface EvaluationCase {
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
