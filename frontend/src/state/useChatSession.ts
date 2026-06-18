import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useInfiniteQuery, useMutation, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { queryApi } from "../api/contracts";
import { isGlobalAdmin } from "../authz";
import type { ArtifactJobSummary, RagSseEvent, RAGResponse, SourceAnchor, User } from "../types/api";
import type { AssistantTurn, ChatTurn, QueryProgressItem, QueryRunVariables, SavedChatSession, SavedChatSessionPage } from "../types/chat";
import { errorMessage, formatIntent } from "../utils/format";
import { createId } from "./ids";

const CHAT_HISTORY_PAGE_SIZE = 30;

type ChatHistoryQueryData = InfiniteData<SavedChatSessionPage, number>;

export function useChatSession(currentUser: User | null) {
  const queryClient = useQueryClient();
  const sessionIdRef = useRef<string | null>(null);
  const activeAbortControllerRef = useRef<AbortController | null>(null);
  const activeAssistantTurnIdRef = useRef<string | null>(null);
  const cancelledAssistantTurnIdsRef = useRef<Set<string>>(new Set());
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [chatTurns, setChatTurns] = useState<ChatTurn[]>([]);
  const [scopedDocumentIds, setScopedDocumentIds] = useState<string[]>([]);
  const [selectedSource, setSelectedSource] = useState<SourceAnchor | null>(null);
  const [activeSpacePath, setActiveSpacePath] = useState<string | null>(() => defaultSpacePath(currentUser));
  const chatHistoryQueryKey = useMemo(
    () => ["chat-sessions", currentUser?.user_id ?? "anonymous", currentUser?.permission_version ?? 0] as const,
    [currentUser?.permission_version, currentUser?.user_id],
  );
  const defaultActiveSpacePath = useMemo(() => defaultSpacePath(currentUser), [currentUser?.permission_version, currentUser?.user_id]);

  const savedSessionsQuery = useInfiniteQuery({
    queryKey: chatHistoryQueryKey,
    queryFn: ({ pageParam }) => queryApi.listSessions({ limit: CHAT_HISTORY_PAGE_SIZE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const loadedCount = allPages.reduce((count, page) => count + page.items.length, 0);
      return loadedCount < lastPage.total ? loadedCount : undefined;
    },
    enabled: Boolean(currentUser),
  });
  const savedSessions = useMemo(
    () => savedSessionsQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [savedSessionsQuery.data],
  );
  const savedSessionsTotal = savedSessionsQuery.data?.pages[0]?.total ?? savedSessions.length;

  const queryMutation = useMutation<RAGResponse, Error, QueryRunVariables>({
    mutationFn: (variables) =>
      runStreamingQuery(variables, (event) => {
        setChatTurns((turns) => applyStreamEvent(turns, variables.assistantTurnId, event));
      }),
    onSuccess: (result, variables) => {
      if (cancelledAssistantTurnIdsRef.current.has(variables.assistantTurnId)) {
        return;
      }
      sessionIdRef.current = result.session_id;
      setActiveSessionId(result.session_id);
      setChatTurns((turns) => replaceAssistantTurn(turns, variables.assistantTurnId, result));
      void queryClient.invalidateQueries({ queryKey: chatHistoryQueryKey });
    },
    onError: (error, variables) => {
      if (cancelledAssistantTurnIdsRef.current.has(variables.assistantTurnId) || isAbortError(error)) {
        setChatTurns((turns) => markAssistantTurnCancelled(turns, variables.assistantTurnId));
        return;
      }
      setChatTurns((turns) => markAssistantTurnErrored(turns, variables.assistantTurnId, errorMessage(error, "The query request failed.")));
    },
    onSettled: (_result, _error, variables) => {
      if (activeAssistantTurnIdRef.current === variables.assistantTurnId) {
        activeAssistantTurnIdRef.current = null;
        activeAbortControllerRef.current = null;
      }
      cancelledAssistantTurnIdsRef.current.delete(variables.assistantTurnId);
    },
  });

  const loadSessionMutation = useMutation<SavedChatSession, Error, string>({
    mutationFn: queryApi.getSession,
    onSuccess: (session) => {
      sessionIdRef.current = session.id;
      setActiveSessionId(session.id);
      setChatTurns(session.turns);
      setScopedDocumentIds([]);
      setSelectedSource(null);
      setQuestion("");
    },
  });

  const deleteSessionMutation = useMutation<void, Error, string, { previous?: ChatHistoryQueryData }>({
    mutationFn: queryApi.deleteSession,
    onMutate: async (sessionId) => {
      await queryClient.cancelQueries({ queryKey: chatHistoryQueryKey });
      const previous = queryClient.getQueryData<ChatHistoryQueryData>(chatHistoryQueryKey);
      queryClient.setQueryData<ChatHistoryQueryData>(chatHistoryQueryKey, (current) => removeSessionFromPages(current, sessionId));
      return { previous };
    },
    onError: (_error, _sessionId, context) => {
      const previous = context?.previous;
      if (previous) queryClient.setQueryData(chatHistoryQueryKey, previous);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: chatHistoryQueryKey });
    },
  });

  const latestResponse = useMemo(() => latestCompleteResponse(chatTurns), [chatTurns]);
  const hasPendingTurn = chatTurns.some((turn) => turn.role === "assistant" && turn.status === "pending");
  const activeArtifactJobIds = useMemo(() => activeArtifactJobs(chatTurns), [chatTurns]);
  const activeArtifactJobKey = activeArtifactJobIds.join("|");

  useEffect(() => {
    abortActiveQuery();
    loadSessionMutation.reset();
    sessionIdRef.current = null;
    setActiveSessionId(null);
    setChatTurns([]);
    setScopedDocumentIds([]);
    setSelectedSource(null);
    setQuestion("");
    setActiveSpacePath(defaultActiveSpacePath);
  }, [defaultActiveSpacePath, chatHistoryQueryKey]);

  useEffect(() => {
    return () => abortActiveQuery();
  }, []);

  useEffect(() => {
    const jobIds = activeArtifactJobKey ? activeArtifactJobKey.split("|") : [];
    if (!currentUser || jobIds.length === 0) return;
    let cancelled = false;

    async function pollArtifactJobs() {
      const results = await Promise.allSettled(jobIds.map((jobId) => queryApi.getArtifactJob(jobId)));
      if (cancelled) return;
      setChatTurns((turns) =>
        results.reduce(
          (nextTurns, result) => (result.status === "fulfilled" ? mergeArtifactJobIntoTurns(nextTurns, result.value) : nextTurns),
          turns,
        ),
      );
    }

    void pollArtifactJobs();
    const timer = window.setInterval(() => {
      void pollArtifactJobs();
    }, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeArtifactJobKey, currentUser?.permission_version, currentUser?.user_id]);

  function resetChat() {
    abortActiveQuery();
    loadSessionMutation.reset();
    sessionIdRef.current = null;
    setActiveSessionId(null);
    setChatTurns([]);
    setScopedDocumentIds([]);
    setSelectedSource(null);
    setQuestion("");
  }

  function handleQuestionSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submitQuestion(question);
  }

  function submitQuestion(rawQuestion: string) {
    const nextQuestion = rawQuestion.trim();
    if (!nextQuestion || !currentUser || hasPendingTurn) {
      return;
    }
    const queryDocumentIds = scopedDocumentIds;
    const sessionId = sessionIdRef.current ?? createId("session");
    sessionIdRef.current = sessionId;
    setActiveSessionId(sessionId);
    const assistantTurn = createAssistantTurn(nextQuestion, queryDocumentIds, activeSpacePath);
    setChatTurns((turns) => [...turns, createUserTurn(nextQuestion), assistantTurn]);
    setSelectedSource(null);
    setQuestion("");
    setScopedDocumentIds([]);
    startStreamingQuery({
      assistantTurnId: assistantTurn.id,
      request: {
        query: nextQuestion,
        session_id: sessionId,
        client_request_id: assistantTurn.id,
        group_path: activeSpacePath,
        document_ids: queryDocumentIds.length ? queryDocumentIds : undefined,
      },
    });
  }

  function cancelPendingTurn() {
    const assistantTurnId = activeAssistantTurnIdRef.current ?? latestPendingAssistantTurnId(chatTurns);
    if (!assistantTurnId) return;
    cancelledAssistantTurnIdsRef.current.add(assistantTurnId);
    activeAbortControllerRef.current?.abort();
    setChatTurns((turns) => markAssistantTurnCancelled(turns, assistantTurnId));
  }

  function changeActiveSpacePath(groupPath: string | null) {
    if (hasPendingTurn || !currentUser) return;
    if (groupPath === null) {
      if (!isGlobalAdmin(currentUser)) return;
      setActiveSpacePath(null);
      setScopedDocumentIds([]);
      setSelectedSource(null);
      return;
    }
    if (!isGlobalAdmin(currentUser) && !currentUser.group_paths.includes(groupPath)) return;
    setActiveSpacePath(groupPath);
    setScopedDocumentIds([]);
    setSelectedSource(null);
  }

  function addScopedDocument(documentId: string) {
    setScopedDocumentIds((current) => (current.includes(documentId) ? current : [...current, documentId]));
  }

  function removeScopedDocument(documentId: string) {
    setScopedDocumentIds((current) => current.filter((candidate) => candidate !== documentId));
  }

  function loadChatSession(sessionId: string) {
    if (hasPendingTurn || loadSessionMutation.isPending) return;
    loadSessionMutation.mutate(sessionId);
  }

  function deleteChatSession(sessionId: string) {
    if (hasPendingTurn) return;
    deleteSessionMutation.mutate(sessionId);
    if (activeSessionId === sessionId) resetChat();
  }

  function handleRetry(assistantTurnId: string) {
    const turn = chatTurns.find((candidate) => candidate.id === assistantTurnId);
    const retrySpacePath = turn?.role === "assistant" ? turn.groupPath ?? activeSpacePath : null;
    if (!turn || turn.role !== "assistant" || !currentUser || hasPendingTurn) {
      return;
    }
    setChatTurns((turns) =>
      turns.map((candidate) =>
        candidate.id === assistantTurnId && candidate.role === "assistant"
          ? {
              ...candidate,
              status: "pending",
              progress: initialProgressForQuestion(turn.question, "Replaying retrieval graph", turn.documentIds ?? [], retrySpacePath),
              streamText: undefined,
              errorMessage: undefined,
            }
          : candidate,
      ),
    );
    setSelectedSource(null);
    startStreamingQuery({
      assistantTurnId,
      request: {
        query: turn.question,
        session_id: sessionIdRef.current,
        client_request_id: createId("query"),
        group_path: retrySpacePath,
        document_ids: turn.documentIds?.length ? turn.documentIds : undefined,
      },
    });
  }

  async function clarifyArtifactJob(jobId: string, answers: Record<string, string>) {
    const response = await queryApi.clarifyArtifactJob(jobId, answers);
    setChatTurns((turns) => mergeArtifactJobIntoTurns(turns, response.job));
  }

  async function cancelArtifactJob(jobId: string) {
    const response = await queryApi.cancelArtifactJob(jobId);
    setChatTurns((turns) => mergeArtifactJobIntoTurns(turns, response.job));
  }

  async function retryArtifactJob(jobId: string) {
    const response = await queryApi.retryArtifactJob(jobId);
    setChatTurns((turns) => mergeArtifactJobIntoTurns(turns, response.job));
  }

  function startStreamingQuery(variables: Omit<QueryRunVariables, "signal">) {
    abortActiveQuery();
    const abortController = new AbortController();
    activeAbortControllerRef.current = abortController;
    activeAssistantTurnIdRef.current = variables.assistantTurnId;
    queryMutation.mutate({ ...variables, signal: abortController.signal });
  }

  function abortActiveQuery() {
    activeAbortControllerRef.current?.abort();
    activeAbortControllerRef.current = null;
    activeAssistantTurnIdRef.current = null;
  }

  return {
    activeSessionId,
    activeSpacePath,
    changeActiveSpacePath,
    deleteChatSession,
    chatTurns,
    cancelPendingTurn,
    cancelArtifactJob,
    handleQuestionSubmit,
    handleRetry,
    clarifyArtifactJob,
    hasPendingTurn,
    latestResponse,
    loadChatSession,
    question,
    resetChat,
    addScopedDocument,
    removeScopedDocument,
    retryArtifactJob,
    scopedDocumentIds,
    savedSessions,
    savedSessionsError: savedSessionsQuery.isError ? errorMessage(savedSessionsQuery.error, "Chat history could not be loaded.") : null,
    savedSessionLoadError: loadSessionMutation.isError ? errorMessage(loadSessionMutation.error, "Chat session could not be loaded.") : null,
    savedSessionsFetchingMore: savedSessionsQuery.isFetchingNextPage,
    savedSessionsHasMore: Boolean(savedSessionsQuery.hasNextPage),
    savedSessionsLoading: savedSessionsQuery.isLoading,
    savedSessionsTotal,
    loadMoreSavedSessions: () => {
      if (savedSessionsQuery.hasNextPage && !savedSessionsQuery.isFetchingNextPage) {
        void savedSessionsQuery.fetchNextPage();
      }
    },
    loadingSessionId: loadSessionMutation.isPending ? loadSessionMutation.variables ?? null : null,
    selectedSource,
    setQuestion,
    setSelectedSource,
  };
}

