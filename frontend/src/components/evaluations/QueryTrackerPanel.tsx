import { type ChangeEvent, type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, CheckCircle2, Clock3, Database, FileText, Info, Layers3, Loader2, Play, Search, ShieldCheck, Square, XCircle, type LucideIcon } from "lucide-react";

import { queryApi } from "../../api/contracts";
import { isGlobalAdmin } from "../../authz";
import { EmptyPanel, InlineMessage, Skeleton } from "../layout/Common";
import type { Document, QuerySource, QuerySourceMode, User as AuthUser } from "../../types/api";
import { errorMessage, formatIntent } from "../../utils/format";
import { isDocumentInSpace, userSpacesFromPaths } from "../../utils/groups";
import {
  createQueryTrackerState,
  formatDurationMs,
  markQueryTrackerCancelled,
  reduceQueryTrackerEvent,
  slowestNodeTimings,
  sourceDetail,
  type QueryTrackerState,
  type QueryTrackerTimelineItem,
} from "./queryTrackerState";

const SOURCE_MODES: Array<{ mode: QuerySourceMode; label: string; icon: LucideIcon }> = [
  { mode: "auto", label: "Auto", icon: Search },
  { mode: "corpus_only", label: "Documents", icon: FileText },
  { mode: "db_only", label: "Live DB", icon: Database },
  { mode: "hybrid", label: "Hybrid", icon: Layers3 },
];

