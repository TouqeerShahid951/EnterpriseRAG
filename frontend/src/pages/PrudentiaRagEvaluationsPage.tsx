import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileJson, Info, Loader2, Play, RotateCcw, StopCircle, XCircle } from "lucide-react";

import { ragEvaluationsApi, type EvaluationDatasetImportRequest, type EvaluationRunCreateRequest } from "../api/contracts";
import { useToast } from "../components/feedback/ToastProvider";
import { QueryTrackerPanel } from "../components/evaluations/QueryTrackerPanel";
import { RagEvaluationDiagnostics } from "../components/evaluations/RagEvaluationDiagnostics";
import { EmptyPanel, InlineMessage, Skeleton } from "../components/layout/Common";
import { PrudentiaWorkspace } from "../components/layout/PrudentiaWorkspace";
import type { RouteId } from "../routes";
import type {
  Document,
  EvaluationCaseResult,
  EvaluationDatasetSummary,
  EvaluationFailureStage,
  EvaluationRunDetail,
  EvaluationRunStatus,
  EvaluationRunSummary,
  User as AuthUser,
} from "../types/api";
import { errorMessage, formatDateTime } from "../utils/format";

export function PrudentiaRagEvaluationsPage({ activeSpacePath, currentDocuments, documents, documentsLoading, onActiveSpaceChange, onLogout, onNavigate, user }: Props) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [activeScreen, setActiveScreen] = useState<RagEvalScreen>("overview");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const datasetsQuery = useQuery({ queryKey: ["rag-evaluations", "datasets"], queryFn: ragEvaluationsApi.listDatasets, retry: false });
  const runsQuery = useQuery({ queryKey: ["rag-evaluations", "runs"], queryFn: ragEvaluationsApi.listRuns, refetchInterval: 5000, retry: false });
  const datasets = datasetsQuery.data?.items ?? [];
  const runs = runsQuery.data?.items ?? [];
  const selectedRun = selectedRunId ? runs.find((run) => run.id === selectedRunId) ?? null : runs[0] ?? null;
  const runDetailQuery = useQuery({
    queryKey: ["rag-evaluations", "runs", selectedRun?.id],
    queryFn: () => ragEvaluationsApi.getRun(selectedRun?.id ?? ""),
    enabled: Boolean(selectedRun?.id),
    refetchInterval: selectedRun && isRunActive(selectedRun.status) ? 3000 : false,
    retry: false,
  });

  useEffect(() => {
    const firstRun = runs[0] ?? null;
    if (!selectedRunId && firstRun) setSelectedRunId(firstRun.id);
    if (selectedRunId && runsQuery.data && !runs.some((run) => run.id === selectedRunId)) {
      setSelectedRunId(firstRun?.id ?? null);
    }
  }, [runs, runsQuery.data, selectedRunId]);

  const latestDetail = runDetailQuery.data ?? null;
  const summarySource = latestDetail ?? selectedRun;
  const failureBreakdown = latestDetail?.failure_breakdown ?? failureBreakdownFromSummary(summarySource?.summary);
  const metricsLoading = runsQuery.isLoading || (Boolean(selectedRun) && runDetailQuery.isLoading);
  const selectRunForInspection = (runId: string) => {
    setSelectedRunId(runId);
    setActiveScreen("runs");
  };
  const openNewRun = () => setActiveScreen(datasets.length > 0 ? "new-run" : "datasets");
  const handleRunCreated = (runId: string) => {
    setSelectedRunId(runId);
    setActiveScreen("runs");
  };

  const cancelMutation = useMutation({
    mutationFn: ragEvaluationsApi.cancelRun,
    onSuccess: async (response) => {
      queryClient.setQueryData(["rag-evaluations", "runs", response.run.id], response.run);
      await queryClient.invalidateQueries({ queryKey: ["rag-evaluations", "runs"] });
      notify({ title: "Evaluation cancelled", description: response.run.dataset_name, tone: "warning" });
    },
    onError: (error) => notify({ title: "Cancel failed", description: errorMessage(error, "Unable to cancel evaluation."), tone: "error" }),
  });
  const retryMutation = useMutation({
    mutationFn: ragEvaluationsApi.retryRun,
    onSuccess: async (response) => {
      setSelectedRunId(response.run.id);
      await queryClient.invalidateQueries({ queryKey: ["rag-evaluations", "runs"] });
      notify({ title: "Evaluation queued", description: response.run.dataset_name, tone: "success" });
    },
    onError: (error) => notify({ title: "Retry failed", description: errorMessage(error, "Unable to retry evaluation."), tone: "error" }),
  });

  return (
    <PrudentiaWorkspace activeRoute="evaluations" onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page rag-eval-page" id="main-content">
        <div className="sv-page-inner sv-page-inner-workbench rag-eval-page-inner">
          <header className="sv-page-header rag-eval-header">
            <div>
              <p className="sv-eyebrow">Evaluate</p>
              <h1 className="sv-page-title">RAG Evaluation</h1>
              <p className="sv-page-subtitle">Manage evaluation datasets, launch scoped runs, and inspect failures from retrieval through faithfulness without crowding one screen.</p>
            </div>
            <div className="rag-eval-header-actions">
              <button type="button" className="sv-action-primary" onClick={openNewRun}>
                <Play size={16} />
                New evaluation
              </button>
              {selectedRun && isRunActive(selectedRun.status) ? (
                <button type="button" className="sv-action-danger" disabled={cancelMutation.isPending} onClick={() => cancelMutation.mutate(selectedRun.id)}>
                  {cancelMutation.isPending ? <Loader2 className="animate-spin" size={16} /> : <StopCircle size={16} />}
                  Cancel
                </button>
              ) : null}
              {selectedRun && isRunRetryable(selectedRun.status) ? (
                <button type="button" className="sv-action-secondary" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(selectedRun.id)}>
                  {retryMutation.isPending ? <Loader2 className="animate-spin" size={16} /> : <RotateCcw size={16} />}
                  Retry
                </button>
              ) : null}
            </div>
          </header>

          {datasetsQuery.isError ? <InlineMessage tone="error">{errorMessage(datasetsQuery.error, "Unable to load evaluation datasets.")}</InlineMessage> : null}
          {runsQuery.isError ? <InlineMessage tone="error">{errorMessage(runsQuery.error, "Unable to load evaluation runs.")}</InlineMessage> : null}
          {runDetailQuery.isError ? <InlineMessage tone="warning">{errorMessage(runDetailQuery.error, "Unable to load selected evaluation run.")}</InlineMessage> : null}

          <RagEvaluationScreenTabs activeScreen={activeScreen} datasetsCount={datasets.length} onChange={setActiveScreen} runsCount={runs.length} />

          {activeScreen === "overview" ? (
            <OverviewScreen
              datasetsCount={datasets.length}
              datasetsLoading={datasetsQuery.isLoading}
              failureBreakdown={failureBreakdown}
              metricsLoading={metricsLoading}
              onOpenScreen={setActiveScreen}
              onSelectRun={selectRunForInspection}
              runs={runs}
              runsLoading={runsQuery.isLoading}
              selectedRun={selectedRun}
              summarySource={summarySource}
            />
          ) : null}
          {activeScreen === "datasets" ? <DatasetsScreen datasets={datasets} loading={datasetsQuery.isLoading} onNewRun={() => setActiveScreen("new-run")} /> : null}
          {activeScreen === "new-run" ? <NewRunScreen datasets={datasets} datasetsLoading={datasetsQuery.isLoading} onRunCreated={handleRunCreated} /> : null}
          {activeScreen === "query-tracker" ? (
            <QueryTrackerPanel
              activeSpacePath={activeSpacePath}
              currentDocuments={currentDocuments}
              documents={documents}
              documentsLoading={documentsLoading}
              onActiveSpaceChange={onActiveSpaceChange}
              user={user}
            />
          ) : null}
          {activeScreen === "runs" ? (
            <RunsScreen
              detail={latestDetail}
              failureBreakdown={failureBreakdown}
              loading={Boolean(selectedRun) && runDetailQuery.isLoading}
              metricsLoading={metricsLoading}
              onSelectRun={setSelectedRunId}
              runs={runs}
              runsLoading={runsQuery.isLoading}
              selectedRun={selectedRun}
              summarySource={summarySource}
            />
          ) : null}
        </div>
      </main>
    </PrudentiaWorkspace>
  );
}

