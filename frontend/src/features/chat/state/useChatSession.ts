import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { queryApi } from "@/lib/api/contracts";
import { isGlobalAdmin } from "@/lib/auth/authz";
import type { QuerySourceMode, RAGResponse, SourceAnchor, User } from "@/types/api";
import type { QueryRunVariables, SavedChatSession, SavedChatSessionSummary } from "@/types/chat";
import { errorMessage } from "@/lib/utils/format";
import { createId } from "@/lib/utils/ids";
import { readStoredString, writeStoredString } from "@/lib/utils/uiPreferences";
import {
  compactSessionTitle,
  createUserTurn,
  mergeSavedSessionsWithLocal,
  questionCountForTurns,
  removeCachedSession,
  removeSessionFromPages,
  updateChatSessionTurns,
  upsertLocalSessionSummary,
  type ChatHistoryQueryData,
  type ChatSessionTurnCache,
} from "@/features/chat/state/chatSessionCache";
import { applyStreamEvent } from "@/features/chat/state/chatStreamReducer";
import {
  activeArtifactJobs,
  createAssistantTurn,
  initialProgressForQuestion,
  isAbortError,
  latestCompleteResponse,
  markAssistantTurnCancelled,
  markAssistantTurnErrored,
  mergeArtifactJobIntoTurns,
  replaceAssistantTurn,
  type SourceSubmitOverride,
} from "@/features/chat/state/chatTurnState";
import { runStreamingQuery } from "@/features/chat/state/chatStreaming";


export { applyStreamEvent };

export { mergeSavedSessionsWithLocal, updateChatSessionTurns };
export type { ChatSessionTurnCache };


const CHAT_HISTORY_PAGE_SIZE = 30;
const CHAT_SOURCE_MODE_STORAGE_KEY = "Prudentia-chat-source-mode";
const QUERY_SOURCE_MODES: QuerySourceMode[] = ["auto", "corpus_only", "db_only", "hybrid"];
export type ActiveGeneration = { assistantTurnId: string; sessionId: string };

