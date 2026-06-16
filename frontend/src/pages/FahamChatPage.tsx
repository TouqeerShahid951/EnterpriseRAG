import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, AtSign, CheckCircle2, Circle, FileText, Loader2, Paperclip, Send, Square, X, XCircle } from "lucide-react";

import { uploadApi } from "../api/contracts";
import { canUploadToSpace } from "../authz";
import { AssistantZipTurn } from "../components/chat/AssistantZipTurn";
import { ChatEmptyState } from "../components/chat/ChatEmptyState";
import { ChatWorkspaceHeader } from "../components/chat/ChatWorkspaceHeader";
import { CorpusRail } from "../components/chat/CorpusRail";
import { EvidenceInspector, MobileEvidencePanel } from "../components/chat/EvidenceInspector";
import { FahamWorkspace } from "../components/layout/FahamWorkspace";
import type { RouteId } from "../routes";
import type { Document, SourceAnchor, User as AuthUser } from "../types/api";
import type { ChatTurn, SavedChatSession, UploadJobView } from "../types/chat";
import { buildChatUploadRequest } from "../state/chatUpload";
import { formatStageProgress, isUploadTerminalStatus, toUploadJobView, uploadFallbackSteps } from "../state/uploadJobProgress";
import { errorMessage } from "../utils/format";
import { isDocumentInSpace } from "../utils/groups";
import { withSourceDocumentTitle } from "../utils/sourceDocument";

const CHAT_UPLOAD_MAX_BYTES = 50 * 1024 * 1024;

export function FahamChatPage(props: Props) {
  const activeSpaceDocuments = useMemo(
    () => documentsInActiveSpace(props.documents, props.activeSpacePath),
    [props.activeSpacePath, props.documents],
  );
  const activeCurrentDocuments = useMemo(
    () => documentsInActiveSpace(props.currentDocuments, props.activeSpacePath),
    [props.activeSpacePath, props.currentDocuments],
  );
  const hasCorpus = activeCurrentDocuments.length > 0;
  const source = props.selectedSource ? withSourceDocumentTitle(props.selectedSource, props.documents) : null;
  const sourceCount = props.latestResponse?.sources.length ?? 0;
  const sourceNumber = selectedSourceNumber(props.latestResponse?.sources ?? [], props.selectedSource);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const streamPositionKey = useMemo(() => chatStreamPositionKey(props.chatTurns), [props.chatTurns]);

  useEffect(() => {
    const scrollNode = scrollRef.current;
    if (!scrollNode) return;
    scrollNode.scrollTo({ top: scrollNode.scrollHeight, behavior: "smooth" });
  }, [streamPositionKey, source?.chunk_id]);

  return (
    <FahamWorkspace activeRoute="chat" onLogout={props.onLogout} onNavigate={props.onNavigate} user={props.user}>
      <main className="rag-chat-page" id="main-content">
        <ChatWorkspaceHeader />
        <div className={source ? "rag-chat-body rag-chat-body-with-evidence" : "rag-chat-body"}>
          <CorpusRail
            activeSessionId={props.activeSessionId}
            hasPendingTurn={props.hasPendingTurn}
            onDeleteSession={props.deleteChatSession}
            onLoadSession={props.loadChatSession}
            onReset={props.onReset}
            loading={props.savedSessionsLoading}
            errorMessage={props.savedSessionsError}
            savedSessions={props.savedSessions}
          />
          <section className="rag-chat-thread" aria-label="Document chat">
            <div className="rag-chat-scroll" ref={scrollRef}>
              <div className="rag-chat-inner">
                {props.chatTurns.length === 0 ? (
                  <ChatEmptyState documents={activeCurrentDocuments} hasCorpus={hasCorpus} onQuestionChange={props.onQuestionChange} />
                ) : (
                  <ChatTurns
                    chatTurns={props.chatTurns}
                    documents={props.documents}
                    onCancelArtifactJob={props.onCancelArtifactJob}
                    onClarifyArtifactJob={props.onClarifyArtifactJob}
                    onRetryArtifactJob={props.onRetryArtifactJob}
                    onSelectSource={props.onSelectSource}
                    selectedSource={props.selectedSource}
                  />
                )}
                {source ? <MobileEvidencePanel onClose={() => props.onSelectSource(null)} source={source} sourceCount={sourceCount} sourceNumber={sourceNumber} /> : null}
              </div>
            </div>
            <ChatComposer activeDocuments={activeSpaceDocuments} hasCorpus={hasCorpus} {...props} />
          </section>
          {source ? <EvidenceInspector onClose={() => props.onSelectSource(null)} source={source} sourceCount={sourceCount} sourceNumber={sourceNumber} /> : null}
        </div>
      </main>
    </FahamWorkspace>
  );
}