function RagEvaluationScreenTabs({ activeScreen, datasetsCount, onChange, runsCount }: { activeScreen: RagEvalScreen; datasetsCount: number; onChange: (screen: RagEvalScreen) => void; runsCount: number }) {
  const tabs: { id: RagEvalScreen; label: string; detail: string }[] = [
    { id: "overview", label: "Overview", detail: "Status" },
    { id: "datasets", label: "Datasets", detail: `${datasetsCount} available` },
    { id: "new-run", label: "New Evaluation", detail: "Scope and queue" },
    { id: "query-tracker", label: "Query Tracker", detail: "Live trace" },
    { id: "runs", label: "Runs", detail: `${runsCount} total` },
  ];
  return (
    <nav className="rag-eval-tabs" aria-label="RAG evaluation screens">
      {tabs.map((tab) => (
        <button key={tab.id} type="button" className={activeScreen === tab.id ? "rag-eval-tab active" : "rag-eval-tab"} aria-current={activeScreen === tab.id ? "page" : undefined} onClick={() => onChange(tab.id)}>
          <span>{tab.label}</span>
          <small>{tab.detail}</small>
        </button>
      ))}
    </nav>
  );
}

function OverviewScreen({ datasetsCount, datasetsLoading, failureBreakdown, metricsLoading, onOpenScreen, onSelectRun, runs, runsLoading, selectedRun, summarySource }: {
  datasetsCount: number;
  datasetsLoading: boolean;
  failureBreakdown: Record<string, number>;
  metricsLoading: boolean;
  onOpenScreen: (screen: RagEvalScreen) => void;
  onSelectRun: (runId: string) => void;
  runs: EvaluationRunSummary[];
  runsLoading: boolean;
  selectedRun: EvaluationRunSummary | null;
  summarySource: EvaluationRunSummary | EvaluationRunDetail | null | undefined;
}) {
  return (
    <div className="rag-eval-screen">
      <EvaluationMetrics run={summarySource} loading={metricsLoading} />
      <div className="rag-eval-overview-grid">
        <EvaluationWorkflowPanel datasetsCount={datasetsCount} datasetsLoading={datasetsLoading} onOpenScreen={onOpenScreen} runs={runs} />
        <RunSummaryPanel failureBreakdown={failureBreakdown} onInspect={() => onOpenScreen("runs")} selectedRun={selectedRun} />
      </div>
      <RunHistoryPanel loading={runsLoading} runs={runs} selectedRunId={selectedRun?.id ?? null} onSelect={onSelectRun} />
    </div>
  );
}

