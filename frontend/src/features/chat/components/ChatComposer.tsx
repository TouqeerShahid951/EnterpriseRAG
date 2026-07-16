import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AtSign, Database, FileText, Layers3, Loader2, Paperclip, Search, Send, Square, X } from "lucide-react";
import { ingestJobsApi, queryApi, uploadApi } from "@/lib/api/contracts";
import { canUploadToSpace } from "@/lib/auth/authz";
import { buildChatUploadRequest } from "@/features/chat/state/chatUpload";
import { ComposerUploadProgress } from "@/features/chat/components/ComposerUploadProgress";
import {
  activeMentionQuery,
  composerPlaceholder,
  failedComposerUploadJob,
  isSupportedDocumentFile,
  localComposerUploadJob,
  mentionSuggestionsForDocuments,
  removeActiveMention,
} from "@/features/chat/utils/chatComposerUtils";
import { isUploadTerminalStatus, toUploadJobView } from "@/features/upload/state/uploadJobProgress";
import type { Props } from "@/features/chat/types/chatPageTypes";
import type { Document, QuerySource, QuerySourceMode } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";

const CHAT_UPLOAD_MAX_BYTES = 50 * 1024 * 1024;

export function ChatComposer({
  addScopedDocument,
  activeDocuments,
  activeSpacePath,
  activeSessionHasPendingTurn,
  cancelPendingTurn,
  hasCorpus,
  hasPendingGeneration,
  onSelectedQuerySourceChange,
  onQuestionChange,
  onQuestionSubmit,
  onSourceModeChange,
  question,
  removeScopedDocument,
  scopedDocumentIds,
  selectedQuerySourceId,
  sourceMode,
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
  const pendingElsewhere = hasPendingGeneration && !activeSessionHasPendingTurn;
  const dbMode = sourceMode === "db_only" || sourceMode === "hybrid";
  const querySourcesQuery = useQuery({
    queryKey: ["query-sources", activeSpacePath ?? "all"],
    queryFn: () => queryApi.sources({ group_path: activeSpacePath }),
    enabled: dbMode,
    staleTime: 15000,
    retry: false,
  });
  const querySources = querySourcesQuery.data?.items ?? [];
  const hasQueryableSource = hasCorpus || querySources.length > 0;
  const canSubmitQuestion = question.trim().length > 0
    && !hasPendingGeneration
    && (
      sourceMode === "db_only"
        ? querySources.length > 0
        : sourceMode === "corpus_only"
          ? hasCorpus
          : hasQueryableSource
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
  const graphStatusQuery = useQuery({
    queryKey: ["ingest-jobs", "graphrag-status", "chat-upload", uploadJobId],
    queryFn: ingestJobsApi.graphragStatus,
    enabled: uploadJobView?.status === "complete",
    refetchInterval: uploadJobView?.status === "complete" ? 5000 : false,
    staleTime: 3000,
    retry: false,
  });
  const graphStatusError = graphStatusQuery.isError ? errorMessage(graphStatusQuery.error, "Unable to load graph enrichment status.") : null;

  useEffect(() => {
    if (uploadJobId && uploadStatusQuery.data?.status === "complete") {
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    }
  }, [queryClient, uploadJobId, uploadStatusQuery.data?.status]);

  useEffect(() => {
    if (!selectedQuerySourceId) return;
    if (!querySources.some((source) => source.id === selectedQuerySourceId)) {
      onSelectedQuerySourceChange("");
    }
  }, [onSelectedQuerySourceChange, querySources, selectedQuerySourceId]);

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
      setUploadJob({ fileName: file.name, jobId: null, space: uploadSpace, errorMessage: "Only PDF, DOCX, JPG, PNG, and JSON files can be uploaded from chat." });
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

  function handleQuestionKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (canSubmitQuestion) {
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <form onSubmit={onQuestionSubmit} className="rag-composer-shell">
      <div className="rag-composer-inner">
        <ComposerSourceControls
          dbMode={dbMode}
          loadingSources={querySourcesQuery.isLoading}
          onSelectedQuerySourceChange={onSelectedQuerySourceChange}
          onSourceModeChange={onSourceModeChange}
          querySources={querySources}
          selectedQuerySourceId={selectedQuerySourceId}
          sourceMode={sourceMode}
        />
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
        <div className="rag-composer-box relative">
          <textarea ref={inputRef} value={question} onChange={(event) => onQuestionChange(event.target.value)} onKeyDown={handleQuestionKeyDown} className={`rag-composer-input ${canUploadActiveSpace ? "rag-composer-input-with-upload" : "rag-composer-input-with-send"}`} aria-label="Ask a question" placeholder={composerPlaceholder(sourceMode, hasCorpus, querySources.length)} rows={1} />
          {canUploadActiveSpace ? (
            <>
              <input ref={fileInputRef} className="hidden" type="file" accept="application/pdf,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx,image/jpeg,.jpg,.jpeg,image/png,.png,application/json,.json" onChange={handleFileChange} tabIndex={-1} aria-hidden="true" />
              <button
                type="button"
                disabled={uploadMutation.isPending}
                onClick={() => fileInputRef.current?.click()}
                className="rag-composer-icon-action absolute bottom-2 right-14"
                aria-label="Upload PDF, DOCX, JPG, PNG, or JSON, maximum 50 MB"
                title="Upload PDF, DOCX, JPG, PNG, or JSON, maximum 50 MB"
              >
                {uploadMutation.isPending ? <Loader2 className="animate-spin" size={18} /> : <Paperclip size={18} />}
              </button>
            </>
          ) : null}
          <button
            type={activeSessionHasPendingTurn ? "button" : "submit"}
            disabled={!activeSessionHasPendingTurn && !canSubmitQuestion}
            onClick={activeSessionHasPendingTurn ? cancelPendingTurn : undefined}
            className={`rag-composer-send-action absolute bottom-2 right-2 ${activeSessionHasPendingTurn ? "rag-composer-stop-action" : "bg-primary text-on-primary"}`}
            aria-label={activeSessionHasPendingTurn ? "Stop response generation" : pendingElsewhere ? "A response is generating in another chat" : "Send question"}
            title={activeSessionHasPendingTurn ? "Stop response generation" : pendingElsewhere ? "A response is generating in another chat" : "Send question"}
          >
            {activeSessionHasPendingTurn ? <Square fill="currentColor" size={16} /> : <Send size={18} />}
          </button>
          {mentionQuery !== null && sourceMode !== "db_only" ? (
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
            graphStatus={graphStatusQuery.data}
            graphStatusError={graphStatusError}
            job={uploadJobView}
            pollError={uploadStatusQuery.isError ? errorMessage(uploadStatusQuery.error, "Unable to poll upload status.") : null}
            space={uploadJob.space}
          />
        ) : null}
        <p className="mt-2 text-center text-[10px] font-semibold uppercase text-secondary">
          {pendingElsewhere
            ? "A response is generating in another chat. You can keep browsing, then send when it finishes."
            : sourceMode === "db_only"
              ? "Live DB source selected."
              : `${canUploadActiveSpace ? "Paperclip uploads PDF, DOCX, JPG, PNG, or JSON files up to 50 MB into the active Knowledge Space. " : ""}@ tags narrow the retrieval scope.`}
        </p>
      </div>
    </form>
  );
}

function ComposerSourceControls({
  dbMode,
  loadingSources,
  onSelectedQuerySourceChange,
  onSourceModeChange,
  querySources,
  selectedQuerySourceId,
  sourceMode,
}: {
  dbMode: boolean;
  loadingSources: boolean;
  onSelectedQuerySourceChange: (sourceId: string) => void;
  onSourceModeChange: (mode: QuerySourceMode) => void;
  querySources: QuerySource[];
  selectedQuerySourceId: string;
  sourceMode: QuerySourceMode;
}) {
  const modes: Array<{ mode: QuerySourceMode; label: string; icon: typeof Search }> = [
    { mode: "auto", label: "Auto", icon: Search },
    { mode: "corpus_only", label: "Documents", icon: FileText },
    { mode: "db_only", label: "Live DB", icon: Database },
    { mode: "hybrid", label: "Hybrid", icon: Layers3 },
  ];
  return (
    <div className="rag-composer-source-row">
      <div className="rag-composer-source-segments" aria-label="Query source mode">
        {modes.map(({ mode, label, icon: Icon }) => (
          <button
            key={mode}
            type="button"
            className={sourceMode === mode ? "is-active" : ""}
            onClick={() => onSourceModeChange(mode)}
            aria-pressed={sourceMode === mode}
          >
            <Icon size={14} />
            <span>{label}</span>
          </button>
        ))}
      </div>
      {dbMode ? (
        <label className="rag-composer-source-select">
          <span className="sr-only">Live database source</span>
          <select
            aria-label="Live database source"
            disabled={loadingSources || querySources.length === 0}
            value={selectedQuerySourceId}
            onChange={(event) => onSelectedQuerySourceChange(event.target.value)}
          >
            <option value="">{loadingSources ? "Loading sources" : querySources.length ? "All visible DB sources" : "No DB sources"}</option>
            {querySources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </div>
  );
}

export type ChatUploadJob = {
  fileName: string;
  jobId: string | null;
  space: string | null;
  errorMessage: string | null;
};

export type ChatUploadVariables = {
  file: File;
  groupPath: string;
};
