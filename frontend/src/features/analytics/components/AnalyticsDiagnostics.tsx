import type { AnalyticsDiagnostics, AnalyticsStageDiagnostics, AnalyticsScoreStats, AnalyticsTimingDiagnostics } from "@/types/api";

function DocumentUsage({ diagnostics }: { diagnostics: AnalyticsDiagnostics }) {
  const documents = diagnostics.documents;
  return <div className="analytics-document-usage">
    <div className="analytics-panel-heading"><div><h3>Most retrieved documents</h3><p>Distinct generation-aware documents observed in retained retrieved candidates</p></div></div>
    {documents.status === "available" && documents.top_documents.length ? <div className="analytics-table-wrap"><table className="analytics-table"><caption className="sr-only">Most retrieved documents</caption><thead><tr><th scope="col">Document</th><th scope="col">Executions</th><th scope="col">Candidates</th></tr></thead><tbody>{documents.top_documents.map((document) => <tr key={document.document_key}><th scope="row">{document.document_title || document.document_key}</th><td>{document.execution_count.toLocaleString()}</td><td>{document.candidate_count.toLocaleString()}</td></tr>)}</tbody></table></div> : <p className="analytics-empty">Document observations are unavailable for this window.</p>}
    {documents.documents_per_query.count ? <p className="analytics-footnote">Documents per query: mean {documents.documents_per_query.mean?.toFixed(1) ?? "—"} · P50 {documents.documents_per_query.p50?.toFixed(1) ?? "—"} · P95 {documents.documents_per_query.p95?.toFixed(1) ?? "—"} across {documents.documents_per_query.count.toLocaleString()} observed queries.</p> : null}
  </div>;
}

export function AnswerQualityDiagnostics({ diagnostics }: { diagnostics: AnalyticsDiagnostics | undefined }) {
  if (!diagnostics || diagnostics.data_status === "empty") {
    return <DiagnosticEmpty message="No quality measurements are available for this window." />;
  }
  const quality = diagnostics.quality;
  const coverage = quality.applicable_count ? quality.checked_count / quality.applicable_count : null;
  const ledger = quality.claim_ledger;
  return <section className="sv-panel analytics-panel" aria-labelledby="quality-diagnostics-title">
    <header className="analytics-panel-heading"><div><h2 id="quality-diagnostics-title">Qualified answer quality</h2><p>Scores include checked answers only; they are not absolute correctness.</p></div></header>
    <div className="analytics-diagnostic-callouts">
      <DiagnosticMetric label="Checked score mean" value={formatPercent(quality.score.mean)} detail={quality.score.count + " checked scores"} />
      <DiagnosticMetric label="Verification coverage" value={formatPercent(coverage)} detail={quality.checked_count + " checked of " + quality.applicable_count + " applicable"} />
      <DiagnosticMetric label="Claim support coverage" value={ledger.status === "available" ? formatPercent(ledger.support_rate.value) : "Unavailable"} detail={ledger.status === "available" ? `${ledger.supported_claim_count} supported of ${ledger.applicable_claim_count} claims` : "No final claim ledger was retained."} />
      <DiagnosticMetric label="Citation coverage" value={ledger.status === "available" ? formatPercent(ledger.citation_coverage.value) : "Unavailable"} detail={ledger.status === "available" ? `${ledger.cited_claim_count} cited · ${ledger.uncited_claim_count} uncited` : "No final claim ledger was retained."} />
    </div>
    <div className="analytics-diagnostic-grid">
      <QualityCounts title="Verification status" values={quality.status_counts} empty="No verification statuses were captured." />
      <QualityCounts title="Verification method" values={quality.method_counts} empty="No verification methods were captured." />
      <QualityCounts title="Evidence-window support" values={quality.support_status_counts} empty="No evidence-window support states were captured." />
      <QualityCounts title="Final claim verdict" values={{ supported: ledger.supported_claim_count, unsupported: ledger.unsupported_claim_count, unknown: ledger.unknown_claim_count }} empty="No final claim ledgers were captured." />
    </div>
    <p className="analytics-footnote">Semantic fallback evidence is reported separately from verified evidence. Claim support and citation coverage use the final answer ledger and remain unavailable for legacy or uncaptured responses.</p>
  </section>;
}