function EvaluationWorkflowPanel({ datasetsCount, datasetsLoading, onOpenScreen, runs }: { datasetsCount: number; datasetsLoading: boolean; onOpenScreen: (screen: RagEvalScreen) => void; runs: EvaluationRunSummary[] }) {
  const activeRuns = runs.filter((run) => isRunActive(run.status)).length;
  return (
    <section className="sv-panel rag-eval-workflow-panel">
      <div className="rag-eval-section-header">
        <div>
          <h2 className="sv-section-title">Evaluation workflow</h2>
          <p>Move through setup, launch, and inspection as separate screens.</p>
        </div>
      </div>
      <div className="rag-eval-workflow-steps">
        <WorkflowStep index="1" title="Datasets" detail={datasetsLoading ? "Loading datasets" : `${datasetsCount} imported`} onClick={() => onOpenScreen("datasets")} />
        <WorkflowStep index="2" title="New evaluation" detail={datasetsCount ? "Choose scope and queue" : "Import a dataset first"} onClick={() => onOpenScreen(datasetsCount ? "new-run" : "datasets")} />
        <WorkflowStep index="3" title="Query tracker" detail="Run one live trace" onClick={() => onOpenScreen("query-tracker")} />
        <WorkflowStep index="4" title="Runs" detail={activeRuns ? `${activeRuns} active` : `${runs.length} total`} onClick={() => onOpenScreen("runs")} />
      </div>
    </section>
  );
}

function WorkflowStep({ detail, index, onClick, title }: { detail: string; index: string; onClick: () => void; title: string }) {
  return (
    <button type="button" className="rag-eval-workflow-step" onClick={onClick}>
      <span>{index}</span>
      <strong>{title}</strong>
      <small>{detail}</small>
    </button>
  );
}

function RunSummaryPanel({ failureBreakdown, onInspect, selectedRun }: { failureBreakdown: Record<string, number>; onInspect: () => void; selectedRun: EvaluationRunSummary | null }) {
  if (!selectedRun) {
    return (
      <section className="sv-panel p-5">
        <EmptyPanel>No runs yet. Import a dataset and queue a new evaluation to see run status here.</EmptyPanel>
      </section>
    );
  }
  return (
    <section className="sv-panel rag-eval-run-summary-panel">
      <div className="rag-eval-section-header">
        <div>
          <h2 className="sv-section-title">Current run</h2>
          <p>{selectedRun.dataset_name} / {selectedRun.stage}</p>
        </div>
        <StatusBadge status={selectedRun.status} />
      </div>
      <div className="rag-eval-run-summary-body">
        <div className="rag-eval-progress">
          <span style={{ width: `${selectedRun.progress_pct}%` }} />
        </div>
        <p>{selectedRun.completed_count} of {selectedRun.case_count} cases complete. {selectedRun.failed_count} failed.</p>
        <FailureBreakdown breakdown={failureBreakdown} />
        <button type="button" className="sv-action-secondary" onClick={onInspect}>Inspect run</button>
      </div>
    </section>
  );
}

function DatasetsScreen({ datasets, loading, onNewRun }: { datasets: EvaluationDatasetSummary[]; loading: boolean; onNewRun: () => void }) {
  return (
    <div className="rag-eval-screen rag-eval-datasets-grid">
      <DatasetImportPanel />
      <DatasetLibraryPanel datasets={datasets} loading={loading} onNewRun={onNewRun} />
    </div>
  );
}

