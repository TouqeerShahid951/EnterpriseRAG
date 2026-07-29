import type { GraphRAGStatus, JobStatus, ParserProvenance, UploadJobStageProgress, UploadJobState, UploadJobStep } from "@/types/api";
import type { UploadBatchItemView, UploadJobView } from "@/types/chat";

const uploadTerminalStatuses: ReadonlySet<UploadJobState> = new Set(["complete", "failed", "human_review", "cancelled"]);
const uploadCancellableStatuses: ReadonlySet<UploadJobState> = new Set(["scheduled", "queued", "processing", "human_review"]);

export const uploadFallbackSteps: UploadJobStep[] = [
  { id: "scheduled", label: "Scheduled", detail: "Waiting for the scheduled ingestion window.", state: "active" },
  { id: "queued", label: "Queued", detail: "Waiting for the ingestion worker to start.", state: "active" },
  { id: "reading_file", label: "Read file", detail: "Fetching the uploaded document from object storage.", state: "pending" },
  { id: "parsing_document", label: "Parse document", detail: "Extracting text, layout, tables, and hierarchy.", state: "pending" },
  { id: "docling_repair", label: "Docling repair", detail: "Repairing selected pages with Docling OCR and layout analysis.", state: "pending" },
  { id: "vision_layout_repair", label: "Vision repair", detail: "Using the vision model to re-read complex PDF layout.", state: "pending" },
  { id: "image_analysis", label: "Image analysis", detail: "Running OCR and descriptions for extracted document images.", state: "pending" },
  { id: "metadata_enrichment", label: "Metadata enrichment", detail: "Creating document metadata for retrieval filters.", state: "pending" },
  { id: "chunking_document", label: "Build chunks", detail: "Creating retrieval chunks and extracted claims.", state: "pending" },
  { id: "saving_claims", label: "Save claims", detail: "Persisting extracted claims and conflict pairs.", state: "pending" },
  { id: "embedding_chunks", label: "Generate embeddings", detail: "Creating dense and sparse vectors for each chunk.", state: "pending" },
  { id: "indexing_vectors", label: "Index vectors", detail: "Writing document vectors to Qdrant.", state: "pending" },
  { id: "finalizing", label: "Finalize", detail: "Applying supersession metadata and final job state.", state: "pending" },
];

export function isUploadTerminalStatus(status: UploadJobState | null | undefined): boolean {
  return Boolean(status && uploadTerminalStatuses.has(status));
}

export function isUploadCancellableStatus(status: UploadJobState | null | undefined): boolean {
  return Boolean(status && uploadCancellableStatuses.has(status));
}

export function uploadItemNeedsAttention(item: UploadBatchItemView): boolean {
  return item.requestState === "failed"
    || item.job?.status === "failed"
    || item.job?.status === "human_review"
    || (item.job?.status === "complete" && item.job.warnings.length > 0);
}

export function toUploadJobView(jobId: string, status: JobStatus | undefined): UploadJobView {
  const statusWithDocument = status as (JobStatus & { document_id?: string | null; retry_of_job_id?: string | null }) | undefined;
  return {
    jobId,
    documentId: statusWithDocument?.document_id ?? null,
    retryOfJobId: statusWithDocument?.retry_of_job_id ?? null,
    status: status?.status ?? "queued",
    progressPct: status?.progress_pct ?? 0,
    stage: status?.stage ?? "queued",
    stageLabel: status?.stage_label ?? "Queued",
    stageDetail: status?.stage_detail ?? "Waiting for the ingestion worker to start.",
    stageProgress: status?.stage_progress ?? null,
    steps: status?.steps ?? uploadFallbackSteps,
    warnings: status?.warnings ?? [],
    parserProvenance: status?.parser_provenance ?? null,
    errorCode: status?.error_code ?? null,
    errorMessage: status?.error_message ?? null,
    attemptCount: status?.attempt_count ?? 0,
    maxAttempts: status?.max_attempts ?? 3,
    createdAt: status?.created_at ?? null,
    updatedAt: status?.updated_at ?? null,
    completedAt: status?.completed_at ?? null,
    lastHeartbeatAt: status?.last_heartbeat_at ?? null,
  };
}

export function formatStageProgress(progress: UploadJobStageProgress | null | undefined): string | null {
  if (!progress || progress.total <= 0) return null;
  if (progress.label?.trim()) return progress.label.trim();
  return `${unitLabel(progress.unit, progress.total)} ${progress.current} of ${progress.total}`;
}

export function formatSecondaryStageProgress(
  progress: UploadJobStageProgress | null | undefined,
  primaryDetail: string | null | undefined,
): string | null {
  const formatted = formatStageProgress(progress);
  if (!formatted) return null;
  return formatted === primaryDetail?.trim() ? null : formatted;
}

export function formatUploadWarning(value: string): string {
  return WARNING_LABELS[value] ?? labelize(value);
}

export function formatIngestRunLabel(job: IngestRunLabelJob): string {
  const attempt = positiveInt(job.attempt_count ?? job.attemptCount, 1);
  const maxAttempts = positiveInt(job.max_attempts ?? job.maxAttempts, 3);
  if (isReviewResumeRun(job)) return "Resumed after review";
  if (attempt > 1) return `Retry ${attempt} of ${maxAttempts}`;
  return `Attempt ${attempt} of ${maxAttempts}`;
}

