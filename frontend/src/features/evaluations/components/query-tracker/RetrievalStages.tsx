import type { RetrievalStage, RetrievalStageCandidate, RetrievalStageName } from "@/types/api";
import { ChunkPreview } from "./ChunkPreview";

const STAGE_COPY: Record<RetrievalStageName, { label: string; detail: string }> = {
  retrieved: { label: "Vector retrieval", detail: "ABAC-filtered vector and hybrid recall" },
  rerank_input: { label: "Reranker input", detail: "Candidates admitted to the reranker" },
  reranked: { label: "Reranked", detail: "Candidates ordered by semantic relevance" },
  post_policy: { label: "Post-policy", detail: "Coverage and route policy applied" },
  final_evidence: { label: "Final evidence", detail: "Chunks sent to answer generation" },
};

export function RetrievalStages({ stages }: { stages: RetrievalStage[] }) {
  return (
    <div className="rag-eval-retrieval-stages">
      {stages.map((stage, index) => {
        const copy = STAGE_COPY[stage.name];
        return (
          <details className="rag-eval-retrieval-stage" key={`${stage.attempt}-${stage.name}`} open={index === stages.length - 1}>
            <summary>
              <span>
                <strong>{copy.label}</strong>
                <small>{copy.detail} / attempt {stage.attempt + 1}</small>
              </span>
              <span>{stage.status === "skipped" ? "Skipped" : `${stage.candidate_count} chunks`}</span>
            </summary>
            {stage.candidates.length ? (
              <div className="rag-eval-stage-candidates">
                {stage.candidates.map((candidate) => (
                  <article key={`${candidate.point_id}-${candidate.rank}`}>
                    <span className="rag-eval-candidate-rank">#{candidate.rank}</span>
                    <div>
                      <strong>{candidate.doc_title || candidate.doc_id || "Untitled source"}</strong>
                      <small>{candidateLocation(candidate)}</small>
                      <ChunkPreview chunkId={candidate.chunk_id} excerpt={candidate.excerpt} />
                    </div>
                    <small className="rag-eval-candidate-scores">{candidateScores(candidate)}</small>
                  </article>
                ))}
              </div>
            ) : (
              <p className="rag-eval-stage-empty">No candidates at this stage.</p>
            )}
          </details>
        );
      })}
    </div>
  );
}

function candidateLocation(candidate: RetrievalStageCandidate): string {
  const page = candidate.page_start ?? candidate.page ?? candidate.page_end;
  return [candidate.group_path, page ? `page ${page}` : null].filter(Boolean).join(" / ") || "Location unavailable";
}

function candidateScores(candidate: RetrievalStageCandidate): string {
  const scores = [`vector ${candidate.retrieval_score.toFixed(3)}`];
  if (candidate.rerank_score !== undefined) scores.push(`rerank ${candidate.rerank_score.toFixed(3)}`);
  if (candidate.rerank_adjusted_score !== undefined) scores.push(`adjusted ${candidate.rerank_adjusted_score.toFixed(3)}`);
  return scores.join(" / ");
}