function createUserTurn(content: string): ChatTurn {
  return { id: createId("user"), role: "user", content, createdAt: new Date().toISOString() };
}

function removeSessionFromPages(current: ChatHistoryQueryData | undefined, sessionId: string): ChatHistoryQueryData | undefined {
  if (!current) return current;
  const containedSession = current.pages.some((page) => page.items.some((session) => session.id === sessionId));
  if (!containedSession) return current;
  return {
    ...current,
    pages: current.pages.map((page) => ({
      ...page,
      total: Math.max(0, page.total - 1),
      items: page.items.filter((session) => session.id !== sessionId),
    })),
  };
}

function createAssistantTurn(question: string, documentIds: string[] = [], groupPath: string | null = null): AssistantTurn {
  return {
    id: createId("assistant"),
    role: "assistant",
    status: "pending",
    question,
    groupPath,
    documentIds,
    progress: initialProgressForQuestion(question, "Opening retrieval graph", documentIds, groupPath),
    createdAt: new Date().toISOString(),
  };
}

function initialProgressForQuestion(question: string, graphLabel = "Opening retrieval graph", documentIds: string[] = [], groupPath: string | null = null): QueryProgressItem[] {
  return [
    {
      id: createId("progress"),
      label: "Analyzing question",
      detail: compactText(question),
      kind: "system",
    },
    {
      id: createId("progress"),
      label: graphLabel,
      detail: documentIds.length ? "Preparing tagged document search" : `Preparing ${groupPath ?? "Knowledge Space"} search`,
      kind: "node",
    },
  ];
}