function QualityCounts({ empty, title, values }: { empty: string; title: string; values: Record<string, number> }) {
  const entries = Object.entries(values);
  return <div className="analytics-diagnostic-table"><h3>{title}</h3>{entries.length ? <table className="analytics-table"><caption className="sr-only">{title}</caption><thead><tr><th scope="col">Value</th><th scope="col">Count</th></tr></thead><tbody>{entries.map(([label, count]) => <tr key={label}><th scope="row">{label.replace(/_/g, " ")}</th><td>{count.toLocaleString()}</td></tr>)}</tbody></table> : <p className="analytics-empty">{empty}</p>}</div>;
}

export function RetrievalDiagnostics({ diagnostics }: { diagnostics: AnalyticsDiagnostics | undefined }) {
  if (!diagnostics || diagnostics.data_status === "empty" || !diagnostics.stages.length) {
    return <DiagnosticEmpty message="No retained retrieval lineage is available for this window." />;
  }
  return <section className="sv-panel analytics-panel" aria-labelledby="retrieval-diagnostics-title">
    <header className="analytics-panel-heading"><div><h2 id="retrieval-diagnostics-title">Retrieval stages</h2><p>Candidate counts and score distributions from retained authorized lineage · scores are diagnostic signals, not relevance accuracy</p></div></header>
    <CaptureStatus counts={diagnostics.capture_status_counts} />
    <div className="analytics-table-wrap"><table className="analytics-table analytics-diagnostics-table"><caption className="sr-only">Retrieval stage score diagnostics</caption><thead><tr><th scope="col">Stage</th><th scope="col">Executions</th><th scope="col">Candidates</th><th scope="col">Retained</th><th scope="col">Retrieval P50 / P95</th><th scope="col">Rerank P50 / P95</th><th scope="col">Adjusted P50 / P95</th></tr></thead><tbody>{diagnostics.stages.map((stage) => <StageRow key={stage.name} stage={stage} />)}</tbody></table></div>
    <div className="analytics-diagnostic-callouts"><DiagnosticMetric label="Top-k overlap" value={diagnostics.documents.top_k_turnover.status === "available" ? formatPercent(diagnostics.documents.top_k_turnover.mean_overlap) : "Unavailable"} detail={diagnostics.documents.top_k_turnover.status === "available" ? (diagnostics.documents.top_k_turnover.mean_added?.toFixed(1) ?? "—") + " added · " + (diagnostics.documents.top_k_turnover.mean_dropped?.toFixed(1) ?? "—") + " dropped" : "Rerank input and final evidence sets were not both retained."} /></div>
    <ScoreDistribution stages={diagnostics.stages} />
    <DocumentUsage diagnostics={diagnostics} />
    <div className="analytics-diagnostic-callouts"><DiagnosticMetric label="Reranker movement" value={diagnostics.rank_movement.status === "available" ? `${diagnostics.rank_movement.mean_absolute?.toFixed(1) ?? "—"} positions` : "Not measured"} detail={diagnostics.rank_movement.status === "available" ? `${diagnostics.rank_movement.promoted} promoted · ${diagnostics.rank_movement.demoted} demoted · ${diagnostics.rank_movement.unchanged} unchanged` : "A complete rerank input/output candidate set is required."} /><DiagnosticMetric label="Evidence utilization" value={diagnostics.evidence_utilization.status === "available" ? formatPercent(diagnostics.evidence_utilization.utilization_rate) : "Unavailable"} detail={diagnostics.evidence_utilization.status === "available" ? `${diagnostics.evidence_utilization.cited_source_count} cited of ${diagnostics.evidence_utilization.sent_source_count} sent sources` : "Generation and citation mappings were not retained."} /></div>
  </section>;
}

export function PerformanceDiagnostics({ diagnostics }: { diagnostics: AnalyticsDiagnostics | undefined }) {
  if (!diagnostics || diagnostics.data_status === "empty" || (!diagnostics.timings.length && !diagnostics.cohorts.length)) {
    return <DiagnosticEmpty message="Stage timing data is not measured for this window." />;
  }
  return <section className="sv-panel analytics-panel" aria-labelledby="performance-diagnostics-title">
    <header className="analytics-panel-heading"><div><h2 id="performance-diagnostics-title">Pipeline timing</h2><p>Repeated stage runs are summed per execution before P50/P95 are calculated · milliseconds</p></div></header>
    <CaptureStatus counts={diagnostics.capture_status_counts} />
    <CohortMarkers diagnostics={diagnostics} />
    {diagnostics.timings.length ? <div className="analytics-table-wrap"><table className="analytics-table analytics-diagnostics-table"><caption className="sr-only">Pipeline node timing diagnostics</caption><thead><tr><th scope="col">Stage</th><th scope="col">Executions</th><th scope="col">Samples</th><th scope="col">P50</th><th scope="col">P95</th></tr></thead><tbody>{diagnostics.timings.map((timing) => <TimingRow key={timing.node} timing={timing} />)}</tbody></table></div> : <p className="analytics-empty">Timing samples are unavailable for this window.</p>}
  </section>;
}