function isReviewResumeRun(job: IngestRunLabelJob): boolean {
  const provenance = job.parser_provenance ?? job.parserProvenance;
  return provenance?.routing_mode === "image_review_resume" || provenance?.primary_parser === "review_resume";
}

function positiveInt(value: number | null | undefined, fallback: number): number {
  return Number.isFinite(value) && Number(value) > 0 ? Math.floor(Number(value)) : fallback;
}

type GraphEnrichmentChipState = "queued" | "running" | "unavailable";

export interface GraphEnrichmentChip {
  state: GraphEnrichmentChipState;
  label: string;
  detail: string | null;
}

export interface GraphEnrichmentTask {
  taskId: string;
  jobId: string | null;
  documentId: string | null;
  state: "queued" | "running";
  elapsedSeconds: number | null;
}

type IngestRunLabelJob = {
  attempt_count?: number | null;
  max_attempts?: number | null;
  attemptCount?: number | null;
  maxAttempts?: number | null;
  parser_provenance?: ParserProvenance | null;
  parserProvenance?: ParserProvenance | null;
};

export function graphEnrichmentTaskForJob(
  job: { jobId: string; documentId?: string | null },
  graphStatus: GraphRAGStatus | null | undefined,
): GraphEnrichmentTask | null {
  const activeTask = graphStatus?.active_tasks.find((task) => graphTaskMatchesJob(task, job));
  if (activeTask) {
    return {
      taskId: activeTask.task_id,
      jobId: activeTask.job_id,
      documentId: activeTask.document_id,
      state: "running",
      elapsedSeconds: activeTask.elapsed_seconds,
    };
  }
  const queuedTask = graphStatus?.queued_tasks.find((task) => graphTaskMatchesJob(task, job));
  if (!queuedTask) return null;
  return {
    taskId: queuedTask.task_id,
    jobId: queuedTask.job_id,
    documentId: queuedTask.document_id,
    state: "queued",
    elapsedSeconds: null,
  };
}

export function graphEnrichmentForJob(
  job: { jobId: string; status: UploadJobState; documentId?: string | null },
  graphStatus: GraphRAGStatus | null | undefined,
  graphStatusError?: string | null,
): GraphEnrichmentChip | null {
  if (job.status !== "complete") return null;
  if (graphStatusError) {
    return { state: "unavailable", label: "Graph enrichment unavailable", detail: graphStatusError };
  }
  const graphTask = graphEnrichmentTaskForJob(job, graphStatus);
  if (!graphStatus?.enabled && !graphTask) return null;
  if (graphStatus?.enabled && (graphStatus.queue_error || graphStatus.worker_error)) {
    return {
      state: "unavailable",
      label: "Graph enrichment unavailable",
      detail: graphStatus.queue_error ?? graphStatus.worker_error ?? null,
    };
  }
  if (graphTask?.state === "running") {
    return {
      state: "running",
      label: "Graph enrichment running",
      detail: graphTask.elapsedSeconds === null ? null : `Running ${durationLabel(graphTask.elapsedSeconds)}`,
    };
  }
  if (graphTask?.state === "queued") {
    return { state: "queued", label: "Graph enrichment queued", detail: null };
  }
  return null;
}

function unitLabel(unit: UploadJobStageProgress["unit"], total: number): string {
  const singular = total === 1;
  if (unit === "pages") return singular ? "Page" : "Pages";
  if (unit === "chunks") return singular ? "Chunk" : "Chunks";
  if (unit === "vectors") return singular ? "Vector" : "Vectors";
  if (unit === "metadata") return "Metadata step";
  if (unit === "images") return singular ? "Image" : "Images";
  return singular ? "File" : "Files";
}

const WARNING_LABELS: Record<string, string> = {
  metadata_extraction_exception: "Metadata extraction failed; fallback metadata was used",
  metadata_extraction_unavailable: "Metadata enrichment was unavailable; fallback metadata was used",
  ollama_metadata_http_error: "Metadata model returned an HTTP error; fallback metadata was used",
  ollama_metadata_invalid_json: "Metadata model returned invalid JSON; fallback metadata was used",
  ollama_metadata_timeout: "Metadata model timed out; fallback metadata was used",
  ollama_metadata_transport_error: "Metadata model connection failed; fallback metadata was used",
  ollama_metadata_unavailable: "Metadata model was unavailable; fallback metadata was used",
};

function labelize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function graphTaskMatchesJob(
  task: { job_id: string | null; document_id: string | null },
  job: { jobId: string; documentId?: string | null },
) {
  if (job.jobId && task.job_id) return task.job_id === job.jobId;
  return Boolean(task.document_id && job.documentId && task.document_id === job.documentId);
}

function durationLabel(totalSeconds: number): string {
  if (totalSeconds < 60) return `${Math.max(0, totalSeconds)}s`;
  if (totalSeconds < 3600) return `${Math.floor(totalSeconds / 60)}m`;
  return `${Math.floor(totalSeconds / 3600)}h ${Math.floor((totalSeconds % 3600) / 60)}m`;
}