function chatStreamPositionKey(chatTurns: ChatTurn[]): string {
  const lastTurn = chatTurns[chatTurns.length - 1];
  if (!lastTurn) return "empty";
  if (lastTurn.role === "user") return `${lastTurn.id}:${lastTurn.content.length}`;
  return [
    lastTurn.id,
    lastTurn.status,
    lastTurn.progress.length,
    lastTurn.streamText?.length ?? 0,
    lastTurn.response?.sources.length ?? 0,
  ].join(":");
}

function selectedSourceNumber(sources: SourceAnchor[], selectedSource: SourceAnchor | null): number | null {
  if (!selectedSource) return null;
  const index = sources.findIndex((source) => source.doc_id === selectedSource.doc_id && source.chunk_id === selectedSource.chunk_id);
  return index === -1 ? null : index + 1;
}

function ChatTurns({
  chatTurns,
  documents,
  onCancelArtifactJob,
  onClarifyArtifactJob,
  onRetryArtifactJob,
  onSelectSource,
  selectedSource,
}: Pick<Props, "chatTurns" | "documents" | "onCancelArtifactJob" | "onClarifyArtifactJob" | "onRetryArtifactJob" | "onSelectSource" | "selectedSource">) {
  return chatTurns.map((turn) =>
    turn.role === "user" ? (
      <div key={turn.id} className="flex justify-end">
        <div className="rag-user-message">{turn.content}</div>
      </div>
    ) : (
      <AssistantZipTurn
        key={turn.id}
        documents={documents}
        onCancelArtifactJob={onCancelArtifactJob}
        onClarifyArtifactJob={onClarifyArtifactJob}
        onRetryArtifactJob={onRetryArtifactJob}
        onSelectSource={onSelectSource}
        selectedSource={selectedSource}
        turn={turn}
      />
    ),
  );
}