function replaceAssistantTurn(turns: ChatTurn[], assistantTurnId: string, response: RAGResponse): ChatTurn[] {
  return turns.map((turn) =>
    turn.id === assistantTurnId && turn.role === "assistant" ? { ...turn, status: "complete", response } : turn,
  );
}

function activeArtifactJobs(turns: ChatTurn[]): string[] {
  const ids = new Set<string>();
  for (const turn of turns) {
    if (turn.role !== "assistant") continue;
    const job = turn.response?.artifact_job;
    if (job && !isArtifactJobTerminal(job.status)) {
      ids.add(job.id);
    }
  }
  return [...ids];
}

function mergeArtifactJobIntoTurns(turns: ChatTurn[], job: ArtifactJobSummary): ChatTurn[] {
  return turns.map((turn) => {
    if (turn.role !== "assistant" || !turn.response?.artifact_job || turn.response.artifact_job.id !== job.id) {
      return turn;
    }
    const artifacts = mergeArtifacts(turn.response.artifacts ?? [], job.artifacts);
    return {
      ...turn,
      response: {
        ...turn.response,
        artifact_job: job,
        artifacts,
      },
    };
  });
}

function mergeArtifacts(current: RAGResponse["artifacts"], next: RAGResponse["artifacts"]): RAGResponse["artifacts"] {
  const byId = new Map<string, NonNullable<RAGResponse["artifacts"]>[number]>();
  for (const artifact of current ?? []) byId.set(artifact.id, artifact);
  for (const artifact of next ?? []) byId.set(artifact.id, artifact);
  return [...byId.values()];
}

