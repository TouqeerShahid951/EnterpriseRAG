import type { DocType, ParserProvenance, QueryRequest, QueryIntent, RAGResponse, SourceAnchor, UploadJobStage, UploadJobStageProgress, UploadJobState, UploadJobStep } from "./api";

export interface PdfUploadDraft {
  files: File[];
  groupPath: string;
  effectiveDate: string;
  expiryDate: string;
  docType: DocType;
  description: string;
  supersedesText: string;
}

export interface UploadJobView {
  jobId: string;
  status: UploadJobState;
  progressPct: number;
  stage: UploadJobStage;
  stageLabel: string;
  stageDetail: string;
  stageProgress: UploadJobStageProgress | null;
  steps: UploadJobStep[];
  warnings: string[];
  parserProvenance: ParserProvenance | null;
  errorCode: string | null;
  errorMessage: string | null;
  attemptCount: number;
  maxAttempts: number;
  createdAt: string | null;
  updatedAt: string | null;
  lastHeartbeatAt: string | null;
}

export interface UploadBatchItemView {
  id: string;
  fileName: string;
  fileSize: number;
  groupPath: string;
  requestState: "uploading" | "accepted" | "failed";
  job: UploadJobView | null;
  uploadError: Error | null;
  jobError: Error | null;
}

export interface UserTurn {
  id: string;
  role: "user";
  content: string;
  createdAt: string;
}

export interface AssistantTurn {
  id: string;
  role: "assistant";
  status: "pending" | "complete" | "error" | "cancelled";
  question: string;
  createdAt: string;
  groupPath?: string | null;
  documentIds?: string[];
  progress: QueryProgressItem[];
  response?: RAGResponse;
  streamText?: string;
  errorMessage?: string;
}

export type ChatTurn = UserTurn | AssistantTurn;

export interface SavedChatSession {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  turns: ChatTurn[];
}

export interface QueryRunVariables {
  assistantTurnId: string;
  request: QueryRequest;
  signal: AbortSignal;
}

export interface QueryProgressItem {
  id: string;
  label: string;
  detail?: string;
  intent?: QueryIntent;
  kind?: "system" | "node" | "intent" | "source" | "warning";
  source?: SourceAnchor;
}