function ChatComposer({
  addScopedDocument,
  activeDocuments,
  activeSpacePath,
  cancelPendingTurn,
  hasCorpus,
  hasPendingTurn,
  onQuestionChange,
  onQuestionSubmit,
  question,
  removeScopedDocument,
  scopedDocumentIds,
  user,
}: Props & { activeDocuments: Document[]; hasCorpus: boolean }) {
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const queryClient = useQueryClient();
  const [uploadJob, setUploadJob] = useState<ChatUploadJob | null>(null);
  const uploadSpace = activeSpacePath;
  const canUploadActiveSpace = Boolean(uploadSpace && canUploadToSpace(user, uploadSpace));
  const uploadJobId = uploadJob?.jobId ?? null;
  const mentionQuery = activeMentionQuery(question);
  const scopedDocuments = activeDocuments.filter((document) => scopedDocumentIds.includes(document.id));
  const mentionSuggestions = useMemo(
    () => mentionSuggestionsForDocuments(activeDocuments, scopedDocumentIds, mentionQuery),
    [activeDocuments, scopedDocumentIds, mentionQuery],
  );
  const uploadMutation = useMutation({
    mutationFn: ({ file, groupPath }: ChatUploadVariables) =>
      uploadApi.document(buildChatUploadRequest(file, groupPath)),
    onMutate: ({ file, groupPath }) => {
      setUploadJob({ fileName: file.name, jobId: null, space: groupPath, errorMessage: null });
    },
    onSuccess: (response, { file, groupPath }) => {
      setUploadJob({ fileName: file.name, jobId: response.job_id, space: groupPath, errorMessage: null });
    },
    onError: (error, { file, groupPath }) => {
      setUploadJob({
        fileName: file.name,
        jobId: null,
        space: groupPath,
        errorMessage: errorMessage(error, "Document upload failed."),
      });
    },
  });
  const uploadStatusQuery = useQuery({
    queryKey: ["upload", "status", uploadJobId],
    queryFn: () => uploadApi.status(uploadJobId ?? ""),
    enabled: Boolean(uploadJobId),
    refetchInterval: (query) => (isUploadTerminalStatus(query.state.data?.status) ? false : 2000),
  });
  const uploadJobView = uploadJob
    ? uploadJob.errorMessage
      ? failedComposerUploadJob(uploadJob.errorMessage)
      : uploadJobId
        ? toUploadJobView(uploadJobId, uploadStatusQuery.data)
        : localComposerUploadJob
    : null;

  useEffect(() => {
    if (uploadJobId && uploadStatusQuery.data?.status === "complete") {
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    }
  }, [queryClient, uploadJobId, uploadStatusQuery.data?.status]);

  function handleTagDocument(document: Document) {
    addScopedDocument(document.id);
    onQuestionChange(removeActiveMention(question));
    window.requestAnimationFrame(() => inputRef.current?.focus());
  }

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    event.target.value = "";
    uploadMutation.reset();
    if (!file) return;
    if (!isSupportedDocumentFile(file)) {
      setUploadJob({ fileName: file.name, jobId: null, space: uploadSpace, errorMessage: "Only PDF, DOCX, JPG, and PNG files can be uploaded from chat." });
      return;
    }
    if (file.size > CHAT_UPLOAD_MAX_BYTES) {
      setUploadJob({ fileName: file.name, jobId: null, space: uploadSpace, errorMessage: `${file.name} exceeds the 50 MB upload limit.` });
      return;
    }
    if (!uploadSpace) {
      setUploadJob({ fileName: file.name, jobId: null, space: uploadSpace, errorMessage: "Select a Knowledge Space before uploading." });
      return;
    }
    if (!canUploadActiveSpace) {
      setUploadJob({ fileName: file.name, jobId: null, space: uploadSpace, errorMessage: "Your account cannot upload to the active Knowledge Space." });
      return;
    }
    uploadMutation.mutate({ file, groupPath: uploadSpace });
  }

  return (
    <form onSubmit={onQuestionSubmit} className="border-t border-surface-border bg-surface-card p-5">
      <div className="mx-auto max-w-4xl">
        {scopedDocuments.length > 0 ? (
          <div className="rag-composer-scope" aria-label="Scoped documents">
            <span className="rag-composer-scope-label">Search scoped to</span>
            {scopedDocuments.map((document) => (
              <span key={document.id} className="rag-scope-chip">
                <FileText size={13} />
                {document.title}
                <button type="button" onClick={() => removeScopedDocument(document.id)} aria-label={`Remove ${document.title} from scope`}>
                  <X size={13} />
                </button>
              </span>
            ))}
          </div>
        ) : null}
        <div className="relative rounded-lg border border-surface-border bg-surface focus-within:border-primary focus-within:ring-2 focus-within:ring-primary">
          <textarea ref={inputRef} value={question} onChange={(event) => onQuestionChange(event.target.value)} className={`min-h-[56px] max-h-32 w-full resize-none rounded-lg border-none bg-transparent p-4 text-body-lg text-on-surface focus:outline-none ${canUploadActiveSpace ? "pr-28" : "pr-16"}`} placeholder={hasCorpus ? "Ask a question, or type @ to scope to a document..." : "Index a document before querying."} rows={1} />
          {canUploadActiveSpace ? (
            <>
              <input ref={fileInputRef} className="hidden" type="file" accept="application/pdf,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx,image/jpeg,.jpg,.jpeg,image/png,.png" onChange={handleFileChange} tabIndex={-1} aria-hidden="true" />
              <button
                type="button"
                disabled={uploadMutation.isPending}
                onClick={() => fileInputRef.current?.click()}
                className="rag-composer-icon-action absolute bottom-2 right-14"
                aria-label="Upload PDF, DOCX, JPG, or PNG, maximum 50 MB"
                title="Upload PDF, DOCX, JPG, or PNG, maximum 50 MB"
              >
                {uploadMutation.isPending ? <Loader2 className="animate-spin" size={18} /> : <Paperclip size={18} />}
              </button>
            </>
          ) : null}
          <button
            type={hasPendingTurn ? "button" : "submit"}
            disabled={!hasPendingTurn && (!hasCorpus || !question.trim())}
            onClick={hasPendingTurn ? cancelPendingTurn : undefined}
            className={`absolute bottom-2 right-2 flex h-10 w-10 items-center justify-center rounded-lg ${hasPendingTurn ? "rag-composer-stop-action" : "bg-primary text-on-primary"}`}
            aria-label={hasPendingTurn ? "Stop response generation" : "Send question"}
            title={hasPendingTurn ? "Stop response generation" : "Send question"}
          >
            {hasPendingTurn ? <Square fill="currentColor" size={16} /> : <Send size={18} />}
          </button>
          {mentionQuery !== null ? (
            <div className="rag-mention-menu" role="listbox" aria-label="Document suggestions">
              {mentionSuggestions.length > 0 ? (
                mentionSuggestions.map((document) => (
                  <button key={document.id} type="button" onClick={() => handleTagDocument(document)} role="option">
                    <FileText size={14} />
                    <span>
                      <strong>{document.title}</strong>
                      <small>{document.group_path}</small>
                    </span>
                  </button>
                ))
              ) : (
                <div className="rag-mention-empty">
                  <AtSign size={14} />
                  No matching documents in this space
                </div>
              )}
            </div>
          ) : null}
        </div>
        {uploadJob && uploadJobView ? (
          <ComposerUploadProgress
            fileName={uploadJob.fileName}
            job={uploadJobView}
            pollError={uploadStatusQuery.isError ? errorMessage(uploadStatusQuery.error, "Unable to poll upload status.") : null}
            space={uploadJob.space}
          />
        ) : null}
        <p className="mt-2 text-center text-[10px] font-semibold uppercase text-secondary">
          {canUploadActiveSpace ? "Paperclip uploads PDF, DOCX, JPG, or PNG files up to 50 MB into the active Knowledge Space. " : ""}@ tags narrow the retrieval scope.
        </p>
      </div>
    </form>
  );
}