function isArtifactJobTerminal(status: ArtifactJobSummary["status"]): boolean {
  return status === "complete" || status === "partial" || status === "failed" || status === "cancelled";
}

function latestCompleteResponse(turns: ChatTurn[]): RAGResponse | null {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index];
    if (turn.role === "assistant" && turn.status === "complete") {
      return turn.response ?? null;
    }
  }
  return null;
}

async function runStreamingQuery(
  variables: QueryRunVariables,
  onEvent: (event: RagSseEvent) => void,
): Promise<RAGResponse> {
  let finalResponse: RAGResponse | null = null;
  for await (const event of queryApi.stream(variables.request, { signal: variables.signal })) {
    onEvent(event);
    if (event.event === "done") {
      finalResponse = event.data;
    }
    if (event.event === "verified") {
      finalResponse = event.data;
    }
    if (event.event === "error") {
      throw new Error(event.data.message || event.data.code);
    }
  }
  if (!finalResponse) {
    throw new Error("The query stream ended before returning a final answer.");
  }
  return finalResponse;
}

function markAssistantTurnErrored(turns: ChatTurn[], assistantTurnId: string, message: string): ChatTurn[] {
  return turns.map((turn) =>
    turn.id === assistantTurnId && turn.role === "assistant"
      ? { ...turn, status: "error", errorMessage: message }
      : turn,
  );
}

