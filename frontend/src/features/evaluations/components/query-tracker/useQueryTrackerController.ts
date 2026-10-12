import { type FormEventHandler, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { queryApi, ragEvaluationsApi } from "@/lib/api/contracts";
import { isGlobalAdmin } from "@/lib/auth/authz";
import { errorMessage } from "@/lib/utils/format";
import { isDocumentInSpace, userSpacesFromPaths } from "@/lib/utils/groups";
import type { Document, QueryRequest, QuerySource, QuerySourceMode, RAGResponse, User as AuthUser } from "@/types/api";
import type { QueryNodeTiming } from "@/types/query";
import {
  createQueryTrackerState,
  formatDurationMs,
  markQueryTrackerCancelled,
  reduceQueryTrackerEvent,
  slowestNodeTimings,
  type QueryTrackerState,
} from "../queryTrackerState";

export interface QueryTrackerControllerInput {
  activeSpacePath: string | null;
  currentDocuments: Document[];
  documents: Document[];
  documentsLoading: boolean;
  onActiveSpaceChange: (path: string | null) => void;
  user: AuthUser;
}

export interface QueryTrackerController {
  controls: QueryTrackerControlsViewModel;
  results: QueryTrackerResultsViewModel;
}

export interface QueryTrackerControlsViewModel {
  canSubmit: boolean;
  documents: {
    disabled: boolean;
    isLoading: boolean;
    onChange: (documentIds: string[]) => void;
    onRemove: (documentId: string) => void;
    scoped: Document[];
    selected: Document[];
    selectedIds: string[];
  };
  expansion: {
    checked: boolean;
    disabled: boolean;
    onChange: (checked: boolean) => void;
  };
  isRunning: boolean;
  onCancel: () => void;
  onSubmit: FormEventHandler<HTMLFormElement>;
  query: {
    disabled: boolean;
    onChange: (query: string) => void;
    value: string;
  };
  sources: {
    dbSelectDisabled: boolean;
    errorMessage: string | null;
    items: QuerySource[];
    mode: QuerySourceMode;
    onModeChange: (mode: QuerySourceMode) => void;
    onQuerySourcesChange: (sourceIds: string[]) => void;
    selectedQuerySourceIds: string[];
    sourcesLoading: boolean;
  };
  spaces: {
    activePath: string | null;
    disabled: boolean;
    onChange: (path: string | null) => void;
    options: QueryTrackerSpaceOption[];
    showAllVisible: boolean;
  };
  submitHint: string | null;
}

export interface QueryTrackerResultsViewModel {
  finalResponse: RAGResponse | null;
  onChooseQuerySource: (sourceId: string) => void;
  onExpandSourceSearch: () => void;
  runtime: string;
  slowTimings: QueryNodeTiming[];
  state: QueryTrackerState;
}

interface QueryTrackerSpaceOption {
  documentCount: number;
  name: string;
  path: string;
}

export function useQueryTrackerController({
  activeSpacePath,
  currentDocuments,
  documents,
  documentsLoading,
  onActiveSpaceChange,
  user,
}: QueryTrackerControllerInput): QueryTrackerController {
  const abortControllerRef = useRef<AbortController | null>(null);
  const cancelledRef = useRef(false);
  const [allowSourceExpansion, setAllowSourceExpansion] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [selectedQuerySourceIds, setSelectedQuerySourceIds] = useState<string[]>([]);
  const [sourceMode, setSourceMode] = useState<QuerySourceMode>("auto");
  const [trackerState, setTrackerState] = useState<QueryTrackerState>(() => createQueryTrackerState());

  const querySourcesQuery = useQuery({
    queryKey: ["query-sources", "evaluation-tracker", activeSpacePath ?? "all"],
    queryFn: () => queryApi.sources({ group_path: activeSpacePath }),
    retry: false,
    staleTime: 15000,
  });
  const querySources = querySourcesQuery.data?.items ?? [];
  const dbMode = sourceMode === "db_only" || sourceMode === "hybrid";
  const scopedDocuments = useMemo(
    () => currentDocuments.filter((document) => !activeSpacePath || isDocumentInSpace(document.group_path, activeSpacePath)),
    [activeSpacePath, currentDocuments],
  );
  const scopedDocumentIdSet = useMemo(() => new Set(scopedDocuments.map((document) => document.id)), [scopedDocuments]);
  const selectedDocuments = useMemo(
    () => scopedDocuments.filter((document) => selectedDocumentIds.includes(document.id)),
    [scopedDocuments, selectedDocumentIds],
  );
  const spaceOptions = useMemo(() => knowledgeSpaceOptions(user, documents), [documents, user]);
  const hasCorpus = scopedDocuments.length > 0;
  const hasQueryableSource = hasCorpus || querySources.length > 0;
  const canSubmit = query.trim().length > 0
    && !isRunning
    && (
      sourceMode === "db_only"
        ? querySources.length > 0
        : sourceMode === "corpus_only"
          ? hasCorpus
          : hasQueryableSource
    );
  const submitHint = submitBlocker(sourceMode, querySources, hasCorpus, query.trim().length > 0, isRunning);
  const finalResponse = trackerState.verifiedResponse ?? trackerState.finalResponse;

  useEffect(() => {
    if (sourceMode === "db_only") setSelectedDocumentIds([]);
    if (sourceMode === "db_only" || sourceMode === "corpus_only") setAllowSourceExpansion(false);
  }, [sourceMode]);

  useEffect(() => {
    setSelectedDocumentIds((current) => current.filter((documentId) => scopedDocumentIdSet.has(documentId)));
  }, [scopedDocumentIdSet]);

  useEffect(() => {
    setSelectedQuerySourceIds((current) => current.filter((sourceId) => querySources.some((source) => source.id === sourceId)));
  }, [querySources]);

  const handleSubmit: FormEventHandler<HTMLFormElement> = async (event) => {
    event.preventDefault();
    const trimmedQuery = query.trim();
    if (!trimmedQuery || !canSubmit) return;

    void streamTrackerQuery({
      query: trimmedQuery,
      session_id: null,
      client_request_id: createClientRequestId(),
      group_path: activeSpacePath,
      document_ids: sourceMode === "db_only" || selectedDocumentIds.length === 0 ? undefined : selectedDocumentIds,
      source_mode: sourceMode,
      query_source_ids: dbMode && selectedQuerySourceIds.length ? selectedQuerySourceIds : undefined,
      allow_source_expansion: allowSourceExpansion,
    });
  };

  function handleCancel() {
    cancelledRef.current = true;
    abortControllerRef.current?.abort();
    setTrackerState((current) => markQueryTrackerCancelled(current));
    setIsRunning(false);
  }

  async function streamTrackerQuery(request: QueryRequest) {
    const controller = new AbortController();
    abortControllerRef.current = controller;
    cancelledRef.current = false;
    setIsRunning(true);
    setTrackerState(createQueryTrackerState(new Date().toISOString(), request.client_request_id ?? null, request.query));

    try {
      for await (const streamEvent of ragEvaluationsApi.streamQueryTracker(request, { signal: controller.signal })) {
        setTrackerState((current) => reduceQueryTrackerEvent(current, streamEvent));
      }
    } catch (error) {
      if (isAbortError(error)) {
        if (!cancelledRef.current) setTrackerState((current) => markQueryTrackerCancelled(current));
        return;
      }
      setTrackerState((current) => reduceQueryTrackerEvent(current, {
        event: "error",
        data: { code: "request_failed", message: errorMessage(error, "The tracker query failed.") },
      }));
    } finally {
      abortControllerRef.current = null;
      setIsRunning(false);
    }
  }

  function chooseQuerySource(sourceId: string) {
    const response = trackerState.verifiedResponse ?? trackerState.finalResponse;
    if (!response?.source_clarification || !trackerState.sessionId || !trackerState.clientRequestId || isRunning) return;
    if (!response.source_clarification.options.some((option) => option.source_id === sourceId)) return;
    const nextMode = response.source_mode === "hybrid" ? "hybrid" : "db_only";
    void streamTrackerQuery({
      query: trackerState.queryText,
      session_id: trackerState.sessionId,
      client_request_id: trackerState.clientRequestId,
      group_path: activeSpacePath,
      document_ids: nextMode === "hybrid" && selectedDocumentIds.length ? selectedDocumentIds : undefined,
      source_mode: nextMode,
      query_source_id: sourceId,
      continue_source_clarification: true,
    });
  }

  function expandSourceSearch() {
    const response = trackerState.verifiedResponse ?? trackerState.finalResponse;
    if (!response?.source_expansion?.available || isRunning || !trackerState.queryText) return;
    void streamTrackerQuery({
      query: trackerState.queryText,
      session_id: null,
      client_request_id: createClientRequestId(),
      group_path: activeSpacePath,
      document_ids: selectedDocumentIds.length ? selectedDocumentIds : undefined,
      source_mode: "hybrid",
      allow_source_expansion: true,
    });
  }

  return {
    controls: {
      canSubmit,
      documents: {
        disabled: isRunning || sourceMode === "db_only" || scopedDocuments.length === 0,
        isLoading: documentsLoading,
        onChange: setSelectedDocumentIds,
        onRemove: (documentId) => setSelectedDocumentIds((current) => current.filter((currentId) => currentId !== documentId)),
        scoped: scopedDocuments,
        selected: selectedDocuments,
        selectedIds: selectedDocumentIds,
      },
      expansion: {
        checked: allowSourceExpansion,
        disabled: isRunning || sourceMode === "corpus_only" || sourceMode === "db_only",
        onChange: setAllowSourceExpansion,
      },
      isRunning,
      onCancel: handleCancel,
      onSubmit: handleSubmit,
      query: { disabled: isRunning, onChange: setQuery, value: query },
      sources: {
        dbSelectDisabled: isRunning || !dbMode || querySourcesQuery.isLoading || querySources.length === 0,
        errorMessage: querySourcesQuery.isError ? errorMessage(querySourcesQuery.error, "Unable to load DB query sources.") : null,
        items: querySources,
        mode: sourceMode,
        onModeChange: setSourceMode,
        onQuerySourcesChange: (sourceIds) => setSelectedQuerySourceIds(sourceIds.slice(0, 3)),
        selectedQuerySourceIds,
        sourcesLoading: querySourcesQuery.isLoading,
      },
      spaces: {
        activePath: activeSpacePath,
        disabled: isRunning,
        onChange: onActiveSpaceChange,
        options: spaceOptions,
        showAllVisible: isGlobalAdmin(user),
      },
      submitHint,
    },
    results: {
      finalResponse,
      onChooseQuerySource: chooseQuerySource,
      onExpandSourceSearch: expandSourceSearch,
      runtime: trackerRuntime(trackerState),
      slowTimings: slowestNodeTimings(finalResponse),
      state: trackerState,
    },
  };
}

function knowledgeSpaceOptions(user: AuthUser, documents: Document[]): QueryTrackerSpaceOption[] {
  const paths = isGlobalAdmin(user)
    ? Array.from(new Set([...user.group_paths, ...documents.map((document) => document.group_path)].filter(Boolean))).sort()
    : user.group_paths;
  return userSpacesFromPaths(paths).map((space) => ({
    ...space,
    documentCount: documents.filter((document) => isDocumentInSpace(document.group_path, space.path)).length,
  }));
}

function submitBlocker(sourceMode: QuerySourceMode, querySources: QuerySource[], hasCorpus: boolean, hasQuery: boolean, isRunning: boolean): string | null {
  if (!hasQuery || isRunning) return null;
  if (sourceMode === "db_only" && querySources.length === 0) return "Live DB mode needs at least one visible database source.";
  if (sourceMode === "corpus_only" && !hasCorpus) return "Document mode needs at least one current document in scope.";
  if (!hasCorpus && querySources.length === 0) return "No document or DB source is available in this scope.";
  return null;
}

function trackerRuntime(state: QueryTrackerState): string {
  if (state.finalResponse?.latency_ms) return formatDurationMs(state.finalResponse.latency_ms);
  if (!state.startedAt) return "Not started";
  if (!state.completedAt) return "Running";
  const elapsed = Date.parse(state.completedAt) - Date.parse(state.startedAt);
  return elapsed > 0 ? formatDurationMs(elapsed) : "Complete";
}

function createClientRequestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `tracker-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function isAbortError(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "name" in error && (error as { name?: string }).name === "AbortError");
}