function DatasetLibraryPanel({ datasets, loading, onNewRun }: { datasets: EvaluationDatasetSummary[]; loading: boolean; onNewRun: () => void }) {
  return (
    <section className="sv-panel rag-eval-dataset-library">
      <div className="rag-eval-section-header">
        <div>
          <h2 className="sv-section-title">Dataset library</h2>
          <p>Imported case sets available for evaluation runs.</p>
        </div>
        <span className="sv-pill">{loading ? "Loading" : `${datasets.length} datasets`}</span>
      </div>
      {loading ? <div className="p-4 grid gap-3"><Skeleton className="h-16" /><Skeleton className="h-16" /></div> : null}
      {!loading && datasets.length === 0 ? <div className="p-4"><EmptyPanel>Import a JSON or JSONL dataset to start evaluating RAG answers.</EmptyPanel></div> : null}
      <div className="rag-eval-dataset-list">
        {datasets.map((dataset) => (
          <article key={dataset.id} className="rag-eval-dataset-row">
            <div>
              <strong>{dataset.name}</strong>
              <small>{dataset.case_count} cases / {dataset.source_format} / {formatDateTime(dataset.created_at)}</small>
              {dataset.description ? <p>{dataset.description}</p> : null}
            </div>
            <button type="button" className="sv-action-secondary" onClick={onNewRun}>Use dataset</button>
          </article>
        ))}
      </div>
    </section>
  );
}

function NewRunScreen({ datasets, datasetsLoading, onRunCreated }: { datasets: EvaluationDatasetSummary[]; datasetsLoading: boolean; onRunCreated: (runId: string) => void }) {
  return (
    <div className="rag-eval-screen rag-eval-new-run-grid">
      <RunLauncherPanel datasets={datasets} datasetsLoading={datasetsLoading} onRunCreated={onRunCreated} />
      <section className="sv-panel p-5">
        <div className="rag-eval-panel-header">
          <span><Info size={18} /> Before queueing</span>
        </div>
        <div className="rag-eval-guidance-list">
          <p><strong>Scope is part of the result.</strong><span>Knowledge Space and document IDs are captured with the run.</span></p>
          <p><strong>Permission context is captured.</strong><span>Results reflect the submitter's visible corpus at launch time.</span></p>
          <p><strong>Case IDs and limit are exclusive.</strong><span>Use one when you want a targeted or sampled run.</span></p>
        </div>
      </section>
    </div>
  );
}

function RunsScreen({ detail, failureBreakdown, loading, metricsLoading, onSelectRun, runs, runsLoading, selectedRun, summarySource }: {
  detail: EvaluationRunDetail | null;
  failureBreakdown: Record<string, number>;
  loading: boolean;
  metricsLoading: boolean;
  onSelectRun: (runId: string) => void;
  runs: EvaluationRunSummary[];
  runsLoading: boolean;
  selectedRun: EvaluationRunSummary | null;
  summarySource: EvaluationRunSummary | EvaluationRunDetail | null | undefined;
}) {
  return (
    <div className="rag-eval-screen">
      <EvaluationMetrics run={summarySource} loading={metricsLoading} />
      <div className="rag-eval-main-grid">
        <RunHistoryPanel loading={runsLoading} runs={runs} selectedRunId={selectedRun?.id ?? null} onSelect={onSelectRun} />
        <RunInspectionPanel detail={detail} failureBreakdown={failureBreakdown} loading={loading} selectedRun={selectedRun} />
      </div>
    </div>
  );
}

function EvaluationMetrics({ loading, run }: { loading: boolean; run: EvaluationRunSummary | EvaluationRunDetail | null | undefined }) {
  const summary = run?.summary ?? {};
  const total = numberFromSummary(summary, "total", run?.case_count ?? 0);
  const passRate = percent(numberFromSummary(summary, "pass_rate", ratio(run?.passed_count ?? 0, total)));
  const retrievalRate = percent(numberFromSummary(summary, "retrieval_pass_rate", 0));
  const rerankingRate = optionalPercent(summary, ["reranking_pass_rate", "source_selection_pass_rate"]);
  const citationRate = percent(numberFromSummary(summary, "citation_pass_rate", 0));
  const faithfulnessRate = percent(numberFromSummary(summary, "faithfulness_pass_rate", 0));
  const fallbackRate = optionalPercent(summary, ["reranker_fallback_rate"]);
  const avgLatency = numberFromSummary(summary, "avg_latency_ms", 0);

  return (
    <section className="rag-eval-metrics" aria-label="RAG evaluation summary">
      <MetricCard label="Pass rate" value={passRate} detail={`${run?.passed_count ?? 0} of ${total} cases passed`} loading={loading} tone="success" />
      <MetricCard label="Retrieval" value={retrievalRate} detail="Expected evidence retrieved" loading={loading} tone="active" />
      <MetricCard label="Reranking" value={rerankingRate ?? "N/A"} detail="Expected evidence kept after ranking" loading={loading} tone="neutral" />
      <MetricCard label="Citations" value={citationRate} detail="Required citations present" loading={loading} tone="neutral" />
      <MetricCard label="Faithfulness" value={faithfulnessRate} detail="Judge threshold passed" loading={loading} tone="warning" />
      <MetricCard label="Fallbacks" value={fallbackRate ?? "N/A"} detail="Reranker fallback rate" loading={loading} tone="warning" />
      <MetricCard label="Avg latency" value={avgLatency ? `${avgLatency}ms` : "0ms"} detail="Mean case runtime" loading={loading} tone="neutral" />
    </section>
  );
}