function markAssistantTurnCancelled(turns: ChatTurn[], assistantTurnId: string): ChatTurn[] {
  return turns.map((turn) => {
    if (turn.id !== assistantTurnId || turn.role !== "assistant") return turn;
    if (turn.status === "complete") return turn;
    if (turn.status === "cancelled") return turn;
    return {
      ...turn,
      status: "cancelled",
      errorMessage: undefined,
      progress: [
        ...turn.progress,
        {
          id: createId("progress"),
          label: "Generation stopped",
          detail: "Request cancelled.",
          kind: "warning",
        },
      ],
    };
  });
}

function latestPendingAssistantTurnId(turns: ChatTurn[]): string | null {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index];
    if (turn.role === "assistant" && turn.status === "pending") {
      return turn.id;
    }
  }
  return null;
}

function isAbortError(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "name" in error && error.name === "AbortError");
}

function applyStreamEvent(turns: ChatTurn[], assistantTurnId: string, event: RagSseEvent): ChatTurn[] {
  return turns.map((turn) => {
    if (turn.id !== assistantTurnId || turn.role !== "assistant") return turn;
    if (event.event === "token") return { ...turn, streamText: appendText(turn.streamText, event.data.text) };
    if (event.event === "done") return { ...turn, status: "complete", response: event.data, streamText: event.data.answer };
    if (event.event === "verified") {
      return {
        ...turn,
        status: "complete",
        response: event.data,
        streamText: event.data.answer,
        progress: [...turn.progress, verifiedProgress(event.data.faithfulness_status)],
      };
    }
    const progress = progressFromEvent(event);
    return progress ? { ...turn, progress: [...turn.progress, progress] } : turn;
  });
}

function verifiedProgress(status: RAGResponse["faithfulness_status"]): QueryProgressItem {
  return {
    id: createId("progress"),
    label: status === "checked" ? "Grounding verified" : status === "failed" ? "Grounding check failed" : "Grounding check complete",
    detail: status === "checked" ? "Answer claims were checked against cited sources" : humanizeNode(status),
    kind: status === "failed" ? "warning" : "system",
  };
}

