import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ExternalLink, FileText, Loader2, XCircle } from "lucide-react";

import { reviewApi, documentsApi } from "../api/contracts";
import { DocumentRegionViewer, type DocumentRegion } from "../components/document/DocumentRegionViewer";
import { useToast } from "../components/feedback/ToastProvider";
import { EmptyPanel, InlineMessage, Skeleton } from "../components/layout/Common";
import { FahamWorkspace } from "../components/layout/FahamWorkspace";
import type { RouteId } from "../routes";
import type { ReviewItem, User as AuthUser } from "../types/api";
import { errorMessage } from "../utils/format";

export function FahamReviewQueuePage({ onLogout, onNavigate, user }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const reviewQuery = useQuery({ queryKey: ["review-queue"], queryFn: reviewApi.list, retry: false });
  const items = reviewQuery.data?.items ?? [];
  const groups = useMemo(() => groupReviewItemsByDocument(items), [items]);
  const selected = items.find((item) => item.id === selectedId) ?? items[0] ?? null;

  useEffect(() => {
    if (items.length === 0) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!selectedId || !items.some((item) => item.id === selectedId)) setSelectedId(items[0].id);
  }, [items, selectedId]);

  function handleReviewed(reviewedId: string) {
    const reviewedIndex = items.findIndex((item) => item.id === reviewedId);
    const nextItem = reviewedIndex >= 0 ? items[reviewedIndex + 1] ?? items[reviewedIndex - 1] ?? null : items[0] ?? null;
    setSelectedId(nextItem?.id ?? null);
  }

  return (
    <FahamWorkspace activeRoute="review" onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page review-workspace" id="main-content">
        <div className="sv-page-inner review-page-inner">
          <header className="sv-page-header review-page-header">
            <div>
              <p className="sv-eyebrow">Faham AI</p>
              <h1 className="sv-page-title">OCR Review</h1>
              <p className="sv-page-subtitle">Resolve low-confidence extraction blocks before the document is indexed for grounded answers.</p>
            </div>
            <div className="review-summary" aria-label="Review queue summary">
              <ReviewSummaryMetric label="Pending blocks" value={String(items.length)} loading={reviewQuery.isLoading} />
              <ReviewSummaryMetric label="Documents" value={String(groups.length)} loading={reviewQuery.isLoading} />
              <ReviewSummaryMetric label="Lowest confidence" value={lowestConfidenceLabel(items)} loading={reviewQuery.isLoading} />
            </div>
          </header>

          {reviewQuery.isError ? <InlineMessage tone="error">{errorMessage(reviewQuery.error, "Unable to load review queue.")}</InlineMessage> : null}

          <div className="review-layout">
            <ReviewQueuePanel
              groups={groups}
              isLoading={reviewQuery.isLoading}
              onSelect={setSelectedId}
              selectedId={selected?.id ?? null}
            />
            <ReviewDocumentPreview item={selected} />
            <ReviewCorrectionPanel item={selected} onReviewed={handleReviewed} />
          </div>
        </div>
      </main>
    </FahamWorkspace>
  );
}

function ReviewSummaryMetric({ label, loading, value }: { label: string; loading: boolean; value: string }) {
  return (
    <div className="review-summary-metric" aria-busy={loading} data-cursor-glow>
      <span>{label}</span>
      {loading ? (
        <>
          <span className="sr-only">Loading {label.toLowerCase()}</span>
          <Skeleton className="mt-1 h-5 w-12" />
        </>
      ) : <strong>{value}</strong>}
    </div>
  );
}