export function QueryTrackerPanel({
  activeSpacePath,
  currentDocuments,
  documents,
  documentsLoading,
  onActiveSpaceChange,
  user,
}: QueryTrackerPanelProps) {
  const abortControllerRef = useRef<AbortController | null>(null);
  const cancelledRef = useRef(false);
  const [allowSourceExpansion, setAllowSourceExpansion] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [selectedQuerySourceId, setSelectedQuerySourceId] = useState("");
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
  const slowTimings = slowestNodeTimings(finalResponse);
  const runtime = trackerRuntime(trackerState);

  useEffect(() => {
    if (sourceMode === "db_only") setSelectedDocumentIds([]);
    if (sourceMode === "db_only" || sourceMode === "corpus_only") setAllowSourceExpansion(false);
  }, [sourceMode]);

  useEffect(() => {
    setSelectedDocumentIds((current) => current.filter((documentId) => scopedDocumentIdSet.has(documentId)));
  }, [scopedDocumentIdSet]);

  useEffect(() => {
    if (selectedQuerySourceId && !querySources.some((source) => source.id === selectedQuerySourceId)) {
      setSelectedQuerySourceId("");
    }
  }, [querySources, selectedQuerySourceId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuery = query.trim();
    if (!trimmedQuery || !canSubmit) return;

    const controller = new AbortController();
    abortControllerRef.current = controller;
    cancelledRef.current = false;
    setIsRunning(true);
    setTrackerState(createQueryTrackerState(new Date().toISOString()));

    try {
      for await (const streamEvent of queryApi.stream({
        query: trimmedQuery,
        session_id: null,
        client_request_id: createClientRequestId(),
        group_path: activeSpacePath,
        document_ids: sourceMode === "db_only" || selectedDocumentIds.length === 0 ? undefined : selectedDocumentIds,
        source_mode: sourceMode,
        query_source_id: dbMode ? selectedQuerySourceId || null : null,
        allow_source_expansion: allowSourceExpansion,
      }, { signal: controller.signal })) {
        setTrackerState((current) => reduceQueryTrackerEvent(current, streamEvent));
      }
    } catch (error) {
      if (isAbortError(error)) {
        if (!cancelledRef.current) {
          setTrackerState((current) => markQueryTrackerCancelled(current));
        }
        return;
      }
      setTrackerState((current) => reduceQueryTrackerEvent(current, { event: "error", data: { code: "request_failed", message: errorMessage(error, "The tracker query failed.") } }));
    } finally {
      abortControllerRef.current = null;
      setIsRunning(false);
    }
  }

  function handleCancel() {
    cancelledRef.current = true;
    abortControllerRef.current?.abort();
    setTrackerState((current) => markQueryTrackerCancelled(current));
    setIsRunning(false);
  }

  function handleDocumentSelection(event: ChangeEvent<HTMLSelectElement>) {
    setSelectedDocumentIds(Array.from(event.currentTarget.selectedOptions, (option) => option.value));
  }

  return (
    <div className="rag-eval-screen rag-eval-tracker-screen">
      <section className="sv-panel rag-eval-tracker-console">
        <div className="rag-eval-section-header">
          <div>
            <h2 className="sv-section-title">Query Tracker</h2>
            <p>Run one live query and inspect the graph, evidence, answer, and timings.</p>
          </div>
          <span className={isRunning ? "rag-eval-tracker-live active" : "rag-eval-tracker-live"}>
            {isRunning ? <Loader2 className="animate-spin" size={14} /> : <Activity size={14} />}
            {isRunning ? "Streaming" : "Ready"}
          </span>
        </div>
        <form className="rag-eval-tracker-form" onSubmit={handleSubmit}>
          <div className="rag-eval-tracker-notice">
            <ShieldCheck size={16} />
            <span>Tracker queries run against the live system and are saved like normal chat queries.</span>
          </div>
          <label className="sv-field">
            <span className="sv-label">Query</span>
            <textarea
              className="sv-textarea rag-eval-tracker-query"
              disabled={isRunning}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Ask the system a question to trace..."
              rows={4}
              value={query}
            />
          </label>
          <div className="rag-eval-tracker-controls">
            <label className="sv-field">
              <span className="sv-label">Knowledge Space</span>
              <select
                className="sv-input"
                disabled={isRunning}
                onChange={(event) => onActiveSpaceChange(event.target.value || null)}
                value={activeSpacePath ?? ""}
              >
                {isGlobalAdmin(user) ? <option value="">All visible spaces</option> : null}
                {spaceOptions.map((space) => (
                  <option key={space.path} value={space.path}>
                    {space.name} ({space.documentCount})
                  </option>
                ))}
              </select>
            </label>
            <div className="sv-field">
              <span className="sv-label">Source mode</span>
              <div className="rag-eval-tracker-source-segments" aria-label="Query source mode">
                {SOURCE_MODES.map(({ mode, label, icon: Icon }) => (
                  <button
                    key={mode}
                    type="button"
                    aria-pressed={sourceMode === mode}
                    className={sourceMode === mode ? "active" : ""}
                    disabled={isRunning}
                    onClick={() => setSourceMode(mode)}
                  >
                    <Icon size={14} />
                    <span>{label}</span>
                  </button>
                ))}
              </div>
            </div>
            <label className="sv-field">
              <span className="sv-label">DB source</span>
              <select
                className="sv-input"
                disabled={isRunning || !dbMode || querySourcesQuery.isLoading || querySources.length === 0}
                onChange={(event) => setSelectedQuerySourceId(event.target.value)}
                value={selectedQuerySourceId}
              >
                <option value="">{querySourcesQuery.isLoading ? "Loading sources" : querySources.length ? "All visible DB sources" : "No DB sources"}</option>
                {querySources.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="sv-field">
              <span className="sv-label">Document scope</span>
              {documentsLoading ? (
                <Skeleton className="h-28 w-full" />
              ) : (
                <select
                  className="sv-input rag-eval-tracker-document-select"
                  disabled={isRunning || sourceMode === "db_only" || scopedDocuments.length === 0}
                  multiple
                  onChange={handleDocumentSelection}
                  size={Math.min(6, Math.max(3, scopedDocuments.length))}
                  value={selectedDocumentIds}
                >
                  {scopedDocuments.map((document) => (
                    <option key={document.id} value={document.id}>
                      {document.title}
                    </option>
                  ))}
                </select>
              )}
            </label>
            <label className="rag-eval-tracker-toggle">
              <input
                checked={allowSourceExpansion}
                disabled={isRunning || sourceMode === "corpus_only" || sourceMode === "db_only"}
                onChange={(event) => setAllowSourceExpansion(event.target.checked)}
                type="checkbox"
              />
              <span>
                <strong>Allow source expansion</strong>
                <small>Let the router expand beyond the selected mode when needed.</small>
              </span>
            </label>
          </div>
          {selectedDocuments.length > 0 ? (
            <div className="rag-eval-tracker-scope" aria-label="Selected document scope">
              <span>Scoped documents</span>
              {selectedDocuments.map((document) => (
                <button
                  key={document.id}
                  type="button"
                  disabled={isRunning}
                  onClick={() => setSelectedDocumentIds((current) => current.filter((documentId) => documentId !== document.id))}
                >
                  <FileText size={13} />
                  {document.title}
                  <XCircle size={13} />
                </button>
              ))}
            </div>
          ) : null}
          {submitHint ? <InlineMessage tone="warning">{submitHint}</InlineMessage> : null}
          {querySourcesQuery.isError ? <InlineMessage tone="warning">{errorMessage(querySourcesQuery.error, "Unable to load DB query sources.")}</InlineMessage> : null}
          <div className="rag-eval-tracker-actions">
            <button type="submit" className="sv-action-primary" disabled={!canSubmit}>
              {isRunning ? <Loader2 className="animate-spin" size={16} /> : <Play size={16} />}
              {isRunning ? "Streaming" : "Run query"}
            </button>
            {isRunning ? (
              <button type="button" className="sv-action-danger" onClick={handleCancel}>
                <Square fill="currentColor" size={14} />
                Stop
              </button>
            ) : null}
          </div>
        </form>
      </section>

      <section className="sv-panel rag-eval-tracker-status">
        <TrackerFact icon={ShieldCheck} label="Trace" value={trackerState.traceId ?? "Not started"} />
        <TrackerFact icon={Activity} label="Session" value={trackerState.sessionId ?? "Created on completion"} />
        <TrackerFact icon={Info} label="Intent" value={trackerState.intent ? formatIntent(trackerState.intent) : "Pending"} />
        <TrackerFact icon={Clock3} label="Runtime" value={runtime} />
      </section>

      <div className="rag-eval-tracker-grid">
        <section className="sv-panel rag-eval-tracker-timeline-panel">
          <div className="rag-eval-section-header">
            <div>
              <h2 className="sv-section-title">System Trace</h2>
              <p>{trackerState.timeline.length ? `${trackerState.timeline.length} streamed events` : "Graph activity will appear here."}</p>
            </div>
          </div>
          {trackerState.timeline.length === 0 ? (
            <div className="p-5"><EmptyPanel>Run a tracker query to see retrieval, ranking, synthesis, and verification steps.</EmptyPanel></div>
          ) : (
            <div className="rag-eval-tracker-timeline" role="list">
              {trackerState.timeline.map((item) => <TimelineRow key={item.id} item={item} />)}
            </div>
          )}
        </section>

        <section className="sv-panel rag-eval-tracker-answer-panel">
          <div className="rag-eval-section-header">
            <div>
              <h2 className="sv-section-title">Answer Stream</h2>
              <p>{finalResponse ? finalResponse.faithfulness_status : "Tokens and final response."}</p>
            </div>
            {finalResponse ? <span className="sv-pill">{Math.round(finalResponse.faithfulness_score * 100)}% grounded</span> : null}
          </div>
          <div className="rag-eval-tracker-answer-body">
            {trackerState.errorMessage ? <InlineMessage tone="error">{trackerState.errorMessage}</InlineMessage> : null}
            {trackerState.warnings.length > 0 ? (
              <div className="rag-eval-tracker-warning-list">
                {trackerState.warnings.map((warning, index) => (
                  <span key={`${warning}-${index}`}><AlertTriangle size={14} /> {warning}</span>
                ))}
              </div>
            ) : null}
            {trackerState.answerText ? (
              <p className="rag-eval-answer rag-eval-tracker-answer">{trackerState.answerText}</p>
            ) : (
              <EmptyPanel>Answer tokens will stream here while the graph runs.</EmptyPanel>
            )}
          </div>
        </section>
      </div>

      <div className="rag-eval-tracker-detail-grid">
        <section className="sv-panel rag-eval-tracker-sources-panel">
          <div className="rag-eval-section-header">
            <div>
              <h2 className="sv-section-title">Sources</h2>
              <p>{trackerState.sources.length ? `${trackerState.sources.length} returned` : "Retrieved evidence anchors."}</p>
            </div>
          </div>
          {trackerState.sources.length === 0 ? (
            <div className="p-5"><EmptyPanel>No sources have been streamed yet.</EmptyPanel></div>
          ) : (
            <div className="rag-eval-tracker-source-list">
              {trackerState.sources.map((source, index) => (
                <article key={`${source.doc_id}-${source.chunk_id}-${index}`}>
                  <strong>{sourceDetail(source)}</strong>
                  <small>{source.group_path} / {source.clearance_level}</small>
                  <p>{source.excerpt}</p>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="sv-panel rag-eval-tracker-timings-panel">
          <div className="rag-eval-section-header">
            <div>
              <h2 className="sv-section-title">Node Timings</h2>
              <p>{slowTimings.length ? "Slowest completed graph steps." : "Available when the response completes."}</p>
            </div>
          </div>
          {slowTimings.length === 0 ? (
            <div className="p-5"><EmptyPanel>Node timings arrive with the final response.</EmptyPanel></div>
          ) : (
            <div className="rag-eval-tracker-timing-list">
              {slowTimings.map((timing) => (
                <div key={`${timing.node}-${timing.duration_ms}`}>
                  <span>{formatDurationMs(timing.duration_ms)}</span>
                  <strong>{timing.node}</strong>
                  <small>{timing.execution_mode ?? "mode unavailable"}{timing.detail ? ` / ${timing.detail}` : ""}</small>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function TimelineRow({ item }: { item: QueryTrackerTimelineItem }) {
  const Icon = item.status === "error" ? XCircle : item.status === "warning" ? AlertTriangle : item.status === "running" ? Loader2 : CheckCircle2;
  return (
    <div className="rag-eval-tracker-timeline-row" data-status={item.status} role="listitem">
      <span className="rag-eval-tracker-timeline-icon">
        <Icon className={item.status === "running" ? "animate-spin" : ""} size={15} />
      </span>
      <div>
        <strong>{item.label}</strong>
        {item.detail ? <small>{item.detail}</small> : null}
      </div>
      <span className="rag-eval-tracker-timeline-meta">{formatDurationMs(item.durationMs)}</span>
    </div>
  );
}

function TrackerFact({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="rag-eval-tracker-fact">
      <Icon size={15} />
      <span>
        <small>{label}</small>
        <strong>{value}</strong>
      </span>
    </div>
  );
}

function knowledgeSpaceOptions(user: AuthUser, documents: Document[]) {
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

interface QueryTrackerPanelProps {
  activeSpacePath: string | null;
  currentDocuments: Document[];
  documents: Document[];
  documentsLoading: boolean;
  onActiveSpaceChange: (path: string | null) => void;
  user: AuthUser;
}