function progressFromEvent(event: RagSseEvent): QueryProgressItem | null {
  if (event.event === "trace" && event.data.node) {
    const nodeProgress = progressForNode(event.data.node);
    return {
      id: createId("progress"),
      label: nodeProgress.label,
      detail: executionDetail(event.data.execution_mode, event.data.detail) ?? event.data.agent ?? nodeProgress.detail,
      kind: "node",
    };
  }
  if (event.event === "intent") {
    return {
      id: createId("progress"),
      label: "Question type identified",
      detail: formatIntent(event.data.intent),
      intent: event.data.intent,
      kind: "intent",
    };
  }
  if (event.event === "source") {
    return {
      id: createId("progress"),
      label: "Evidence source found",
      detail: sourceDetail(event.data),
      kind: "source",
      source: event.data,
    };
  }
  if (event.event === "artifact") {
    return {
      id: createId("progress"),
      label: "File ready",
      detail: event.data.filename,
      kind: "system",
    };
  }
  if (event.event === "artifact_job") {
    return {
      id: createId("progress"),
      label: "Document job queued",
      detail: artifactJobProgressDetail(event.data),
      kind: "system",
    };
  }
  if (event.event === "warning") {
    return { id: createId("progress"), label: "Warning", detail: warningDetail(event), kind: "warning" };
  }
  return null;
}

function artifactJobProgressDetail(job: ArtifactJobSummary): string {
  const formats = job.requested_formats.map((format) => format.toUpperCase()).join(", ");
  const detail = job.stage_detail?.trim() || job.stage_label?.trim() || humanizeNode(job.status);
  return `${detail}${formats ? ` · ${formats}` : ""}`;
}

function executionDetail(mode?: string, detail?: string | null): string | null {
  if (mode === "ai_assisted") return detail ? `AI-assisted · ${humanizeNode(detail)}` : "AI-assisted";
  if (mode === "fallback") return detail ? `Rules fallback · ${humanizeNode(detail)}` : "Rules fallback";
  if (mode === "deterministic") return "Rules-only";
  return null;
}

function progressForNode(node: string): Pick<QueryProgressItem, "label" | "detail"> {
  const labels: Record<string, Pick<QueryProgressItem, "label" | "detail">> = {
    session_memory: { label: "Checking chat context", detail: "Looking for prior session hints" },
    intent_router: { label: "Classifying question", detail: "Choosing the retrieval route" },
    query_planner: { label: "Planning retrieval path", detail: "Breaking the question into evidence targets" },
    abac_retriever: { label: "Searching permitted documents", detail: "Applying access filters first" },
    reranker: { label: "Ranking candidate passages", detail: "Prioritizing likely evidence" },
    verifier: { label: "Checking evidence quality", detail: "Deciding whether to retry retrieval" },
    temporal_resolver: { label: "Resolving document timeline", detail: "Preferring current effective sources" },
    contradiction_detector: { label: "Checking for conflicts", detail: "Comparing claims across sources" },
    evidence_builder: { label: "Assembling citations", detail: "Preparing source anchors" },
    synthesizer: { label: "Drafting cited answer", detail: "Writing from retrieved evidence" },
    faithfulness_checker: { label: "Verifying answer grounding", detail: "Checking claims against sources" },
    artifact_generator: { label: "Preparing requested files", detail: "Rendering downloadable artifacts" },
    response_serializer: { label: "Finalizing response", detail: "Packaging answer and citations" },
  };
  return labels[node] ?? { label: humanizeNode(node) };
}

function humanizeNode(node: string): string {
  return node
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function sourceDetail(source: SourceAnchor): string {
  const page = source.page_start ?? source.page ?? source.page_end;
  return page ? `${source.doc_title} · page ${page}` : source.doc_title;
}

function warningDetail(event: Extract<RagSseEvent, { event: "warning" }>): string {
  if (event.data.message) return event.data.message;
  if (event.data.code === "verifier_retry") return `Evidence check requested another search${event.data.retry_count ? ` (${event.data.retry_count})` : ""}`;
  if (event.data.code === "low_faithfulness") return "Some answer claims may need closer review";
  if (event.data.code === "conflicting_sources") return "Retrieved sources disagree";
  if (event.data.code === "artifact_generation_failed") return "The answer was generated, but file creation failed";
  if (event.data.code === "artifact_generation_partial") return "Some requested files could not be created";
  return humanizeNode(event.data.code);
}

function compactText(value: string): string {
  return value.length > 96 ? `${value.slice(0, 93).trimEnd()}...` : value;
}

function appendText(current: string | undefined, next: string): string {
  return current ? `${current}${next}` : next;
}

function defaultSpacePath(user: User | null): string | null {
  if (user && isGlobalAdmin(user)) return null;
  return user?.group_paths[0] ?? null;
}
