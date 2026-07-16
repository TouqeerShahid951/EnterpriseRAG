import { useEffect, useState, type CSSProperties } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ExternalLink, FileText, Loader2, XCircle } from "lucide-react";
import { documentsApi, reviewApi } from "@/lib/api/contracts";
import { DocumentRegionViewer } from "@/features/documents/components/DocumentRegionViewer";
import { useToast } from "@/components/feedback/ToastProvider";
import { InlineMessage, Skeleton } from "@/components/layout/Common";
import { ReviewFact, ReviewPlaceholder } from "@/features/review-queue/components/ReviewQueuePrimitives";
import {
  confidenceLabel,
  confidencePercent,
  confidencePillClass,
  itemTypeLabel,
  pageRange,
  qualityFlagLabel,
  qualitySummary,
  reviewRegionFromItem,
  type ReviewDocumentGroup,
} from "@/features/review-queue/utils/reviewQueueUtils";
import type { ReviewItem } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";

export function ReviewQueuePanel({
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
          <p className="sv-eyebrow">Queue</p>
          <h2 className="sv-section-title">Pending OCR Blocks</h2>
          <p>Prioritize low-confidence regions before indexing resumes.</p>
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
                      Page {pageRange(item)} | {qualitySummary(item)}
                    </span>
                    <span className="review-queue-item-excerpt">{item.partial_text}</span>
                  </span>
                  <ConfidenceMeter item={item} />
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ConfidenceMeter({ item }: { item: ReviewItem }) {
  const percent = confidencePercent(item);
  return (
    <span className="review-confidence-meter" aria-label={`Confidence ${confidenceLabel(item.confidence)}`}>
      <span className={confidencePillClass(item)}>{confidenceLabel(item.confidence)}</span>
      <span className="review-confidence-track" aria-hidden="true">
        <span style={{ width: `${percent}%` } as CSSProperties} />
      </span>
    </span>
  );
}

export function ReviewDocumentPreview({ item, previewMode }: { item: ReviewItem | null; previewMode: boolean }) {
  const region = item ? reviewRegionFromItem(item) : null;
  const initialPage = region?.page ?? item?.page_start ?? item?.page_end ?? 1;
  const fallbackMessage = region?.bbox
    ? "Exact source highlight is unavailable for this document."
    : "This review block does not include a page bounding box, so compare the OCR text against the visible page.";

  return (
    <section className="sv-card review-preview-panel" aria-label="Document page preview">
      <div className="review-panel-header">
        <div>
          <p className="sv-eyebrow">Evidence</p>
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
          <ReviewPlaceholder
            icon={<FileText aria-hidden="true" size={20} />}
            title="No page selected"
            text="Choose a pending OCR block to load its source page and region evidence."
          />
        ) : (
          previewMode ? (
            <ReviewDemoPage item={item} />
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
          )
        )}
      </div>
    </section>
  );
}

function ReviewDemoPage({ item }: { item: ReviewItem }) {
  return (
    <div className="review-demo-document" aria-label="Preview document page">
      <div className="review-demo-toolbar">
        <span>{item.doc_title}</span>
        <span>Page {pageRange(item)}</span>
      </div>
      <div className="review-demo-page">
        <div className="review-demo-line is-wide" />
        <div className="review-demo-line" />
        <div className="review-demo-line is-short" />
        <div className="review-demo-highlight">
          <span>{item.partial_text}</span>
        </div>
        <div className="review-demo-line is-wide" />
        <div className="review-demo-line" />
        <div className="review-demo-table">
          <span />
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  );
}

export function ReviewCorrectionPanel({ item, onReviewed, previewMode }: { item: ReviewItem | null; onReviewed: (itemId: string) => void; previewMode: boolean }) {
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
            <p className="sv-eyebrow">Decision</p>
            <h2 className="sv-section-title">Correction</h2>
            <p>No review item selected.</p>
          </div>
        </div>
        <ReviewPlaceholder
          icon={<CheckCircle2 aria-hidden="true" size={20} />}
          title="No correction active"
          text="The extraction editor appears after a queue item is selected."
        />
      </aside>
    );
  }

  const isMutating = approveMutation.isPending || rejectMutation.isPending;
  const canApprove = correctedText.trim().length > 0 && !isMutating && !previewMode;

  return (
    <aside className="sv-card review-correction-panel" aria-label="Correction panel">
      <div className="review-panel-header">
        <div>
          <p className="sv-eyebrow">Decision</p>
          <h2 className="sv-section-title">Correct Extraction</h2>
          <p>{itemTypeLabel(item.item_type)} #{item.item_index} from page {pageRange(item)}</p>
        </div>
        <span className={confidencePillClass(item)}>{confidenceLabel(item.confidence)}</span>
      </div>

      <div className="review-active-context">
        <FileText aria-hidden="true" size={15} />
        <span>{item.doc_title}</span>
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

      {previewMode ? <InlineMessage tone="warning">Preview only. Approval and rejection are disabled for the sample items.</InlineMessage> : null}

      <section className="review-original-text" aria-label="Original OCR text">
        <div className="review-subsection-header">
          <h3>Original OCR</h3>
          <span>{item.partial_text.length} chars</span>
        </div>
        <pre>{item.partial_text}</pre>
      </section>

      <label className="sv-field review-correction-field">
        <span className="review-field-header">
          <span className="sv-label">Corrected extraction text</span>
          <small>{correctedText.trim().length} chars</small>
        </span>
        <textarea
          value={correctedText}
          disabled={isMutating || previewMode}
          onChange={(event) => setCorrectedText(event.target.value)}
          rows={10}
          className="sv-textarea"
        />
        <small className="text-secondary">Edit only the extraction text that should be saved for this review block.</small>
      </label>

      <div className="review-actions">
        <button type="button" onClick={() => approveMutation.mutate()} disabled={!canApprove} className="sv-action-primary">
          {approveMutation.isPending ? <Loader2 aria-hidden="true" className="animate-spin" size={16} /> : <CheckCircle2 aria-hidden="true" size={16} />}
          {approveMutation.isPending ? "Saving" : "Approve correction"}
        </button>
        <button type="button" onClick={() => setCorrectedText(item.partial_text)} disabled={isMutating || previewMode} className="sv-action-secondary">
          Reset to OCR
        </button>
        <button type="button" onClick={() => rejectMutation.mutate()} disabled={isMutating || previewMode} className="sv-action-danger">
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
