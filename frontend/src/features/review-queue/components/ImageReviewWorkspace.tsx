import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CheckSquare, FileText, ImageIcon, Loader2, Square, XCircle } from "lucide-react";
import { reviewApi } from "@/lib/api/contracts";
import { useToast } from "@/components/feedback/ToastProvider";
import { InlineMessage, Skeleton } from "@/components/layout/Common";
import { ReviewFact, ReviewPlaceholder } from "@/features/review-queue/components/ReviewQueuePrimitives";
import { candidateLabel, candidateQuality } from "@/features/review-queue/utils/reviewQueueUtils";
import type { ImageReviewBatch, ImageReviewCandidate } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";

export function ImageReviewWorkspace({
  batches,
  isLoading,
  previewMode,
}: {
  batches: ImageReviewBatch[];
  isLoading: boolean;
  previewMode: boolean;
}) {
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<Set<string>>(() => new Set());
  const selectedBatch = batches.find((batch) => batch.id === selectedBatchId) ?? batches[0] ?? null;
  const pendingCandidates = selectedBatch?.candidates.filter((candidate) => candidate.status === "pending") ?? [];
  const selectedPendingIds = pendingCandidates.filter((candidate) => selectedCandidateIds.has(candidate.id)).map((candidate) => candidate.id);
  const queryClient = useQueryClient();
  const { notify } = useToast();

  useEffect(() => {
    if (batches.length === 0) {
      if (selectedBatchId !== null) setSelectedBatchId(null);
      return;
    }
    if (!selectedBatchId || !batches.some((batch) => batch.id === selectedBatchId)) setSelectedBatchId(batches[0].id);
  }, [batches, selectedBatchId]);

  useEffect(() => {
    if (!selectedBatch) {
      setSelectedCandidateIds(new Set());
      return;
    }
    setSelectedCandidateIds(new Set(selectedBatch.candidates.filter((candidate) => candidate.status === "pending" && candidate.recommended).map((candidate) => candidate.id)));
  }, [selectedBatch?.id, selectedBatch?.pending_count, selectedBatch?.recommended_count]);

  const decisionMutation = useMutation({
    mutationFn: (request: Parameters<typeof reviewApi.decideImageBatch>[1]) => reviewApi.decideImageBatch(selectedBatch?.id ?? "", request),
    onSuccess: (response) => {
      void queryClient.invalidateQueries({ queryKey: ["review-queue", "image-batches"] });
      void queryClient.invalidateQueries({ queryKey: ["review-queue"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      notify({
        title: response.batch_complete ? "Image review complete" : "Image decisions saved",
        description: selectedBatch?.doc_title,
        tone: "success",
      });
    },
    onError: (error) => notify({
      title: "Image review failed",
      description: errorMessage(error, "Image review decision is not available yet."),
      tone: "error",
    }),
  });

  function toggleCandidate(candidate: ImageReviewCandidate) {
    if (candidate.status !== "pending" || previewMode) return;
    setSelectedCandidateIds((current) => {
      const next = new Set(current);
      if (next.has(candidate.id)) next.delete(candidate.id);
      else next.add(candidate.id);
      return next;
    });
  }

  function selectCandidates(mode: "recommended" | "all" | "none") {
    if (!selectedBatch) return;
    if (mode === "none") {
      setSelectedCandidateIds(new Set());
      return;
    }
    const next = selectedBatch.candidates.filter((candidate) => {
      if (candidate.status !== "pending") return false;
      return mode === "all" || candidate.recommended;
    });
    setSelectedCandidateIds(new Set(next.map((candidate) => candidate.id)));
  }

  function decide(request: Parameters<typeof reviewApi.decideImageBatch>[1]) {
    if (!selectedBatch || previewMode) return;
    decisionMutation.mutate(request);
  }

  const isMutating = decisionMutation.isPending;
  const canDecide = Boolean(selectedBatch) && !previewMode && !isMutating;

  return (
    <div className="review-layout review-image-layout" id="review-panel-images" role="tabpanel" aria-labelledby="review-tab-images" tabIndex={0}>
      <section className="sv-card review-image-batch-panel" aria-label="PDF image review batches">
        <div className="review-panel-header">
          <div>
            <p className="sv-eyebrow">Queue</p>
            <h2 className="sv-section-title">PDF Image Batches</h2>
            <p>Choose a held document image queue.</p>
          </div>
          <span className="sv-pill">{isLoading ? "Loading" : `${batches.length} batches`}</span>
        </div>
        <div className="review-queue-list" role="list">
          {isLoading ? (
            <div className="review-queue-skeleton" role="status">
              <span className="sr-only">Loading image review batches.</span>
              {Array.from({ length: 4 }, (_, index) => (
                <div className="review-skeleton-row" key={index} aria-hidden="true">
                  <Skeleton className="h-4 w-3/5" />
                  <Skeleton className="h-3 w-4/5" />
                </div>
              ))}
            </div>
          ) : null}
          {!isLoading && batches.map((batch) => (
            <button
              key={batch.id}
              type="button"
              aria-current={selectedBatch?.id === batch.id ? "true" : undefined}
              onClick={() => setSelectedBatchId(batch.id)}
              className="review-image-batch-item"
            >
              <span>
                <FileText aria-hidden="true" size={15} />
                <strong>{batch.doc_title}</strong>
              </span>
              <small>{batch.pending_count} pending | {batch.approved_count} analyze | {batch.skipped_count} skipped</small>
            </button>
          ))}
        </div>
      </section>

      <section className="sv-card review-image-grid-panel" aria-label="PDF image candidates">
        <div className="review-panel-header">
          <div>
            <p className="sv-eyebrow">Candidates</p>
            <h2 className="sv-section-title">{selectedBatch ? selectedBatch.doc_title : "No batch selected"}</h2>
            <p>{selectedBatch ? `${selectedBatch.candidate_count} images selected by the parser` : "Select a batch to review candidate images."}</p>
          </div>
          <span className="sv-pill">{selectedPendingIds.length} selected</span>
        </div>
        <div className="review-image-grid-toolbar">
          <button type="button" onClick={() => selectCandidates("recommended")} disabled={!selectedBatch || previewMode} className="sv-action-secondary">
            <CheckSquare aria-hidden="true" size={15} />
            Recommended
          </button>
          <button type="button" onClick={() => selectCandidates("all")} disabled={!selectedBatch || previewMode} className="sv-action-secondary">
            <CheckSquare aria-hidden="true" size={15} />
            All pending
          </button>
          <button type="button" onClick={() => selectCandidates("none")} disabled={!selectedBatch || previewMode} className="sv-action-secondary">
            <Square aria-hidden="true" size={15} />
            Clear
          </button>
        </div>
        <div className="review-image-grid" role="list">
          {selectedBatch?.candidates.map((candidate) => (
            <label key={candidate.id} className="review-image-candidate" data-selected={selectedCandidateIds.has(candidate.id) ? "true" : undefined} data-status={candidate.status}>
              <input
                type="checkbox"
                checked={selectedCandidateIds.has(candidate.id)}
                disabled={candidate.status !== "pending" || previewMode}
                onChange={() => toggleCandidate(candidate)}
              />
              <span className="review-image-thumb">
                <img src={reviewApi.imageCandidateContentUrl(candidate.content_url)} alt={candidateLabel(candidate)} loading="lazy" />
              </span>
              <span className="review-image-candidate-copy">
                <strong>{candidateLabel(candidate)}</strong>
                <small>{candidateQuality(candidate)}</small>
              </span>
              <span className="review-image-status-row">
                {candidate.recommended ? <span className="sv-pill sv-pill-success">Recommended</span> : null}
                <span className="sv-pill">{candidate.status}</span>
              </span>
            </label>
          ))}
          {!isLoading && !selectedBatch ? (
            <ReviewPlaceholder
              icon={<ImageIcon aria-hidden="true" size={20} />}
              title="No image batch selected"
              text="PDF image batches that need reviewer triage appear here before vision analysis runs."
            />
          ) : null}
        </div>
      </section>

      <aside className="sv-card review-image-decision-panel" aria-label="PDF image review decisions">
        <div className="review-panel-header">
          <div>
            <p className="sv-eyebrow">Decision</p>
            <h2 className="sv-section-title">Analyze or Skip</h2>
            <p>{selectedBatch ? `${selectedPendingIds.length} selected from ${selectedBatch.pending_count} pending` : "No batch selected."}</p>
          </div>
        </div>
        {previewMode ? <InlineMessage tone="warning">Preview only. Image review actions are disabled for sample OCR items.</InlineMessage> : null}
        <dl className="review-facts">
          <ReviewFact label="Pending" value={String(selectedBatch?.pending_count ?? 0)} />
          <ReviewFact label="Selected" value={String(selectedPendingIds.length)} />
          <ReviewFact label="Analyze" value={String(selectedBatch?.approved_count ?? 0)} />
          <ReviewFact label="Skipped" value={String(selectedBatch?.skipped_count ?? 0)} />
        </dl>
        <div className="review-actions">
          <button
            type="button"
            onClick={() => decide({ approve_candidate_ids: selectedPendingIds, skip_remaining: true })}
            disabled={!canDecide || selectedPendingIds.length === 0}
            className="sv-action-primary"
          >
            {isMutating ? <Loader2 aria-hidden="true" className="animate-spin" size={16} /> : <CheckCircle2 aria-hidden="true" size={16} />}
            Analyze selected
          </button>
          <button type="button" onClick={() => decide({ approve_recommended: true, skip_remaining: true })} disabled={!canDecide} className="sv-action-secondary">
            <CheckSquare aria-hidden="true" size={16} />
            Analyze recommended
          </button>
          <button
            type="button"
            onClick={() => decide({ skip_candidate_ids: selectedPendingIds })}
            disabled={!canDecide || selectedPendingIds.length === 0}
            className="sv-action-secondary"
          >
            <XCircle aria-hidden="true" size={16} />
            Skip selected
          </button>
          <button type="button" onClick={() => decide({ skip_remaining: true })} disabled={!canDecide || pendingCandidates.length === 0} className="sv-action-danger">
            <XCircle aria-hidden="true" size={16} />
            Skip all pending
          </button>
        </div>
        <p className="review-helper-text" role="status">
          <AlertTriangle aria-hidden="true" size={14} />
          The job resumes when no candidates remain pending.
        </p>
      </aside>
    </div>
  );
}
