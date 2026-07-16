import { EmptyPanel } from "@/components/layout/Common";
import {
  EvaluationMetrics,
  FailureBreakdown,
  RunHistoryPanel,
  StatusBadge,
} from "@/features/evaluations/components/EvaluationRuns";
import {
  isRunActive,
  type RagEvalScreen,
} from "@/features/evaluations/utils/evaluationPageUtils";
import type { EvaluationRunDetail, EvaluationRunSummary } from "@/types/api";

export function RagEvaluationScreenTabs({ activeScreen, datasetsCount, onChange, runsCount }: { activeScreen: RagEvalScreen; datasetsCount: number; onChange: (screen: RagEvalScreen) => void; runsCount: number }) {
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

export function OverviewScreen({ datasetsCount, datasetsLoading, failureBreakdown, metricsLoading, onOpenScreen, onSelectRun, runs, runsLoading, selectedRun, summarySource }: {
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