function MetricCard({ detail, label, loading, tone, value }: { detail: string; label: string; loading: boolean; tone: string; value: string }) {
  return (
    <article className="sv-panel rag-eval-metric" data-tone={tone} aria-busy={loading} data-cursor-glow>
      <p>{label}</p>
      {loading ? <Skeleton className="mt-2 h-7 w-16" /> : <strong>{value}</strong>}
      <small>{detail}</small>
    </article>
  );
}

function DatasetImportPanel() {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [sourceFormat, setSourceFormat] = useState<EvaluationDatasetImportRequest["source_format"]>("auto");
  const importMutation = useMutation({
    mutationFn: ragEvaluationsApi.importDataset,
    onSuccess: async (dataset) => {
      setName("");
      setContent("");
      setSourceFormat("auto");
      await queryClient.invalidateQueries({ queryKey: ["rag-evaluations", "datasets"] });
      notify({ title: "Dataset imported", description: `${dataset.case_count} cases normalized.`, tone: "success" });
    },
    onError: (error) => notify({ title: "Import failed", description: errorMessage(error, "Unable to import evaluation dataset."), tone: "error" }),
  });
  const canImport = content.trim().length > 0 && !importMutation.isPending;

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setContent(await file.text());
    if (!name.trim()) setName(file.name.replace(/\.(jsonl?|txt)$/i, ""));
  }

  return (
    <section className="sv-panel p-5">
      <div className="rag-eval-panel-header">
        <span><FileJson size={18} /> Dataset Import</span>
        <div className="rag-eval-format-meta">
          <small>JSON or JSONL</small>
          <div className="rag-eval-format-help">
            <button
              type="button"
              className="rag-eval-tooltip-trigger"
              aria-label="Expected JSON format"
              aria-describedby="rag-eval-json-format-tooltip"
            >
              <Info size={14} aria-hidden="true" />
            </button>
            <div className="rag-eval-format-tooltip" id="rag-eval-json-format-tooltip" role="tooltip">
              <strong>Expected JSON format</strong>
              <p>Import a JSON array of cases, one JSON object per JSONL line, or a fixture object with generation_cases.</p>
              <code>{`[{"id":"case_1","question":"What does the policy require?","expected_source_docs":["Policy.pdf"],"must_include":["approval"],"must_cite_source":true}]`}</code>
              <small>Required: question or query. Recommended: stable id or case_id. Optional: expected_answer, must_include, must_not_include, expected_source_docs, acceptable_source_pages, min_sources, min_faithfulness_score, latency_threshold_ms.</small>
            </div>
          </div>
        </div>
      </div>
      <div className="rag-eval-form-grid items-start">
        <label className="sv-field">
          <span className="sv-label">Dataset name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} className="sv-input" placeholder="Dell R630 smoke set" />
          <small className="text-secondary">Optional; file name is used when left blank.</small>
        </label>
        <label className="sv-field">
          <span className="sv-label">Format</span>
          <select value={sourceFormat} onChange={(event) => setSourceFormat(event.target.value as EvaluationDatasetImportRequest["source_format"])} className="sv-input">
            <option value="auto">Auto detect</option>
            <option value="json">JSON</option>
            <option value="jsonl">JSONL</option>
          </select>
          <small className="text-secondary">Auto detects JSON arrays, JSONL, or fixture objects.</small>
        </label>
      </div>
      <label className="sv-field mt-3">
        <span className="sv-label">Upload file</span>
        <input type="file" accept=".json,.jsonl,application/json,text/plain" onChange={(event) => void handleFile(event.target.files?.[0])} className="sv-input" />
        <small className="text-secondary">Loads JSON or JSONL into the content field for review.</small>
      </label>
      <label className="sv-field mt-3">
        <span className="sv-label">Dataset content</span>
        <textarea value={content} onChange={(event) => setContent(event.target.value)} rows={6} className="sv-textarea rag-eval-textarea" placeholder='[{"id":"smoke_1","question":"What does the policy require?","expected_source_docs":["Policy.pdf"]}]' />
        <small className="text-secondary">Paste cases with question or query plus optional expectations.</small>
      </label>
      <button
        type="button"
        className="sv-action-primary mt-4"
        disabled={!canImport}
        onClick={() => importMutation.mutate({ name: name.trim() || null, content, source_format: sourceFormat })}
      >
        {importMutation.isPending ? <Loader2 className="animate-spin" size={16} /> : <FileJson size={16} />}
        {importMutation.isPending ? "Importing" : "Import dataset"}
      </button>
    </section>
  );
}

