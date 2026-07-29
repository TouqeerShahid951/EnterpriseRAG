import { useEffect, useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import { RagEvaluationDiagnostics } from "@/features/evaluations/components/RagEvaluationDiagnostics";
import { EmptyPanel, InlineMessage, Skeleton } from "@/components/layout/Common";
import {
  failureStageLabel,
  faithfulnessResultLabel,
  numberFromSummary,
  optionalPercent,
  percent,
  ratio,
  statusLabel,
} from "@/features/evaluations/utils/evaluationPageUtils";
import type {
  EvaluationCaseResult,
  EvaluationFailureStage,
  EvaluationRunDetail,
  EvaluationRunStatus,
  EvaluationRunSummary,
} from "@/types/api";
import { formatDateTime } from "@/lib/utils/format";

export function RunsScreen({ detail, failureBreakdown, loading, metricsLoading, onSelectRun, runs, runsLoading, selectedRun, summarySource }: {
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

export function EvaluationMetrics({ loading, run }: { loading: boolean; run: EvaluationRunSummary | EvaluationRunDetail | null | undefined }) {
  const summary = run?.summary ?? {};
  const total = numberFromSummary(summary, "total", run?.case_count ?? 0);
  const passRate = percent(numberFromSummary(summary, "pass_rate", ratio(run?.passed_count ?? 0, total)));
  const retrievalRate = percent(numberFromSummary(summary, "retrieval_pass_rate", 0));
  const rerankingRate = optionalPercent(summary, ["reranking_pass_rate", "source_selection_pass_rate"]);
  const citationRate = percent(numberFromSummary(summary, "citation_pass_rate", 0));
  const faithfulnessRate = optionalPercent(summary, ["faithfulness_pass_rate"]);
  const faithfulnessCoverage = percent(numberFromSummary(summary, "faithfulness_coverage_rate", 0));
  const fallbackRate = optionalPercent(summary, ["reranker_fallback_rate"]);
  const avgLatency = numberFromSummary(summary, "avg_latency_ms", 0);

  return (
    <section className="rag-eval-metrics" aria-label="RAG evaluation summary">
      <MetricCard label="Pass rate" value={passRate} detail={`${run?.passed_count ?? 0} of ${total} cases passed`} loading={loading} tone="success" />
      <MetricCard label="Retrieval" value={retrievalRate} detail="Expected evidence retrieved" loading={loading} tone="active" />
      <MetricCard label="Reranking" value={rerankingRate ?? "N/A"} detail="Expected evidence kept after ranking" loading={loading} tone="neutral" />
      <MetricCard label="Citations" value={citationRate} detail="Required citations present" loading={loading} tone="neutral" />
      <MetricCard label="Faithfulness" value={faithfulnessRate ?? "N/A"} detail={`${faithfulnessCoverage} judge coverage`} loading={loading} tone="warning" />
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

export function RunHistoryPanel({ loading, onSelect, runs, selectedRunId }: { loading: boolean; onSelect: (runId: string) => void; runs: EvaluationRunSummary[]; selectedRunId: string | null }) {
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

export function FailureBreakdown({ breakdown }: { breakdown: Record<string, number> }) {
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
        <Fact label="Faithfulness" value={faithfulnessResultLabel(result.faithfulness_status, result.faithfulness_score)} />
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
            <span key={`${timing.node}-${index}`}>
              {timing.node} · {timing.duration_ms}ms
              {Object.entries(timing.phase_timings_ms ?? {}).map(([phase, durationMs]) => (
                <small key={phase}> · {phase.split("_").join(" ")} {durationMs}ms</small>
              ))}
            </span>
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

export function StatusBadge({ status }: { status: EvaluationRunStatus }) {
  return <span className="rag-eval-status" data-status={status}>{statusLabel(status)}</span>;
}

function FailureStageBadge({ secondary = false, stage }: { secondary?: boolean; stage: EvaluationFailureStage }) {
  return <span className={secondary ? "rag-eval-stage-badge secondary" : "rag-eval-stage-badge"}>{failureStageLabel(stage)}</span>;
}
