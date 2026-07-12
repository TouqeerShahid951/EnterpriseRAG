import type { ClearanceLevel, ParserProvenance, QueryRequest, QueryIntent, QuerySourceMode, RAGResponse, SourceAnchor, UploadJobStage, UploadJobStageProgress, UploadJobState, UploadJobStep } from "./api";

export interface PdfUploadDraft {
  files: File[];
  groupPath: string;
  sharedGroupPaths: string[];
  clearanceLevel: ClearanceLevel;
  effectiveDate: string;
  expiryDate: string;
  description: string;
  supersedesText: string;
}

export interface UploadJobView {
  jobId: string;
  documentId: string | null;
  retryOfJobId: string | null;
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
  completedAt: string | null;
  lastHeartbeatAt: string | null;
}

export interface UploadBatchItemView {
  id: string;
  fileName: string;
  fileSize: number | null;
  groupPath: string;
  clearanceLevel: ClearanceLevel;
  requestState: "uploading" | "accepted" | "failed";
  job: UploadJobView | null;
  uploadError: Error | null;
  jobError: Error | null;
}

interface UserTurn {
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
  sourceMode?: QuerySourceMode;
  querySourceId?: string | null;
  progress: QueryProgressItem[];
  response?: RAGResponse;
  streamText?: string;
  errorMessage?: string;
}

export type ChatTurn = UserTurn | AssistantTurn;

export interface SavedChatSessionSummary {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  questionCount: number;
}

export interface SavedChatSession extends SavedChatSessionSummary {
  turns: ChatTurn[];
}

export interface SavedChatSessionPage {
  items: SavedChatSessionSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface QueryRunVariables {
  assistantTurnId: string;
  request: QueryRequest;
  sessionId: string;
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