function ComposerUploadProgress({ fileName, job, pollError, space }: { fileName: string; job: UploadJobView; pollError: string | null; space: string | null }) {
  const progressPct = Math.max(0, Math.min(100, job.progressPct));
  const stageProgress = formatStageProgress(job.stageProgress);
  const Icon = composerUploadIcon(job);
  const tone = composerUploadTone(job.status);
  const live = job.status === "queued" || job.status === "processing" ? "polite" : "off";
  return (
    <div className={`rag-composer-upload-status is-${tone}`} aria-live={live} role="status">
      <div className="rag-composer-upload-summary">
        <Icon className={job.status === "queued" || job.status === "processing" ? "animate-spin" : ""} size={16} />
        <div className="rag-composer-upload-copy">
          <div className="rag-composer-upload-title">
            <strong>{uploadStateLabel(job.status)}</strong>
            <span>{fileName}</span>
          </div>
          <p>{job.stageLabel}{space ? ` in ${space}` : ""}</p>
          <small>{job.stageDetail}</small>
          {stageProgress ? <small className="rag-composer-upload-stage-progress">{stageProgress}</small> : null}
        </div>
        <span className="rag-composer-upload-percent">{progressPct}%</span>
      </div>
      <div className="rag-composer-upload-progress" aria-label="Upload indexing progress" aria-valuemax={100} aria-valuemin={0} aria-valuenow={progressPct} role="progressbar">
        <span style={{ width: `${progressPct}%` }} />
      </div>
      <ol className="rag-composer-upload-steps" aria-label="Ingestion step status">
        {job.steps.map((step) => (
          <li key={step.id} className={`is-${step.state}`}>
            {composerStepIcon(step.state)}
            <span>{step.label}</span>
          </li>
        ))}
      </ol>
      {job.errorCode || job.errorMessage || pollError ? (
        <p className="rag-composer-upload-error">
          {job.errorCode ? <strong>{job.errorCode}: </strong> : null}
          {job.errorMessage ?? pollError}
        </p>
      ) : null}
    </div>
  );
}

