import type { JobStatus, UploadJobStageProgress, UploadJobState, UploadJobStep } from "../types/api";
import type { UploadJobView } from "../types/chat";

export const uploadTerminalStatuses: ReadonlySet<UploadJobState> = new Set(["complete", "failed", "human_review"]);

export const uploadFallbackSteps: UploadJobStep[] = [
  { id: "scheduled", label: "Scheduled", detail: "Waiting for the scheduled ingestion window.", state: "active" },
  { id: "queued", label: "Queued", detail: "Waiting for the ingestion worker to start.", state: "active" },
  { id: "reading_file", label: "Read file", detail: "Fetching the uploaded PDF from object storage.", state: "pending" },
  { id: "parsing_document", label: "Parse document", detail: "Extracting text, layout, tables, and hierarchy.", state: "pending" },
  { id: "generating_metadata", label: "Generate metadata", detail: "Creating document metadata for retrieval filters.", state: "pending" },
  { id: "chunking_document", label: "Build chunks", detail: "Creating retrieval chunks and extracted claims.", state: "pending" },
  { id: "saving_claims", label: "Save claims", detail: "Persisting extracted claims and conflict pairs.", state: "pending" },
  { id: "embedding_chunks", label: "Generate embeddings", detail: "Creating dense and sparse vectors for each chunk.", state: "pending" },
  { id: "indexing_vectors", label: "Index vectors", detail: "Writing document vectors to Qdrant.", state: "pending" },
  { id: "finalizing", label: "Finalize", detail: "Applying supersession metadata and final job state.", state: "pending" },
];

export function isUploadTerminalStatus(status: UploadJobState | null | undefined): boolean {
  return Boolean(status && uploadTerminalStatuses.has(status));
}

export function toUploadJobView(jobId: string, status: JobStatus | undefined): UploadJobView {
  return {
    jobId,
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
    lastHeartbeatAt: status?.last_heartbeat_at ?? null,
  };
}

export function formatStageProgress(progress: UploadJobStageProgress | null | undefined): string | null {
  if (!progress || progress.total <= 0) return null;
  if (progress.label?.trim()) return progress.label.trim();
  return `${unitLabel(progress.unit, progress.total)} ${progress.current} of ${progress.total}`;
}

function unitLabel(unit: UploadJobStageProgress["unit"], total: number): string {
  const singular = total === 1;
  if (unit === "pages") return singular ? "Page" : "Pages";
  if (unit === "chunks") return singular ? "Chunk" : "Chunks";
  if (unit === "vectors") return singular ? "Vector" : "Vectors";
  return singular ? "File" : "Files";
}
