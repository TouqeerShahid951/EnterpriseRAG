import type { Document, QuerySourceMode } from "@/types/api";
import type { UploadJobView } from "@/types/chat";
import { uploadFallbackSteps } from "@/features/upload/state/uploadJobProgress";

export function composerPlaceholder(sourceMode: QuerySourceMode, hasCorpus: boolean, sourceCount: number): string {
  if (sourceMode === "db_only") return sourceCount ? "Ask a live database question..." : "No live database source is available.";
  if (sourceMode === "hybrid") return "Ask across documents and live data...";
  if (sourceMode === "corpus_only") return hasCorpus ? "Ask a document question, or type @ to scope..." : "Index a document before querying.";
  return hasCorpus || sourceCount ? "Ask a question, or type @ to scope to a document..." : "Index a document or approve a database source before querying.";
}

export const localComposerUploadJob: UploadJobView = {
  jobId: "",
  documentId: null,
  retryOfJobId: null,
  status: "queued",
  progressPct: 8,
  stage: "queued",
  stageLabel: "Uploading document",
  stageDetail: "Validating, scanning, storing, and creating the indexing job.",
  stageProgress: null,
  steps: uploadFallbackSteps.map((step, index) =>
    index === 0
      ? { ...step, label: "Prepare upload", detail: "Validate, scan, store, and queue the document.", state: "active" }
      : { ...step, state: "pending" },
  ),
  warnings: [],
  parserProvenance: null,
  errorCode: null,
  errorMessage: null,
  attemptCount: 0,
  maxAttempts: 3,
  createdAt: null,
  updatedAt: null,
  completedAt: null,
  lastHeartbeatAt: null,
};

export function failedComposerUploadJob(message: string): UploadJobView {
  return {
    jobId: "",
    documentId: null,
    retryOfJobId: null,
    status: "failed",
    progressPct: 0,
    stage: "failed",
    stageLabel: "Upload failed",
    stageDetail: "The document did not reach the indexing queue.",
    stageProgress: null,
    steps: uploadFallbackSteps.map((step, index) =>
      index === 0
        ? { ...step, label: "Prepare upload", detail: "Validate, scan, store, and queue the document.", state: "failed" }
        : { ...step, state: "pending" },
    ),
    warnings: [],
    parserProvenance: null,
    errorCode: "chat_upload_failed",
    errorMessage: message,
    attemptCount: 0,
    maxAttempts: 3,
    createdAt: null,
    updatedAt: null,
    completedAt: null,
    lastHeartbeatAt: null,
  };
}

export function activeMentionQuery(value: string): string | null {
  const match = /(^|\s)@([^\s@]*)$/.exec(value);
  return match ? match[2].toLowerCase() : null;
}

export function removeActiveMention(value: string): string {
  return value.replace(/(^|\s)@([^\s@]*)$/, "$1").replace(/\s+$/, " ");
}

export function mentionSuggestionsForDocuments(documents: Document[], scopedDocumentIds: string[], mentionQuery: string | null): Document[] {
  if (mentionQuery === null) return [];
  const query = mentionQuery.trim().toLowerCase();
  return documents
    .filter((document) => !scopedDocumentIds.includes(document.id))
    .filter((document) => {
      if (!query) return true;
      return `${document.title} ${document.id} ${document.group_path}`.toLowerCase().includes(query);
    })
    .slice(0, 6);
}