function RunLauncherPanel({ datasets, datasetsLoading, onRunCreated }: { datasets: EvaluationDatasetSummary[]; datasetsLoading: boolean; onRunCreated: (runId: string) => void }) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [datasetId, setDatasetId] = useState("");
  const [groupPath, setGroupPath] = useState("");
  const [documentIds, setDocumentIds] = useState("");
  const [caseIds, setCaseIds] = useState("");
  const [limit, setLimit] = useState("");
  const selectedDataset = datasets.find((dataset) => dataset.id === datasetId) ?? datasets[0] ?? null;

  useEffect(() => {
    if (!datasetId && datasets.length > 0) setDatasetId(datasets[0].id);
  }, [datasetId, datasets]);

  const createRunMutation = useMutation({
    mutationFn: ragEvaluationsApi.createRun,
    onSuccess: async (run) => {
      onRunCreated(run.id);
      await queryClient.invalidateQueries({ queryKey: ["rag-evaluations", "runs"] });
      notify({ title: "Evaluation queued", description: `${run.dataset_name} has ${run.case_count} cases.`, tone: "success" });
    },
    onError: (error) => notify({ title: "Run failed to queue", description: errorMessage(error, "Unable to queue evaluation run."), tone: "error" }),
  });
  const parsedCaseIds = splitCsv(caseIds);
  const parsedLimit = limit.trim() ? Number(limit) : null;
  const canRun = Boolean(selectedDataset) && !createRunMutation.isPending && !(parsedCaseIds.length > 0 && parsedLimit);

  function submitRun() {
    if (!selectedDataset) return;
    const request: EvaluationRunCreateRequest = {
      dataset_id: selectedDataset.id,
      group_path: groupPath.trim() || null,
      document_ids: splitCsv(documentIds),
      case_ids: parsedCaseIds,
      limit: parsedLimit,
    };
    createRunMutation.mutate(request);
  }

  return (
    <section className="sv-panel p-5">
      <div className="rag-eval-panel-header">
        <span><Play size={18} /> Launch Run</span>
        <small>{selectedDataset ? `${selectedDataset.case_count} cases available` : "No dataset"}</small>
      </div>
      {datasetsLoading ? <Skeleton className="mt-4 h-10 w-full" /> : null}
      {!datasetsLoading && datasets.length === 0 ? <EmptyPanel>Import a JSON or JSONL evaluation dataset before launching a run.</EmptyPanel> : null}
      {datasets.length > 0 ? (
        <div className="rag-eval-form-grid items-start">
          <label className="sv-field">
            <span className="sv-label">Dataset</span>
            <select value={selectedDataset?.id ?? ""} onChange={(event) => setDatasetId(event.target.value)} className="sv-input">
              {datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}
            </select>
            <small className="text-secondary">Choose the imported case set for this run.</small>
          </label>
          <label className="sv-field">
            <span className="sv-label">Knowledge Space</span>
            <input value={groupPath} onChange={(event) => setGroupPath(event.target.value)} className="sv-input" placeholder="/manuals" />
            <small className="text-secondary">Optional retrieval scope; leave blank to use all visible spaces.</small>
          </label>
          <label className="sv-field">
            <span className="sv-label">Document IDs</span>
            <input value={documentIds} onChange={(event) => setDocumentIds(event.target.value)} className="sv-input" placeholder="Optional, comma-separated" />
            <small className="text-secondary">Optional comma-separated document IDs to force scope.</small>
          </label>
          <label className="sv-field">
            <span className="sv-label">Case IDs</span>
            <input value={caseIds} onChange={(event) => setCaseIds(event.target.value)} className="sv-input" placeholder="Optional, comma-separated" />
            <small className="text-secondary">Optional comma-separated case IDs; cannot be combined with a limit.</small>
          </label>
          <label className="sv-field">
            <span className="sv-label">Limit</span>
            <input value={limit} onChange={(event) => setLimit(event.target.value)} min={1} type="number" className="sv-input" placeholder="Optional" />
            <small className="text-secondary">Optional number of cases to sample from the selected dataset.</small>
          </label>
        </div>
      ) : null}
      {parsedCaseIds.length > 0 && parsedLimit ? <InlineMessage tone="warning">Use either case IDs or a limit, not both.</InlineMessage> : null}
      <button type="button" className="sv-action-primary mt-4" disabled={!canRun} onClick={submitRun}>
        {createRunMutation.isPending ? <Loader2 className="animate-spin" size={16} /> : <Play size={16} />}
        {createRunMutation.isPending ? "Queueing" : "Run evaluation"}
      </button>
    </section>
  );
}