export function useChatSession(currentUser: User | null, historyEnabled = true) {
  const queryClient = useQueryClient();
  const activeAbortControllerRef = useRef<AbortController | null>(null);
  const activeGenerationRef = useRef<ActiveGeneration | null>(null);
  const cancelledAssistantTurnIdsRef = useRef<Set<string>>(new Set());
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [activeGeneration, setActiveGenerationState] = useState<ActiveGeneration | null>(null);
  const [question, setQuestion] = useState("");
  const [sessionTurnsById, setSessionTurnsById] = useState<ChatSessionTurnCache>({});
  const [localSessionSummaries, setLocalSessionSummaries] = useState<SavedChatSessionSummary[]>([]);
  const [scopedDocumentIds, setScopedDocumentIds] = useState<string[]>([]);
  const [selectedSource, setSelectedSource] = useState<SourceAnchor | null>(null);
  const [sourceMode, setSourceModeState] = useState<QuerySourceMode>(readStoredSourceMode);
  const [selectedQuerySourceId, setSelectedQuerySourceIdState] = useState("");
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
    enabled: Boolean(currentUser) && historyEnabled,
  });
  const serverSavedSessions = useMemo(
    () => savedSessionsQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [savedSessionsQuery.data],
  );
  const savedSessions = useMemo(
    () => mergeSavedSessionsWithLocal(serverSavedSessions, localSessionSummaries, activeGeneration?.sessionId ?? null),
    [activeGeneration?.sessionId, localSessionSummaries, serverSavedSessions],
  );
  const savedSessionIds = useMemo(() => new Set(serverSavedSessions.map((session) => session.id)), [serverSavedSessions]);
  const savedSessionsTotal = (savedSessionsQuery.data?.pages[0]?.total ?? serverSavedSessions.length)
    + localSessionSummaries.filter((session) => !savedSessionIds.has(session.id)).length;

  const queryMutation = useMutation<RAGResponse, Error, QueryRunVariables>({
    mutationFn: (variables) =>
      runStreamingQuery(variables, (event) => {
        setSessionTurnsById((cache) =>
          updateChatSessionTurns(cache, variables.sessionId, (turns) => applyStreamEvent(turns, variables.assistantTurnId, event)),
        );
      }),
    onSuccess: (result, variables) => {
      if (cancelledAssistantTurnIdsRef.current.has(variables.assistantTurnId)) {
        return;
      }
      setSessionTurnsById((cache) =>
        updateChatSessionTurns(cache, variables.sessionId, (turns) => replaceAssistantTurn(turns, variables.assistantTurnId, result)),
      );
      void queryClient.invalidateQueries({ queryKey: chatHistoryQueryKey });
    },
    onError: (error, variables) => {
      if (cancelledAssistantTurnIdsRef.current.has(variables.assistantTurnId) || isAbortError(error)) {
        setSessionTurnsById((cache) =>
          updateChatSessionTurns(cache, variables.sessionId, (turns) => markAssistantTurnCancelled(turns, variables.assistantTurnId)),
        );
        return;
      }
      setSessionTurnsById((cache) =>
        updateChatSessionTurns(cache, variables.sessionId, (turns) => markAssistantTurnErrored(turns, variables.assistantTurnId, errorMessage(error, "The query request failed."))),
      );
    },
    onSettled: (_result, _error, variables) => {
      if (activeGenerationRef.current?.assistantTurnId === variables.assistantTurnId) {
        updateActiveGeneration(null);
        activeAbortControllerRef.current = null;
      }
      cancelledAssistantTurnIdsRef.current.delete(variables.assistantTurnId);
    },
  });

  const loadSessionMutation = useMutation<SavedChatSession, Error, string>({
    mutationFn: queryApi.getSession,
    onSuccess: (session) => {
      setActiveSessionId(session.id);
      setSessionTurnsById((cache) => ({ ...cache, [session.id]: session.turns }));
      setScopedDocumentIds([]);
      setSelectedSource(null);
      setSelectedQuerySourceIdState("");
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

  const chatTurns = activeSessionId ? sessionTurnsById[activeSessionId] ?? [] : [];
  const latestResponse = useMemo(() => latestCompleteResponse(chatTurns), [chatTurns]);
  const activeSessionHasPendingTurn = chatTurns.some((turn) => turn.role === "assistant" && turn.status === "pending");
  const hasPendingGeneration = Boolean(activeGeneration);
  const activeArtifactJobIds = useMemo(() => activeArtifactJobs(chatTurns), [chatTurns]);
  const activeArtifactJobKey = activeArtifactJobIds.join("|");

  useEffect(() => {
    abortActiveQuery();
    loadSessionMutation.reset();
    setActiveSessionId(null);
    setSessionTurnsById({});
    setLocalSessionSummaries([]);
    setScopedDocumentIds([]);
    setSelectedSource(null);
    setSelectedQuerySourceIdState("");
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
      if (!activeSessionId) return;
      setSessionTurnsById((cache) =>
        updateChatSessionTurns(cache, activeSessionId, (turns) =>
          results.reduce(
            (nextTurns, result) => (result.status === "fulfilled" ? mergeArtifactJobIntoTurns(nextTurns, result.value) : nextTurns),
            turns,
          ),
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
  }, [activeArtifactJobKey, activeSessionId, currentUser?.permission_version, currentUser?.user_id]);

  function resetChat() {
    loadSessionMutation.reset();
    setActiveSessionId(null);
    setScopedDocumentIds([]);
    setSelectedSource(null);
    setSelectedQuerySourceIdState("");
    setQuestion("");
  }

  function handleQuestionSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submitQuestion(question);
  }

  function submitQuestion(rawQuestion: string, override: SourceSubmitOverride = {}) {
    const nextQuestion = rawQuestion.trim();
    if (!nextQuestion || !currentUser || activeGenerationRef.current) {
      return;
    }
    const effectiveSourceMode = override.sourceMode ?? sourceMode;
    const effectiveQuerySourceId = override.querySourceId ?? selectedQuerySourceId;
    const queryDocumentIds = override.documentIds ?? (effectiveSourceMode === "db_only" ? [] : scopedDocumentIds);
    const sessionId = activeSessionId ?? createId("session");
    setActiveSessionId(sessionId);
    const assistantTurn = createAssistantTurn(nextQuestion, queryDocumentIds, activeSpacePath, effectiveSourceMode, effectiveQuerySourceId || null);
    const createdAt = new Date().toISOString();
    const userTurn = createUserTurn(nextQuestion, createdAt);
    const existingSummary = savedSessions.find((session) => session.id === sessionId)
      ?? localSessionSummaries.find((session) => session.id === sessionId);
    const nextQuestionCount = questionCountForTurns([...(sessionTurnsById[sessionId] ?? []), userTurn]);
    setSessionTurnsById((cache) =>
      updateChatSessionTurns(cache, sessionId, (turns) => [...turns, userTurn, assistantTurn]),
    );
    setLocalSessionSummaries((summaries) =>
      upsertLocalSessionSummary(summaries, {
        id: sessionId,
        title: existingSummary?.title ?? compactSessionTitle(nextQuestion),
        createdAt: existingSummary?.createdAt ?? createdAt,
        updatedAt: createdAt,
        questionCount: Math.max(existingSummary?.questionCount ?? 0, nextQuestionCount),
      }),
    );
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
        source_mode: effectiveSourceMode,
        query_source_id: effectiveSourceMode === "db_only" || effectiveSourceMode === "hybrid" ? effectiveQuerySourceId || undefined : undefined,
        allow_source_expansion: override.allowSourceExpansion ?? false,
      },
      sessionId,
    });
  }

  function cancelPendingTurn() {
    const generation = activeGenerationRef.current;
    if (!generation || generation.sessionId !== activeSessionId) return;
    const assistantTurnId = generation.assistantTurnId;
    cancelledAssistantTurnIdsRef.current.add(assistantTurnId);
    activeAbortControllerRef.current?.abort();
    updateActiveGeneration(null);
    activeAbortControllerRef.current = null;
    setSessionTurnsById((cache) =>
      updateChatSessionTurns(cache, generation.sessionId, (turns) => markAssistantTurnCancelled(turns, assistantTurnId)),
    );
  }

  function changeActiveSpacePath(groupPath: string | null) {
    if (activeGenerationRef.current || !currentUser) return;
    if (groupPath === null) {
      if (!isGlobalAdmin(currentUser)) return;
      setActiveSpacePath(null);
      setScopedDocumentIds([]);
      setSelectedSource(null);
      setSelectedQuerySourceIdState("");
      return;
    }
    if (!isGlobalAdmin(currentUser) && !currentUser.group_paths.includes(groupPath)) return;
    setActiveSpacePath(groupPath);
    setScopedDocumentIds([]);
    setSelectedSource(null);
    setSelectedQuerySourceIdState("");
  }

  function addScopedDocument(documentId: string) {
    if (sourceMode === "db_only") {
      setSourceModeState("hybrid");
    }
    setScopedDocumentIds((current) => (current.includes(documentId) ? current : [...current, documentId]));
  }

  function removeScopedDocument(documentId: string) {
    setScopedDocumentIds((current) => current.filter((candidate) => candidate !== documentId));
  }

  function loadChatSession(sessionId: string) {
    if (loadSessionMutation.isPending) return;
    if (sessionTurnsById[sessionId]) {
      setActiveSessionId(sessionId);
      setScopedDocumentIds([]);
      setSelectedSource(null);
      setSelectedQuerySourceIdState("");
      setQuestion("");
      return;
    }
    loadSessionMutation.mutate(sessionId);
  }

  function deleteChatSession(sessionId: string) {
    if (activeGenerationRef.current?.sessionId === sessionId) return;
    deleteSessionMutation.mutate(sessionId);
    setSessionTurnsById((cache) => removeCachedSession(cache, sessionId));
    setLocalSessionSummaries((summaries) => summaries.filter((session) => session.id !== sessionId));
    if (activeSessionId === sessionId) resetChat();
  }

  function handleRetry(assistantTurnId: string) {
    const turn = chatTurns.find((candidate) => candidate.id === assistantTurnId);
    const retrySpacePath = turn?.role === "assistant" ? turn.groupPath ?? activeSpacePath : null;
    if (!turn || turn.role !== "assistant" || !currentUser || activeGenerationRef.current || !activeSessionId) {
      return;
    }
    setSessionTurnsById((cache) =>
      updateChatSessionTurns(cache, activeSessionId, (turns) =>
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
      ),
    );
    setSelectedSource(null);
    startStreamingQuery({
      assistantTurnId,
      request: {
        query: turn.question,
        session_id: activeSessionId,
        client_request_id: createId("query"),
        group_path: retrySpacePath,
        document_ids: turn.documentIds?.length ? turn.documentIds : undefined,
        source_mode: turn.sourceMode ?? "auto",
        query_source_id: turn.querySourceId || undefined,
      },
      sessionId: activeSessionId,
    });
  }

  function expandSourceSearch(assistantTurnId: string) {
    const turn = chatTurns.find((candidate) => candidate.id === assistantTurnId);
    if (!turn || turn.role !== "assistant" || !turn.response?.source_expansion?.available) return;
    submitQuestion(turn.question, {
      sourceMode: "hybrid",
      querySourceId: null,
      allowSourceExpansion: true,
      documentIds: turn.documentIds ?? [],
    });
  }

  function changeSourceMode(nextMode: QuerySourceMode) {
    setSourceModeState(nextMode);
    writeStoredString(CHAT_SOURCE_MODE_STORAGE_KEY, nextMode);
    if (nextMode === "db_only") {
      setScopedDocumentIds([]);
    }
    if (nextMode === "auto" || nextMode === "corpus_only") {
      setSelectedQuerySourceIdState("");
    }
  }

  function changeSelectedQuerySourceId(nextSourceId: string) {
    setSelectedQuerySourceIdState(nextSourceId);
  }

  async function clarifyArtifactJob(jobId: string, answers: Record<string, string>) {
    const response = await queryApi.clarifyArtifactJob(jobId, answers);
    if (!activeSessionId) return;
    setSessionTurnsById((cache) =>
      updateChatSessionTurns(cache, activeSessionId, (turns) => mergeArtifactJobIntoTurns(turns, response.job)),
    );
  }

  async function cancelArtifactJob(jobId: string) {
    const response = await queryApi.cancelArtifactJob(jobId);
    if (!activeSessionId) return;
    setSessionTurnsById((cache) =>
      updateChatSessionTurns(cache, activeSessionId, (turns) => mergeArtifactJobIntoTurns(turns, response.job)),
    );
  }

  async function retryArtifactJob(jobId: string) {
    const response = await queryApi.retryArtifactJob(jobId);
    if (!activeSessionId) return;
    setSessionTurnsById((cache) =>
      updateChatSessionTurns(cache, activeSessionId, (turns) => mergeArtifactJobIntoTurns(turns, response.job)),
    );
  }

  function startStreamingQuery(variables: Omit<QueryRunVariables, "signal">) {
    if (activeGenerationRef.current) return;
    const abortController = new AbortController();
    activeAbortControllerRef.current = abortController;
    updateActiveGeneration({ assistantTurnId: variables.assistantTurnId, sessionId: variables.sessionId });
    queryMutation.mutate({ ...variables, signal: abortController.signal });
  }

  function abortActiveQuery() {
    activeAbortControllerRef.current?.abort();
    activeAbortControllerRef.current = null;
    updateActiveGeneration(null);
  }

  function updateActiveGeneration(next: ActiveGeneration | null) {
    activeGenerationRef.current = next;
    setActiveGenerationState(next);
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
    expandSourceSearch,
    clarifyArtifactJob,
    activeSessionHasPendingTurn,
    generatingSessionId: activeGeneration?.sessionId ?? null,
    hasPendingGeneration,
    hasPendingTurn: activeSessionHasPendingTurn,
    latestResponse,
    loadChatSession,
    question,
    resetChat,
    addScopedDocument,
    removeScopedDocument,
    retryArtifactJob,
    scopedDocumentIds,
    sourceMode,
    selectedQuerySourceId,
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
    setSourceMode: changeSourceMode,
    setSelectedQuerySourceId: changeSelectedQuerySourceId,
    setQuestion,
    setSelectedSource,
  };
}

function readStoredSourceMode(): QuerySourceMode {
  return readStoredString(CHAT_SOURCE_MODE_STORAGE_KEY, { allowed: QUERY_SOURCE_MODES, fallback: "auto" });
}

function defaultSpacePath(user: User | null): string | null {
  if (user && isGlobalAdmin(user)) return null;
  return user?.group_paths[0] ?? null;
}