function CohortMarkers({ diagnostics }: { diagnostics: AnalyticsDiagnostics }) {
  if (!diagnostics.cohorts.length) return <p className="analytics-empty">Configuration cohort markers are unavailable for this window.</p>;
  return <div className="analytics-document-usage"><div className="analytics-panel-heading"><div><h3>Configuration cohorts</h3><p>First observed query timestamps identify cohorts; they do not claim deployment completion.</p></div></div><div className="analytics-table-wrap"><table className="analytics-table"><caption className="sr-only">Configuration cohort markers</caption><thead><tr><th scope="col">Model cohort</th><th scope="col">Configuration</th><th scope="col">Image digest</th><th scope="col">First observed</th><th scope="col">Executions</th></tr></thead><tbody>{diagnostics.cohorts.map((cohort) => <tr key={`${cohort.model_cohort}:${cohort.configuration_digest}`}><th scope="row">{cohort.model_cohort}</th><td>{cohort.configuration_digest}</td><td>{cohort.application_image_digest ?? "Unavailable"}</td><td>{cohort.first_observed_at ? formatDate(cohort.first_observed_at) : "Unavailable"}</td><td>{cohort.execution_count.toLocaleString()}</td></tr>)}</tbody></table></div></div>;
}

function StageRow({ stage }: { stage: AnalyticsStageDiagnostics }) {
  return <tr><th scope="row">{stage.name}</th><td>{stage.execution_count.toLocaleString()}</td><td>{stage.candidate_count.toLocaleString()}</td><td>{stage.serialized_candidate_count.toLocaleString()}</td><td>{scoreRange(stage.retrieval_score)}</td><td>{scoreRange(stage.rerank_score)}</td><td>{scoreRange(stage.adjusted_rerank_score)}</td></tr>;
}

function TimingRow({ timing }: { timing: AnalyticsTimingDiagnostics }) {
  return <tr><th scope="row">{timing.node}</th><td>{timing.execution_count.toLocaleString()}</td><td>{timing.duration_count.toLocaleString()}</td><td>{formatMs(timing.p50_ms)}</td><td>{formatMs(timing.p95_ms)}</td></tr>;
}

function ScoreDistribution({ stages }: { stages: AnalyticsStageDiagnostics[] }) {
  const labels = stages[0]?.retrieval_score.buckets.map(([label]) => label) ?? [];
  if (!labels.length) return null;
  return <div className="analytics-table-wrap analytics-score-distribution"><table className="analytics-table"><caption>Retrieval score distribution by stage</caption><thead><tr><th scope="col">Stage</th>{labels.map((label) => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{stages.map((stage) => <tr key={stage.name}><th scope="row">{stage.name}</th>{labels.map((label) => <td key={label}>{stage.retrieval_score.buckets.find(([bucket]) => bucket === label)?.[1] ?? 0}</td>)}</tr>)}</tbody></table></div>;
}

function CaptureStatus({ counts }: { counts: Record<string, number> }) {
  return <p className="analytics-diagnostic-status">Capture: {Object.entries(counts).map(([status, count]) => `${status.replace(/_/g, " ")} ${count.toLocaleString()}`).join(" · ")}</p>;
}

function DiagnosticMetric({ detail, label, value }: { detail: string; label: string; value: string }) {
  return <div className="analytics-diagnostic-metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

function DiagnosticEmpty({ message }: { message: string }) {
  return <section className="sv-panel analytics-panel" role="status"><p className="analytics-empty">{message}</p></section>;
}

function scoreRange(stats: AnalyticsScoreStats) {
  return stats.count ? `${formatScore(stats.p50)} / ${formatScore(stats.p95)} (${stats.count.toLocaleString()})` : "Not measured";
}

function formatScore(value: number | null) { return value === null ? "—" : value.toFixed(3); }
function formatMs(value: number | null) { return value === null ? "Not measured" : `${Math.round(value)} ms`; }
function formatPercent(value: number | null) { return value === null ? "Not measured" : `${(value * 100).toFixed(1)}%`; }
function formatDate(value: string) { const date = new Date(value); return `${date.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ${date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`; }