function RunHistoryPanel({ loading, onSelect, runs, selectedRunId }: { loading: boolean; onSelect: (runId: string) => void; runs: EvaluationRunSummary[]; selectedRunId: string | null }) {
  return (
    <section className="sv-panel rag-eval-history">
      <div className="rag-eval-section-header">
        <div>
          <h2 className="sv-section-title">Run History</h2>
          <p>Recent evaluation runs and progress.</p>
        </div>
        <span className="sv-pill">{loading ? "Loading" : `${runs.length} runs`}</span>
      </div>
      {loading ? (
        <div className="p-4 grid gap-3"><Skeleton className="h-16" /><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
      ) : null}
      {!loading && runs.length === 0 ? <div className="p-4"><EmptyPanel>No evaluation runs have been launched yet.</EmptyPanel></div> : null}
      <div className="rag-eval-run-list" role="list">
        {runs.map((run) => (
          <button key={run.id} type="button" className="rag-eval-run-row" aria-current={selectedRunId === run.id ? "true" : undefined} onClick={() => onSelect(run.id)}>
            <span>
              <strong>{run.dataset_name}</strong>
              <small>{formatDateTime(run.created_at)} / {run.completed_count} of {run.case_count} cases</small>
            </span>
            <span className="rag-eval-run-state">
              <StatusBadge status={run.status} />
              <span>{run.progress_pct}%</span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

function RunInspectionPanel({ detail, failureBreakdown, loading, selectedRun }: { detail: EvaluationRunDetail | null; failureBreakdown: Record<string, number>; loading: boolean; selectedRun: EvaluationRunSummary | null }) {
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const cases = detail?.cases ?? [];
  const selectedCase = selectedCaseId ? cases.find((item) => item.id === selectedCaseId) ?? null : cases[0] ?? null;

  useEffect(() => {
    if (!selectedCaseId && cases.length > 0) setSelectedCaseId(cases[0].id);
    if (selectedCaseId && cases.length > 0 && !cases.some((item) => item.id === selectedCaseId)) setSelectedCaseId(cases[0].id);
    if (cases.length === 0 && selectedCaseId) setSelectedCaseId(null);
  }, [cases, selectedCaseId]);

  if (!selectedRun) {
    return (
      <section className="sv-panel p-5">
        <EmptyPanel>Select or launch a run to inspect RAG failure stages.</EmptyPanel>
      </section>
    );
  }

  return (
    <section className="sv-panel rag-eval-inspection">
      <div className="rag-eval-section-header">
        <div>
          <h2 className="sv-section-title">Run Inspection</h2>
          <p>{selectedRun.dataset_name} / {selectedRun.stage}</p>
        </div>
        <StatusBadge status={selectedRun.status} />
      </div>
      {loading ? <div className="p-5"><Skeleton className="h-28 w-full" /></div> : null}
      <FailureBreakdown breakdown={failureBreakdown} />
      {detail?.error_message ? <InlineMessage tone="error">{detail.error_message}</InlineMessage> : null}
      {cases.length === 0 && !loading ? <div className="p-5"><EmptyPanel>Case results will appear as the evaluation worker completes each case.</EmptyPanel></div> : null}
      {cases.length > 0 ? (
        <div className="rag-eval-detail-grid">
          <CaseTable cases={cases} selectedId={selectedCase?.id ?? null} onSelect={setSelectedCaseId} />
          <CaseDetailPanel result={selectedCase} />
        </div>
      ) : null}
    </section>
  );
}

function FailureBreakdown({ breakdown }: { breakdown: Record<string, number> }) {
  const entries = Object.entries(breakdown).sort(([, left], [, right]) => right - left);
  return (
    <div className="rag-eval-breakdown" aria-label="Failure breakdown">
      <div>
        <h3>Failure Breakdown</h3>
        <p>Primary failure stage for failed cases.</p>
      </div>
      {entries.length === 0 ? <span className="rag-eval-no-failures"><CheckCircle2 size={15} /> No failed cases recorded</span> : null}
      {entries.map(([stage, count]) => (
        <span key={stage} className="rag-eval-failure-chip">
          {failureStageLabel(stage as EvaluationFailureStage)}
          <strong>{count}</strong>
        </span>
      ))}
    </div>
  );
}

function CaseTable({ cases, onSelect, selectedId }: { cases: EvaluationCaseResult[]; onSelect: (id: string) => void; selectedId: string | null }) {
  return (
    <div className="rag-eval-case-table" role="list" aria-label="Evaluation case results">
      {cases.map((result) => (
        <button key={result.id} type="button" className="rag-eval-case-row" aria-current={selectedId === result.id ? "true" : undefined} onClick={() => onSelect(result.id)}>
          <span className={result.passed ? "rag-eval-result-icon passed" : "rag-eval-result-icon failed"}>
            {result.passed ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
          </span>
          <span>
            <strong>{result.case_id}</strong>
            <small>{result.question}</small>
          </span>
          <span className="rag-eval-stage-stack">
            {result.primary_failure_stage ? <FailureStageBadge stage={result.primary_failure_stage} /> : <span className="sv-pill">Passed</span>}
          </span>
        </button>
      ))}
    </div>
  );
}

function CaseDetailPanel({ result }: { result: EvaluationCaseResult | null }) {
  if (!result) return <EmptyPanel>Select a case to inspect answer, sources, timings, and diagnostics.</EmptyPanel>;
  const secondaryStages = result.failure_stages.filter((stage) => stage !== result.primary_failure_stage);
  return (
    <article className="rag-eval-case-detail">
      <div className="rag-eval-case-detail-header">
        <div>
          <h3>{result.case_id}</h3>
          <p>{result.question}</p>
        </div>
        <span className={result.passed ? "rag-eval-pass-pill" : "rag-eval-fail-pill"}>{result.passed ? "Passed" : "Failed"}</span>
      </div>
      {result.error_message ? <InlineMessage tone="error">{result.error_message}</InlineMessage> : null}
      <div className="rag-eval-stage-badges">
        {result.primary_failure_stage ? <FailureStageBadge stage={result.primary_failure_stage} /> : null}
        {secondaryStages.map((stage) => <FailureStageBadge key={stage} stage={stage} secondary />)}
      </div>
      <dl className="rag-eval-facts">
        <Fact label="Trace" value={result.trace_id ?? "Unavailable"} />
        <Fact label="Latency" value={`${result.latency_ms}ms`} />
        <Fact label="Faithfulness" value={result.faithfulness_score === null ? "Unavailable" : `${Math.round(result.faithfulness_score * 100)}%`} />
        <Fact label="Degraded" value={result.degraded ? result.degraded_reason ?? "Yes" : "No"} />
      </dl>
      <RagEvaluationDiagnostics result={result} />
      <section>
        <h4>Answer</h4>
        <p className="rag-eval-answer">{result.answer || "No answer was generated."}</p>
      </section>
      <section>
        <details className="rag-eval-raw-details">
          <summary>Checks and diagnostic JSON</summary>
          <pre className="rag-eval-json">{JSON.stringify({ checks: result.checks, diagnostic: result.diagnostic }, null, 2)}</pre>
        </details>
      </section>
      <section>
        <h4>Node timings</h4>
        {result.node_timings.length === 0 ? <p className="text-secondary">No node timings were recorded.</p> : null}
        <div className="rag-eval-timing-list">
          {result.node_timings.map((timing, index) => (
            <span key={`${String(timing.node ?? index)}-${index}`}>{String(timing.node ?? "node")} · {String(timing.duration_ms ?? 0)}ms</span>
          ))}
        </div>
      </section>
    </article>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function StatusBadge({ status }: { status: EvaluationRunStatus }) {
  return <span className="rag-eval-status" data-status={status}>{statusLabel(status)}</span>;
}

function FailureStageBadge({ secondary = false, stage }: { secondary?: boolean; stage: EvaluationFailureStage }) {
  return <span className={secondary ? "rag-eval-stage-badge secondary" : "rag-eval-stage-badge"}>{failureStageLabel(stage)}</span>;
}

function statusLabel(status: EvaluationRunStatus) {
  const labels: Record<EvaluationRunStatus, string> = {
    queued: "Queued",
    running: "Running",
    complete: "Complete",
    partial: "Partial",
    failed: "Failed",
    cancelled: "Cancelled",
  };
  return labels[status];
}

function failureStageLabel(stage: EvaluationFailureStage) {
  const labels: Record<EvaluationFailureStage, string> = {
    dataset: "Dataset",
    "ingestion/indexing": "Ingestion / indexing",
    retrieval: "Retrieval",
    "reranking/source_selection": "Source selection",
    answer_content: "Answer content",
    citation: "Citation",
    faithfulness: "Faithfulness",
    degradation: "Degradation",
    runtime: "Runtime",
    latency: "Latency",
  };
  return labels[stage] ?? stage;
}

function isRunActive(status: EvaluationRunStatus) {
  return status === "queued" || status === "running";
}

function isRunRetryable(status: EvaluationRunStatus) {
  return status === "failed" || status === "partial" || status === "cancelled";
}

function numberFromSummary(summary: Record<string, unknown>, key: string, fallback: number) {
  const value = summary[key];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function failureBreakdownFromSummary(summary: Record<string, unknown> | undefined) {
  const value = summary?.failure_breakdown;
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value).filter(([, count]) => typeof count === "number")) as Record<string, number>;
}

function ratio(value: number, total: number) {
  return total > 0 ? value / total : 0;
}

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function optionalPercent(summary: Record<string, unknown>, keys: string[]) {
  const value = keys.map((key) => summary[key]).find((item) => typeof item === "number" && Number.isFinite(item));
  return typeof value === "number" ? percent(value) : null;
}

function splitCsv(value: string) {
  return value.split(",").map((part) => part.trim()).filter(Boolean);
}

type RagEvalScreen = "overview" | "datasets" | "new-run" | "query-tracker" | "runs";
type Props = {
  activeSpacePath: string | null;
  currentDocuments: Document[];
  documents: Document[];
  documentsLoading: boolean;
  onActiveSpaceChange: (path: string | null) => void;
  onLogout: () => void;
  onNavigate: (route: RouteId) => void;
  user: AuthUser;
};
