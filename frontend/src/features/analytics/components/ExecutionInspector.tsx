import { useEffect, useRef } from "react";

import { InlineMessage, Skeleton } from "@/components/layout/Common";
import { ApiClientError } from "@/lib/api/client";
import type { AnalyticsExecution, AnalyticsEvidenceIdentity } from "@/types/api/analytics";
import { executionStatus } from "../utils/executionStatus";

export function ExecutionInspector({ execution, loading, error, onClose, onRetry }: {
  execution?: AnalyticsExecution;
  loading: boolean;
  error: Error | null;
  onClose: () => void;
  onRetry: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, [execution?.execution_id]);
  const lineage = execution?.retrieval_lineage;
  const timings = lineage?.performance?.node_timings ?? [];
  const ledger = lineage?.quality?.claim_ledger;
  return <section className="sv-panel analytics-inspector" aria-labelledby="inspector-title" aria-busy={loading}>
    <header className="analytics-panel-heading">
      <div><h2 id="inspector-title" ref={heading} tabIndex={-1}>Execution details</h2><p>{execution?.execution_id}</p></div>
      <button type="button" className="sv-action-secondary" onClick={onClose}>Close</button>
    </header>
    {loading ? <><p className="sr-only" role="status">Loading execution details</p><Skeleton className="h-48" /></> : null}
    {error ? <InlineMessage tone="error">{detailError(error)} <button type="button" className="sv-action-secondary" onClick={onRetry}>Retry</button></InlineMessage> : null}
    {execution && !error ? <>
      <dl className="analytics-detail-grid">
        <Detail label="Outcome" value={executionStatus(execution)} />
        <Detail label="Reason" value={execution.reason_code ?? execution.degraded_reason} />
        <Detail label="Origin" value={execution.origin} />
        <Detail label="Knowledge Space" value={execution.group_path ?? "All authorized scope"} />
        <Detail label="Requested route" value={execution.requested_source_mode} />
        <Detail label="Resolved route" value={execution.resolved_source_mode} />
        <Detail label="Initial intent" value={execution.initial_intent} />
        <Detail label="Final intent" value={execution.final_intent} />
        <Detail label="Latency" value={execution.latency_ms === null ? null : `${execution.latency_ms} ms`} />
        <Detail label="Retries" value={execution.retry_count} />
        <Detail label="Last heartbeat (UTC)" value={execution.last_heartbeat_at} />
        <Detail label="Verification" value={execution.verification_status ?? "Not measured"} />
        <Detail label="Verification method" value={execution.verification_method} />
        <Detail label="Score subject" value={lineage?.quality?.score_subject} />
        <Detail label="Model cohort" value={execution.model_cohort} />
        <Detail label="Configuration" value={execution.configuration_digest} />
        <Detail label="Image digest" value={execution.application_image_digest} />
      </dl>
      {execution.liveness_status === "heartbeat_expired" ? <p role="status">The execution heartbeat is overdue. Any recorded interruption is inferred; a returning heartbeat or final result can correct it. This does not cancel the query.</p> : null}
      {execution.liveness_status === "untracked" ? <p role="status">This older execution has no heartbeat tracking. Its running status cannot be established from its age.</p> : null}
      <p className="analytics-footnote">Conversation content restricted. Evidence is shown as identifiers; document titles and content require separate current access checks.</p>
      <h3>Pipeline timings</h3>
      {timings.length ? <div className="analytics-table-wrap"><table className="analytics-table">
        <caption>Individual stage runs, including retries</caption><thead><tr><th scope="col">Run</th><th scope="col">Stage</th><th scope="col">Duration</th></tr></thead>
        <tbody>{timings.map((timing, index) => <tr key={index}><td>{index + 1}</td><th scope="row">{timing.node}</th><td>{timing.duration_ms} ms</td></tr>)}</tbody>
      </table></div> : <p role="status">Stage timings were not captured.</p>}
      <h3>Evidence lineage</h3>
      {execution.retrieval_lineage_status === "expired" ? <p role="status">Evidence details expired. Summary timings remain available until summary retention expires.</p> : null}
      {execution.retrieval_lineage_status === "truncated" ? <p role="status">Evidence details are truncated. Counts include candidates omitted from the retained rows.</p> : null}
      {!lineage?.stages?.length && execution.retrieval_lineage_status !== "expired" ? <p role="status">Evidence details were not captured or are unavailable.</p> : null}
      {lineage?.stages?.map((stage, index) => <details className="analytics-stage-detail" key={`${stage.name}:${stage.attempt}:${index}`}>
        <summary>{stage.name} · attempt {stage.attempt + 1} · {stage.status} · {stage.candidates.length} of {stage.candidate_count} candidates{stage.truncated ? " · truncated" : ""}</summary>
        <div className="analytics-table-wrap"><table className="analytics-table"><caption>{stage.name} candidate metadata</caption>
          <thead><tr><th scope="col">Rank</th><th scope="col">Document / chunk</th><th scope="col">Generation</th><th scope="col">Retrieval</th><th scope="col">Rerank</th><th scope="col">Adjusted</th></tr></thead>
          <tbody>{stage.candidates.map((candidate, row) => <tr key={`${candidate.candidate_key ?? candidate.point_id}:${row}`}>
            <td>{candidate.rank ?? "—"}</td><td>{candidate.doc_id ?? "Unknown document"}<small>{candidate.chunk_id ?? "Unknown chunk"}</small></td>
            <td>{candidate.index_generation_id ?? "Unavailable"}</td><td>{score(candidate.retrieval_score)}</td><td>{score(candidate.rerank_score)}</td><td>{score(candidate.rerank_adjusted_score)}</td>
          </tr>)}</tbody>
        </table></div>
      </details>)}
      {lineage?.generation ? <EvidenceMapping title="Sent to generation" sources={lineage.generation.source_keys} /> : null}
      {lineage?.citation ? <EvidenceMapping title="Cited evidence" sources={lineage.citation.cited_source_keys} /> : null}
      {ledger?.status === "captured" ? <><h3>Final claim ledger</h3><dl className="analytics-detail-grid">
        <Detail label="Applicable claims" value={ledger.applicable_claims} /><Detail label="Supported" value={ledger.supported_claims} />
        <Detail label="Unsupported" value={ledger.unsupported_claims} /><Detail label="Unknown" value={ledger.unknown_claims} /><Detail label="Cited" value={ledger.cited_claims} />
      </dl></> : null}
    </> : null}
  </section>;
}

function EvidenceMapping({ title, sources }: { title: string; sources?: AnalyticsEvidenceIdentity[] }) {
  return <><h3>{title}</h3>{sources?.length ? <ul>{sources.map((source, index) => <li key={index}>{source.doc_id ?? "Unknown document"} / {source.chunk_id ?? "Unknown chunk"} · generation {source.index_generation_id ?? "unavailable"}</li>)}</ul> : <p>No mapped evidence was retained.</p>}</>;
}

function Detail({ label, value }: { label: string; value?: string | number | null }) {
  return <div><dt>{label}</dt><dd>{value ?? "Unavailable"}</dd></div>;
}

function score(value?: number | null) { return value == null ? "Not measured" : value.toFixed(3); }

function detailError(error: Error) {
  if (error instanceof ApiClientError && error.status === 404) return "Execution history was deleted or has expired.";
  if (error instanceof ApiClientError && error.status === 403) return "You no longer have access to execution analytics.";
  return "Could not load execution details.";
}