function ReviewQueuePanel({
  groups,
  isLoading,
  onSelect,
  selectedId,
}: {
  groups: ReviewDocumentGroup[];
  isLoading: boolean;
  onSelect: (itemId: string) => void;
  selectedId: string | null;
}) {
  return (
    <section className="sv-card review-queue-panel" aria-label="Review queue">
      <div className="review-panel-header">
        <div>
          <h2 className="sv-section-title">Pending OCR Blocks</h2>
          <p>Choose a block to inspect its page region.</p>
        </div>
        <span className="sv-pill">{isLoading ? "Loading" : `${groups.reduce((count, group) => count + group.items.length, 0)} pending`}</span>
      </div>

      <div className="review-queue-list" role="list">
        {isLoading ? (
          <div className="review-queue-skeleton" role="status">
            <span className="sr-only">Loading review queue.</span>
            {Array.from({ length: 4 }, (_, index) => (
              <div className="review-skeleton-row" key={index} aria-hidden="true">
                <Skeleton className="h-4 w-2/5" />
                <Skeleton className="h-3 w-4/5" />
                <Skeleton className="h-3 w-1/2" />
              </div>
            ))}
          </div>
        ) : null}

        {!isLoading && groups.length === 0 ? (
          <div className="review-empty-state">
            <CheckCircle2 aria-hidden="true" size={24} />
            <h3>No OCR blocks need review</h3>
            <p>Documents with low-confidence OCR will appear here with page and region context before indexing resumes.</p>
          </div>
        ) : null}

        {groups.map((group) => (
          <div key={group.docId} className="review-doc-group" role="listitem">
            <div className="review-doc-group-header">
              <FileText aria-hidden="true" size={15} />
              <span>{group.docTitle}</span>
              <strong>{group.items.length}</strong>
            </div>
            <div className="review-doc-items">
              {group.items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-current={selectedId === item.id ? "true" : undefined}
                  onClick={() => onSelect(item.id)}
                  className="review-queue-item"
                >
                  <span className="review-queue-item-main">
                    <span className="review-queue-item-title">
                      {itemTypeLabel(item.item_type)} #{item.item_index}
                    </span>
                    <span className="review-queue-item-meta">
                      Page {pageRange(item)} / {qualitySummary(item)}
                    </span>
                    <span className="review-queue-item-excerpt">{item.partial_text}</span>
                  </span>
                  <span className={confidencePillClass(item)}>{confidenceLabel(item.confidence)}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ReviewDocumentPreview({ item }: { item: ReviewItem | null }) {
  const region = item ? reviewRegionFromItem(item) : null;
  const initialPage = region?.page ?? item?.page_start ?? item?.page_end ?? 1;
  const fallbackMessage = region?.bbox
    ? "Exact source highlight is unavailable for this document."
    : "This review block does not include a page bounding box, so compare the OCR text against the visible page.";

  return (
    <section className="sv-card review-preview-panel" aria-label="Document page preview">
      <div className="review-panel-header">
        <div>
          <h2 className="sv-section-title">Document Page</h2>
          <p>{item ? `${item.doc_title}, page ${pageRange(item)}` : "Select a block to open its source page."}</p>
        </div>
        {item ? (
          <a href={documentsApi.contentUrl(item.doc_id)} target="_blank" rel="noreferrer" className="sv-action-secondary review-open-original">
            <ExternalLink aria-hidden="true" size={15} />
            Original
          </a>
        ) : null}
      </div>

      <div className="review-preview-body">
        {!item ? (
          <EmptyPanel>Select a queue item to see the affected document page and OCR region.</EmptyPanel>
        ) : (
          <DocumentRegionViewer
            key={item.id}
            documentId={item.doc_id}
            documentTitle={item.doc_title}
            fallbackMessage={fallbackMessage}
            initialPage={initialPage}
            regions={region ? [region] : []}
            textCandidates={[item.partial_text]}
            toolbarEnd={<span className={confidencePillClass(item)}>{confidenceLabel(item.confidence)}</span>}
          />
        )}
      </div>
    </section>
  );
}

function ReviewCorrectionPanel({ item, onReviewed }: { item: ReviewItem | null; onReviewed: (itemId: string) => void }) {
  const [correctedText, setCorrectedText] = useState("");
  const queryClient = useQueryClient();
  const { notify } = useToast();

  useEffect(() => setCorrectedText(item?.corrected_text ?? item?.partial_text ?? ""), [item?.id, item?.corrected_text, item?.partial_text]);

  const approveMutation = useMutation({
    mutationFn: () => reviewApi.approve(item?.id ?? "", correctedText.trim()),
    onSuccess: (_response, _variables, _context) => {
      if (item) onReviewed(item.id);
      void queryClient.invalidateQueries({ queryKey: ["review-queue"] });
      notify({ title: "Correction approved", description: item?.doc_title, tone: "success" });
    },
    onError: (error) => notify({
      title: "Review approval failed",
      description: errorMessage(error, "Review approval is not available yet."),
      tone: "error",
    }),
  });
  const rejectMutation = useMutation({
    mutationFn: () => reviewApi.reject(item?.id ?? ""),
    onSuccess: () => {
      if (item) onReviewed(item.id);
      void queryClient.invalidateQueries({ queryKey: ["review-queue"] });
      notify({ title: "Review block rejected", description: item?.doc_title, tone: "success" });
    },
    onError: (error) => notify({
      title: "Review rejection failed",
      description: errorMessage(error, "Review rejection is not available yet."),
      tone: "error",
    }),
  });

  if (!item) {
    return (
      <aside className="sv-card review-correction-panel" aria-label="Correction panel">
        <div className="review-panel-header">
          <div>
            <h2 className="sv-section-title">Correction</h2>
            <p>No review item selected.</p>
          </div>
        </div>
        <EmptyPanel>The corrected extraction editor appears after you choose a queue item.</EmptyPanel>
      </aside>
    );
  }

  const isMutating = approveMutation.isPending || rejectMutation.isPending;
  const canApprove = correctedText.trim().length > 0 && !isMutating;

  return (
    <aside className="sv-card review-correction-panel" aria-label="Correction panel">
      <div className="review-panel-header">
        <div>
          <p className="sv-eyebrow">Evaluator</p>
          <h2 className="sv-section-title">Correct Extraction</h2>
        </div>
        <span className={confidencePillClass(item)}>{confidenceLabel(item.confidence)}</span>
      </div>

      <dl className="review-facts">
        <ReviewFact label="Document" value={item.doc_title} />
        <ReviewFact label="Block" value={`${itemTypeLabel(item.item_type)} #${item.item_index}`} />
        <ReviewFact label="Pages" value={pageRange(item)} />
        <ReviewFact label="Assigned" value={item.assigned_to ?? "Unassigned"} />
      </dl>

      {item.quality_flags.length > 0 ? (
        <div className="review-flags" aria-label="Extraction quality flags">
          {item.quality_flags.map((flag) => (
            <span key={flag} className="sv-pill knowledge-status-human_review">
              {qualityFlagLabel(flag)}
            </span>
          ))}
        </div>
      ) : (
        <InlineMessage tone="warning">No OCR quality flags were provided for this review block.</InlineMessage>
      )}

      <section className="review-original-text" aria-label="Original OCR text">
        <div className="review-subsection-header">
          <h3>Original OCR</h3>
          <span>{item.partial_text.length} chars</span>
        </div>
        <pre>{item.partial_text}</pre>
      </section>

      <label className="sv-field review-correction-field">
        <span className="sv-label">Corrected extraction text</span>
        <textarea
          value={correctedText}
          disabled={isMutating}
          onChange={(event) => setCorrectedText(event.target.value)}
          rows={10}
          className="sv-textarea"
        />
      </label>

      <div className="review-actions">
        <button type="button" onClick={() => approveMutation.mutate()} disabled={!canApprove} className="sv-action-primary">
          {approveMutation.isPending ? <Loader2 aria-hidden="true" className="animate-spin" size={16} /> : <CheckCircle2 aria-hidden="true" size={16} />}
          {approveMutation.isPending ? "Saving" : "Approve correction"}
        </button>
        <button type="button" onClick={() => rejectMutation.mutate()} disabled={isMutating} className="sv-action-danger">
          {rejectMutation.isPending ? <Loader2 aria-hidden="true" className="animate-spin" size={16} /> : <XCircle aria-hidden="true" size={16} />}
          Reject block
        </button>
      </div>

      {!correctedText.trim() ? (
        <p className="review-helper-text" role="status">
          <AlertTriangle aria-hidden="true" size={14} />
          Corrected text is required before approval.
        </p>
      ) : null}
    </aside>
  );
}

function ReviewFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function reviewRegionFromItem(item: ReviewItem): DocumentRegion {
  return {
    bbox: normalizeBBox(item.bbox),
    confidence: item.confidence,
    page: item.page_start ?? item.page_end,
    regionType: item.item_type,
    text: item.partial_text,
  };
}

export function groupReviewItemsByDocument(items: ReviewItem[]): ReviewDocumentGroup[] {
  const groups = new Map<string, ReviewDocumentGroup>();
  for (const item of items) {
    const group = groups.get(item.doc_id) ?? { docId: item.doc_id, docTitle: item.doc_title, items: [] };
    group.items.push(item);
    groups.set(item.doc_id, group);
  }
  return [...groups.values()];
}

function normalizeBBox(value: number[] | null): [number, number, number, number] | null {
  if (!value || value.length !== 4 || !value.every(Number.isFinite)) return null;
  const [x0, y0, x1, y1] = value;
  if (x1 <= x0 || y1 <= y0) return null;
  return [x0, y0, x1, y1];
}

function confidenceLabel(confidence: number | null): string {
  if (confidence === null) return "Missing confidence";
  return `${Math.round(confidence * 100)}%`;
}

function confidencePillClass(item: ReviewItem): string {
  if (item.confidence === null || item.confidence < 0.8) return "sv-pill sv-pill-warning";
  return "sv-pill sv-pill-success";
}

function lowestConfidenceLabel(items: ReviewItem[]): string {
  const confidences = items.map((item) => item.confidence).filter((confidence): confidence is number => confidence !== null);
  if (items.length === 0) return "None";
  if (confidences.length === 0) return "Missing";
  return `${Math.round(Math.min(...confidences) * 100)}%`;
}

function pageRange(item: ReviewItem): string {
  if (!item.page_start) return "Unknown";
  if (!item.page_end || item.page_end === item.page_start) return String(item.page_start);
  return `${item.page_start}-${item.page_end}`;
}

function itemTypeLabel(value: string): string {
  if (!value) return "Block";
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function qualityFlagLabel(value: string): string {
  return value.replace(/^source:/, "").replace(/[_-]+/g, " ");
}

function qualitySummary(item: ReviewItem): string {
  if (item.quality_flags.length === 0) return "No flags";
  return item.quality_flags.slice(0, 2).map(qualityFlagLabel).join(", ");
}

interface ReviewDocumentGroup {
  docId: string;
  docTitle: string;
  items: ReviewItem[];
}

type Props = { onLogout: () => void; onNavigate: (route: RouteId) => void; user: AuthUser };