const localComposerUploadJob: UploadJobView = {
  jobId: "",
  status: "queued",
  progressPct: 8,
  stage: "queued",
  stageLabel: "Uploading PDF",
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
  lastHeartbeatAt: null,
};

function failedComposerUploadJob(message: string): UploadJobView {
  return {
    jobId: "",
    status: "failed",
    progressPct: 0,
    stage: "failed",
    stageLabel: "Upload failed",
    stageDetail: "The PDF did not reach the indexing queue.",
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
    lastHeartbeatAt: null,
  };
}

function composerUploadIcon(job: UploadJobView) {
  if (job.status === "complete") return CheckCircle2;
  if (job.status === "failed") return XCircle;
  if (job.status === "human_review") return AlertTriangle;
  return Loader2;
}

function composerStepIcon(state: UploadJobView["steps"][number]["state"]) {
  if (state === "complete") return <CheckCircle2 aria-hidden="true" size={12} />;
  if (state === "failed") return <XCircle aria-hidden="true" size={12} />;
  if (state === "needs_review") return <AlertTriangle aria-hidden="true" size={12} />;
  if (state === "active") return <Loader2 aria-hidden="true" className="animate-spin" size={12} />;
  return <Circle aria-hidden="true" size={12} />;
}

function composerUploadTone(status: UploadJobView["status"]) {
  if (status === "complete") return "success";
  if (status === "failed") return "error";
  if (status === "human_review") return "warning";
  return "pending";
}

function uploadStateLabel(status: UploadJobView["status"]) {
  if (status === "complete") return "Completed";
  if (status === "failed") return "Failed";
  if (status === "human_review") return "Needs review";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function isSupportedDocumentFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return (
    file.type === "application/pdf"
    || file.type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    || file.type === "image/jpeg"
    || file.type === "image/png"
    || name.endsWith(".pdf")
    || name.endsWith(".docx")
    || name.endsWith(".jpg")
    || name.endsWith(".jpeg")
    || name.endsWith(".png")
  );
}

function activeMentionQuery(value: string): string | null {
  const match = /(^|\s)@([^\s@]*)$/.exec(value);
  return match ? match[2].toLowerCase() : null;
}

function removeActiveMention(value: string): string {
  return value.replace(/(^|\s)@([^\s@]*)$/, "$1").replace(/\s+$/, " ");
}

function mentionSuggestionsForDocuments(documents: Document[], scopedDocumentIds: string[], mentionQuery: string | null): Document[] {
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

function documentsInActiveSpace(documents: Document[], activeSpacePath: string | null): Document[] {
  if (!activeSpacePath) return documents;
  return documents.filter((document) => isDocumentInSpace(document.group_path, activeSpacePath));
}

type Props = {
  activeSessionId: string | null;
  activeSpacePath: string | null;
  addScopedDocument: (documentId: string) => void;
  cancelPendingTurn: () => void;
  chatTurns: ChatTurn[];
  currentDocuments: Document[];
  deleteChatSession: (sessionId: string) => void;
  documents: Document[];
  documentsLoading: boolean;
  hasPendingTurn: boolean;
  latestResponse: { sources: SourceAnchor[] } | null;
  loadChatSession: (sessionId: string) => void;
  onLogout: () => void;
  onActiveSpaceChange: (groupPath: string | null) => void;
  onCancelArtifactJob: (jobId: string) => Promise<void>;
  onClarifyArtifactJob: (jobId: string, answers: Record<string, string>) => Promise<void>;
  onNavigate: (route: RouteId) => void;
  onQuestionChange: (value: string) => void;
  onQuestionSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onReset: () => void;
  onRetryArtifactJob: (jobId: string) => Promise<void>;
  onSelectSource: (source: SourceAnchor | null) => void;
  question: string;
  removeScopedDocument: (documentId: string) => void;
  savedSessions: SavedChatSession[];
  savedSessionsError: string | null;
  savedSessionsLoading: boolean;
  scopedDocumentIds: string[];
  selectedSource: SourceAnchor | null;
  user: AuthUser;
};

type ChatUploadJob = {
  fileName: string;
  jobId: string | null;
  space: string | null;
  errorMessage: string | null;
};

type ChatUploadVariables = {
  file: File;
  groupPath: string;
};
