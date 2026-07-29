import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, RotateCcw, StopCircle } from "lucide-react";

import { ragEvaluationsApi } from "@/lib/api/contracts";
import { useToast } from "@/components/feedback/ToastProvider";
import { QueryTrackerPanel } from "@/features/evaluations/components/QueryTrackerPanel";
import { InlineMessage } from "@/components/layout/Common";
import { PrudentiaWorkspace } from "@/components/layout/PrudentiaWorkspace";
import type { RouteId } from "@/routes/routes";
import type {
  Document,
  User as AuthUser,
} from "@/types/api";
import { errorMessage } from "@/lib/utils/format";
import {
  failureBreakdownFromSummary,
  isRunActive,
  isRunRetryable,
  type RagEvalScreen,
} from "@/features/evaluations/utils/evaluationPageUtils";
import { OverviewScreen, RagEvaluationScreenTabs } from "@/features/evaluations/components/EvaluationOverview";
import { DatasetsScreen } from "@/features/evaluations/components/EvaluationDatasets";
import { NewRunScreen } from "@/features/evaluations/components/EvaluationRunLauncher";
import { RunsScreen } from "@/features/evaluations/components/EvaluationRuns";


export function PrudentiaRagEvaluationsPage({ activeSpacePath, currentDocuments, documents, documentsLoading, onActiveSpaceChange, onLogout, onNavigate, user }: Props) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [activeScreen, setActiveScreen] = useState<RagEvalScreen>("overview");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [newRunDatasetId, setNewRunDatasetId] = useState<string | null>(null);
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
  const openNewRun = (datasetId: string | null = null) => {
    setNewRunDatasetId(datasetId);
    setActiveScreen(datasets.length > 0 ? "new-run" : "datasets");
  };
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
              <button type="button" className="sv-action-primary" onClick={() => openNewRun()}>
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
          {activeScreen === "datasets" ? <DatasetsScreen datasets={datasets} loading={datasetsQuery.isLoading} onUseDataset={(datasetId) => openNewRun(datasetId)} /> : null}
          {activeScreen === "new-run" ? <NewRunScreen datasets={datasets} datasetsLoading={datasetsQuery.isLoading} initialDatasetId={newRunDatasetId} onRunCreated={handleRunCreated} /> : null}
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
