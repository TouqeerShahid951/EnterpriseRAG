import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Database,
  FileText,
  ListFilter,
  Quote,
  Search,
  ShieldCheck,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import type { EvaluationCaseResult } from "../../types/api";

type JsonRecord = Record<string, unknown>;
type StageState = "passed" | "failed" | "warning" | "pending";

type CandidateRow = {
  rank: number;
  docTitle: string;
  docId: string;
  chunkId: string;
  pageLabel: string;
  retrievalScore: number | null;
  rerankScore: number | null;
  rerankStatus: string;
  rerankError: string;
  chunkType: string;
  structuredOrigin: string;
};

export function RagEvaluationDiagnostics({ result }: { result: EvaluationCaseResult }) {
  const checks = asRecord(result.checks);
  const diagnostic = asRecord(result.diagnostic);
  const retrievalRows = candidateRows(diagnostic, ["retrieval_candidates", "retrieved_candidates", "hits"]);
  const rerankedRows = candidateRows(diagnostic, ["reranked_candidates", "rerank_candidates", "reranked_hits"]);
  const finalRows = finalSourceRows(result);
  const fallbackCount = [...retrievalRows, ...rerankedRows, ...finalRows].filter((row) => row.rerankStatus === "fallback" || row.rerankError).length;
  const stages = pipelineStages(checks, fallbackCount, rerankedRows.length);

  return (
    <section className="rag-eval-diagnostics" aria-label="RAG evaluation pipeline diagnostics">
      <div className="rag-eval-pipeline" role="list" aria-label="Pipeline status">
        {stages.map((stage) => (
          <PipelineStage key={stage.id} stage={stage} />
        ))}
      </div>

      <EvidenceCoverage checks={checks} diagnostic={diagnostic} fallbackCount={fallbackCount} />

      <div className="rag-eval-candidate-grid">
        <CandidateTable title="Retrieved Candidates" detail="Hybrid retrieval before reranking" rows={retrievalRows} />
        <CandidateTable title="Reranked Candidates" detail="Cross-encoder output when available" rows={rerankedRows} empty="Reranked candidates are not recorded by the backend yet." />
        <CandidateTable title="Final Sources" detail="Evidence cited or available to the answer" rows={finalRows} empty="No final answer sources." />
      </div>
    </section>
  );
}

function PipelineStage({ stage }: { stage: Stage }) {
  const StateIcon = stateIcon(stage.state);
  const StageIcon = stage.icon;
  return (
    <article className="rag-eval-pipeline-stage" data-state={stage.state} role="listitem">
      <span className="rag-eval-stage-icon"><StageIcon size={16} aria-hidden="true" /></span>
      <span>
        <strong>{stage.label}</strong>
        <small>{stage.detail}</small>
      </span>
      <StateIcon className="rag-eval-stage-state-icon" size={16} aria-hidden="true" />
    </article>
  );
}

function EvidenceCoverage({ checks, diagnostic, fallbackCount }: { checks: JsonRecord; diagnostic: JsonRecord; fallbackCount: number }) {
  const ingestion = asRecord(checks.ingestion_indexing);
  const retrieval = asRecord(checks.retrieval);
  const finalSources = asRecord(checks.final_sources);
  const expectedDocs = stringList(retrieval.expected_source_docs).length ? stringList(retrieval.expected_source_docs) : stringList(ingestion.expected_source_docs);
  const indexedDocs = stringList(ingestion.indexed_source_docs);
  const retrievedDocs = stringList(diagnostic.retrieved_source_docs).length ? stringList(diagnostic.retrieved_source_docs) : stringList(retrieval.retrieved_source_docs);
  const rerankedDocs = stringList(diagnostic.reranked_source_docs);
  const finalDocs = stringList(finalSources.source_doc_titles);
  const expectedPages = numberList(retrieval.acceptable_source_pages);
  const retrievedPages = numberList(diagnostic.retrieved_pages).length ? numberList(diagnostic.retrieved_pages) : numberList(retrieval.retrieved_pages);

  return (
    <section className="rag-eval-coverage-panel" aria-label="Expected evidence coverage">
      <div className="rag-eval-diagnostic-section-header">
        <div>
          <h4>Evidence coverage</h4>
          <p>Expected evidence compared with indexed, retrieved, and final sources.</p>
        </div>
      </div>
      <dl className="rag-eval-coverage-grid">
        <CoverageListItem label="Expected docs" values={expectedDocs} />
        <CoverageListItem label="Indexed" values={indexedDocs} state={stateFromCheck(ingestion)} />
        <CoverageListItem label="Retrieved" values={retrievedDocs} state={stateFromCheck(retrieval)} />
        <CoverageListItem label="Reranked" values={rerankedDocs} empty="Not recorded" state={rerankedDocs.length ? "passed" : "pending"} />
        <CoverageListItem label="Final sources" values={finalDocs} state={stateFromCheck(finalSources)} />
        <CoverageListItem label="Pages" values={retrievedPages.map(String)} detail={expectedPages.length ? `Expected ${listText(expectedPages)}` : null} />
        <CoverageItem label="Fallbacks" value={fallbackCount ? `${fallbackCount} candidate${fallbackCount === 1 ? "" : "s"}` : "None"} state={fallbackCount ? "warning" : "passed"} />
      </dl>
    </section>
  );
}

function CoverageListItem({ detail, empty = "None", label, state, values }: { detail?: string | null; empty?: string; label: string; state?: StageState; values: Array<string | number> }) {
  const summary = summarizeRepeatedValues(values);
  return (
    <div className="rag-eval-coverage-item" data-state={state ?? "pending"}>
      <dt>{label}</dt>
      <dd>
        {summary.items.length ? (
          <span className="rag-eval-coverage-values">
            {summary.items.map((item) => (
              <span key={item.value} className="rag-eval-coverage-value" title={item.value}>
                <span>{item.value}</span>
                {item.count > 1 ? <strong>x{item.count}</strong> : null}
              </span>
            ))}
            {summary.hiddenCount ? <span className="rag-eval-coverage-more">+{summary.hiddenCount} more</span> : null}
          </span>
        ) : (
          <span className="rag-eval-coverage-empty">{empty}</span>
        )}
        {detail ? <small>{detail}</small> : null}
      </dd>
    </div>
  );
}

function CoverageItem({ label, state, value }: { label: string; state?: StageState; value: string }) {
  return (
    <div className="rag-eval-coverage-item" data-state={state ?? "pending"}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function CandidateTable({ detail, empty = "No candidates recorded.", rows, title }: { detail: string; empty?: string; rows: CandidateRow[]; title: string }) {
  return (
    <section className="rag-eval-candidate-panel">
      <div className="rag-eval-candidate-header">
        <div>
          <h4>{title}</h4>
          <p>{detail}</p>
        </div>
        <span className="sv-pill">{rows.length}</span>
      </div>
      {rows.length === 0 ? <p className="rag-eval-empty-candidates">{empty}</p> : null}
      {rows.length > 0 ? (
        <div className="rag-eval-candidate-table-wrap">
          <table className="rag-eval-candidate-table">
            <thead>
              <tr>
                <th scope="col">Rank</th>
                <th scope="col">Document</th>
                <th scope="col">Chunk</th>
                <th scope="col">Page</th>
                <th scope="col">Retrieval</th>
                <th scope="col">Rerank</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.rank}-${row.docId}-${row.chunkId}`}>
                  <td>{row.rank}</td>
                  <td>
                    <strong title={row.docTitle}>{row.docTitle}</strong>
                    <small title={row.docId}>{compactIdentifier(row.docId)}</small>
                  </td>
                  <td>
                    <span title={row.chunkId}>{compactIdentifier(row.chunkId)}</span>
                    <small>{[row.chunkType, row.structuredOrigin].filter(Boolean).join(" / ") || "text"}</small>
                  </td>
                  <td>{row.pageLabel}</td>
                  <td>{scoreLabel(row.retrievalScore)}</td>
                  <td>{scoreLabel(row.rerankScore)}</td>
                  <td>
                    <span className="rag-eval-rerank-status" data-status={row.rerankStatus || "unknown"}>{row.rerankStatus || "unrecorded"}</span>
                    {row.rerankError ? <small>{row.rerankError}</small> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function pipelineStages(checks: JsonRecord, fallbackCount: number, rerankedCount: number): Stage[] {
  const reranking = asRecord(checks.reranking_source_selection);
  return [
    stage("dataset", "Dataset", Database, stateFromCheck(asRecord(checks.dataset)), "Case contract and expectations"),
    stage("indexing", "Indexing", FileText, stateFromCheck(asRecord(checks.ingestion_indexing)), "Expected evidence in corpus"),
    stage("retrieval", "Retrieval", Search, stateFromCheck(asRecord(checks.retrieval)), "Hybrid candidates found"),
    stage(
      "reranking",
      "Reranking",
      ListFilter,
      fallbackCount ? "warning" : stateFromCheck(reranking, rerankedCount ? "passed" : "pending"),
      fallbackCount ? "Fallback used" : rerankedCount ? "Reranked candidates recorded" : "Awaiting rerank diagnostics",
    ),
    stage("sources", "Sources", Quote, stateFromCheck(asRecord(checks.final_sources)), "Final evidence selected"),
    stage("answer", "Answer", CheckCircle2, stateFromCheck(asRecord(checks.answer_content)), "Required answer checks"),
    stage("faithfulness", "Faithfulness", ShieldCheck, stateFromCheck(asRecord(checks.faithfulness)), "Support threshold and claims"),
  ];
}

function stage(id: string, label: string, icon: LucideIcon, state: StageState, detail: string): Stage {
  return { id, label, icon, state, detail };
}

function candidateRows(diagnostic: JsonRecord, keys: string[]): CandidateRow[] {
  for (const key of keys) {
    const rows = recordList(diagnostic[key]);
    if (rows.length) return rows.map(candidateRow);
  }
  return [];
}

function finalSourceRows(result: EvaluationCaseResult): CandidateRow[] {
  return result.sources.map((source, index) => candidateRow(asRecord(source), index));
}

function candidateRow(row: JsonRecord, index = 0): CandidateRow {
  return {
    rank: numberValue(row.rank) ?? index + 1,
    docTitle: stringValue(row.doc_title) || stringValue(row.document_title) || "Untitled",
    docId: stringValue(row.doc_id) || "unknown",
    chunkId: stringValue(row.chunk_id) || "unknown",
    pageLabel: pageLabel(row),
    retrievalScore: numberValue(row.retrieval_score) ?? numberValue(row.score),
    rerankScore: numberValue(row.rerank_score),
    rerankStatus: stringValue(row.rerank_status),
    rerankError: stringValue(row.rerank_error),
    chunkType: stringValue(row.chunk_type) || stringValue(row.attribution_kind),
    structuredOrigin: stringValue(row.structured_origin),
  };
}

function stateFromCheck(check: JsonRecord, fallback: StageState = "pending"): StageState {
  if (check.passed === true) return "passed";
  if (check.passed === false) return "failed";
  return fallback;
}

function stateIcon(state: StageState): LucideIcon {
  if (state === "passed") return CheckCircle2;
  if (state === "failed") return XCircle;
  if (state === "warning") return AlertTriangle;
  return CircleDashed;
}

function pageLabel(row: JsonRecord): string {
  const page = numberValue(row.page);
  const start = numberValue(row.page_start) ?? page;
  const end = numberValue(row.page_end) ?? start;
  if (start === null) return "unknown";
  return end !== null && end !== start ? `${start}-${end}` : String(start);
}

function scoreLabel(value: number | null): string {
  if (value === null) return "n/a";
  return Math.abs(value) < 10 ? value.toFixed(3) : value.toFixed(1);
}

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : {};
}

function recordList(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(asRecord).filter((row) => Object.keys(row).length > 0) : [];
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item).trim()).filter(Boolean) : [];
}

function numberList(value: unknown): number[] {
  return Array.isArray(value) ? value.map(numberValue).filter((item): item is number => item !== null) : [];
}

function stringValue(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
  return null;
}

export function summarizeRepeatedValues(values: Array<string | number>, limit = 4): { hiddenCount: number; items: Array<{ value: string; count: number }> } {
  const counts = new Map<string, number>();
  for (const value of values) {
    const normalized = String(value).trim();
    if (!normalized) continue;
    counts.set(normalized, (counts.get(normalized) ?? 0) + 1);
  }
  const items = Array.from(counts, ([value, count]) => ({ value, count })).sort((left, right) => right.count - left.count || left.value.localeCompare(right.value));
  return { hiddenCount: Math.max(0, items.length - limit), items: items.slice(0, limit) };
}

function listText(items: string[] | number[]): string {
  return items.length ? items.join(", ") : "None";
}

function compactIdentifier(value: string): string {
  return value.length > 30 ? `${value.slice(0, 14)}...${value.slice(-10)}` : value;
}

type Stage = {
  id: string;
  label: string;
  icon: LucideIcon;
  state: StageState;
  detail: string;
};
