import { useEffect, useRef, useState, type CSSProperties, type UIEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ExternalLink, FileText, Loader2, RotateCcw, X, XCircle } from "lucide-react";
import { documentsApi, reviewApi } from "@/lib/api/contracts";
import { DocumentRegionViewer } from "@/features/documents/components/DocumentRegionViewer";
import { useToast } from "@/components/feedback/ToastProvider";
import { InlineMessage, Skeleton } from "@/components/layout/Common";
import { ReviewPlaceholder } from "@/features/review-queue/components/ReviewQueuePrimitives";
import {
  confidenceLabel,
  confidencePercent,
  confidencePillClass,
  itemTypeLabel,
  pageRange,
  qualitySummary,
  proportionalScrollTop,
  reviewRegionFromItem,
  type ReviewDocumentGroup,
} from "@/features/review-queue/utils/reviewQueueUtils";
import type { ReviewItem } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";

export function ReviewQueuePanel({
  disabled,
  groups,
  isLoading,
  onClose,
  onSelect,
  onSelectAll,
  onSelectGroup,
  panelId,
  selectedId,
  selectedItemIds,
}: {
  disabled: boolean;
  groups: ReviewDocumentGroup[];
  isLoading: boolean;
  onClose?: () => void;
  onSelect: (itemId: string) => void;
  onSelectAll: (selected: boolean) => void;
  onSelectGroup: (itemIds: string[], selected: boolean) => void;
  panelId?: string;
  selectedId: string | null;
  selectedItemIds: ReadonlySet<string>;
}) {
  const itemCount = groups.reduce((count, group) => count + group.items.length, 0);
  const selectedCount = groups.reduce(
    (count, group) => count + group.items.filter((item) => selectedItemIds.has(item.id)).length,
    0,
  );

  return (
    <section className="sv-card review-queue-panel" aria-label="Review queue" id={panelId}>
      <div className="review-panel-header">
        <div>
          <p className="sv-eyebrow">Queue</p>
          <h2 className="sv-section-title">Pending OCR Blocks</h2>
          <p>Prioritize low-confidence regions before indexing resumes.</p>
        </div>
        <div className="review-queue-header-actions">
          {!isLoading && itemCount > 0 ? (
            <label className="review-select-all">
              <SelectionCheckbox
                aria-label="Select all pending OCR blocks"
                checked={selectedCount === itemCount}
                disabled={disabled}
                indeterminate={selectedCount > 0 && selectedCount < itemCount}
                onChange={(event) => onSelectAll(event.target.checked)}
              />
              <span>Select all</span>
            </label>
          ) : null}
          <span className="sv-pill">{isLoading ? "Loading" : `${itemCount} pending`}</span>
          {onClose ? (
            <button type="button" className="review-queue-close" onClick={onClose} aria-label="Close review queue">
              <X aria-hidden="true" size={16} />
            </button>
          ) : null}
        </div>
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
              <SelectionCheckbox
                aria-label={`Select all OCR blocks in ${group.docTitle}`}
                checked={group.items.every((item) => selectedItemIds.has(item.id))}
                disabled={disabled}
                indeterminate={group.items.some((item) => selectedItemIds.has(item.id)) && !group.items.every((item) => selectedItemIds.has(item.id))}
                onChange={(event) => onSelectGroup(group.items.map((item) => item.id), event.target.checked)}
              />
              <FileText aria-hidden="true" size={15} />
              <span>{group.docTitle}</span>
              <strong>{group.items.length}</strong>
            </div>
            <div className="review-doc-items">
              {group.items.map((item) => {
                const label = `${itemTypeLabel(item.item_type)} #${item.item_index}`;
                return (
                  <div className="review-queue-item-row" data-selected={selectedItemIds.has(item.id) || undefined} key={item.id}>
                    <label className="review-item-checkbox">
                      <input
                        type="checkbox"
                        aria-label={`Select ${label} from ${item.doc_title}`}
                        checked={selectedItemIds.has(item.id)}
                        disabled={disabled}
                        onChange={(event) => onSelectGroup([item.id], event.target.checked)}
                      />
                    </label>
                    <button
                      type="button"
                      aria-current={selectedId === item.id ? "true" : undefined}
                      onClick={() => onSelect(item.id)}
                      className="review-queue-item"
                    >
                      <span className="review-queue-item-main">
                        <span className="review-queue-item-title">{label}</span>
                        <span className="review-queue-item-meta">
                          Page {pageRange(item)} | {qualitySummary(item)}
                        </span>
                        <span className="review-queue-item-excerpt">{item.partial_text}</span>
                      </span>
                      <ConfidenceMeter item={item} />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function SelectionCheckbox({ indeterminate, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { indeterminate: boolean }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return <input {...props} ref={ref} type="checkbox" />;
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

export function ReviewDocumentPreview({
  item,
  previewMode,
}: {
  item: ReviewItem | null;
  previewMode: boolean;
}) {
  const region = item ? reviewRegionFromItem(item) : null;
  const initialPage = region?.page ?? item?.page_start ?? item?.page_end ?? 1;
  const hasImageEvidence = Boolean(item?.image_asset_id && !region?.bbox);
  const fallbackMessage = region?.bbox
    ? "Exact source highlight is unavailable for this document."
    : "This review block does not include a page bounding box, so compare the OCR text against the visible page.";

  return (
    <section className="sv-card review-preview-panel" aria-label="Document page preview">
      <div className="review-panel-header">
        <div>
          <p className="sv-eyebrow">Evidence</p>
          <h2 className="sv-section-title">{hasImageEvidence ? "Extracted Image" : "Document Page"}</h2>
          <p>{item ? (hasImageEvidence ? `${item.doc_title}, ${itemTypeLabel(item.item_type)} #${item.item_index}` : `${item.doc_title}, page ${pageRange(item)}`) : "Select a block to open its source page."}</p>
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
              textTargets={hasImageEvidence ? [] : [{ exactText: item.partial_text, occurrence: 0, prefix: "", suffix: "" }]}
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

export function ReviewCorrectionPanel({
  item,
  onReviewed,
  previewMode,
}: {
  item: ReviewItem | null;
  onReviewed: (itemId: string) => void;
  previewMode: boolean;
}) {
  const [correctedText, setCorrectedText] = useState("");
  const originalTextRef = useRef<HTMLPreElement>(null);
  const correctedTextRef = useRef<HTMLTextAreaElement>(null);
  const syncingScrollRef = useRef(false);
  const queryClient = useQueryClient();
  const { notify } = useToast();

  useEffect(() => setCorrectedText(item?.corrected_text ?? item?.partial_text ?? ""), [item?.id, item?.corrected_text, item?.partial_text]);

  const approveMutation = useMutation({
    mutationFn: () => reviewApi.approve(item?.id ?? "", correctedText.trim()),
    onSuccess: (_response, _variables, _context) => {
      if (item) onReviewed(item.id);
      void queryClient.invalidateQueries({ queryKey: ["review-queue"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
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
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
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
  const decisionActions = (
    <div className="review-decision-actions" aria-label="Review actions">
      <button
        type="button"
        title="Approve correction"
        aria-label="Approve correction"
        onClick={() => approveMutation.mutate()}
        disabled={!canApprove}
        className="review-decision-action review-decision-action-approve"
      >
        {approveMutation.isPending ? <Loader2 aria-hidden="true" className="animate-spin" size={17} /> : <CheckCircle2 aria-hidden="true" size={17} />}
      </button>
      <button
        type="button"
        title="Reset corrected text to original OCR"
        aria-label="Reset corrected text to original OCR"
        onClick={() => setCorrectedText(item.partial_text)}
        disabled={isMutating || previewMode}
        className="review-decision-action review-decision-action-reset"
      >
        <RotateCcw aria-hidden="true" size={17} />
      </button>
      <button
        type="button"
        title="Reject review block"
        aria-label="Reject review block"
        onClick={() => rejectMutation.mutate()}
        disabled={isMutating || previewMode}
        className="review-decision-action review-decision-action-reject"
      >
        {rejectMutation.isPending ? <Loader2 aria-hidden="true" className="animate-spin" size={17} /> : <XCircle aria-hidden="true" size={17} />}
      </button>
    </div>
  );

  function syncTextScroll(event: UIEvent<HTMLElement>, target: HTMLElement | null) {
    if (!target || syncingScrollRef.current) return;
    const source = event.currentTarget;
    syncingScrollRef.current = true;
    target.scrollTop = proportionalScrollTop(
      source.scrollTop,
      source.scrollHeight,
      source.clientHeight,
      target.scrollHeight,
      target.clientHeight,
    );
    requestAnimationFrame(() => { syncingScrollRef.current = false; });
  }

  return (
    <aside className="sv-card review-correction-panel" aria-label="Correction panel">
      <div className="review-panel-header">
        <div>
          <p className="sv-eyebrow">Decision</p>
          <h2 className="sv-section-title">Correct Extraction</h2>
          <p>{itemTypeLabel(item.item_type)} #{item.item_index} from page {pageRange(item)}</p>
        </div>
        <div className="review-correction-header-actions">
          {decisionActions}
          <span className={confidencePillClass(item)}>{confidenceLabel(item.confidence)}</span>
        </div>
      </div>

      {previewMode ? <InlineMessage tone="warning">Preview only. Approval and rejection are disabled for the sample items.</InlineMessage> : null}

      {item.image_description ? (
        <details className="review-original-text review-image-description">
          <summary>AI image description</summary>
          <p className="text-secondary">Generated context, separate from the transcription being approved.</p>
          <pre>{item.image_description}</pre>
        </details>
      ) : null}

      <div className="review-correction-body">
        <section className="review-original-text" aria-label="Original OCR text">
          <div className="review-subsection-header">
            <h3>Original OCR</h3>
            <span>{item.partial_text.length} chars</span>
          </div>
          <pre ref={originalTextRef} onScroll={(event) => syncTextScroll(event, correctedTextRef.current)}>{item.partial_text}</pre>
        </section>

        <label className="sv-field review-correction-field">
          <span className="review-field-header">
            <span className="sv-label">Corrected extraction text</span>
            <small>{correctedText.trim().length} chars</small>
          </span>
          <textarea
            ref={correctedTextRef}
            value={correctedText}
            disabled={isMutating || previewMode}
            onChange={(event) => setCorrectedText(event.target.value)}
            onScroll={(event) => syncTextScroll(event, originalTextRef.current)}
            rows={10}
            className="sv-textarea"
          />
          <small className="text-secondary">Edit only the extraction text that should be saved for this review block.</small>
        </label>

        {!correctedText.trim() ? (
          <p className="review-helper-text" role="status">
            <AlertTriangle aria-hidden="true" size={14} />
            Corrected text is required before approval.
          </p>
        ) : null}
      </div>

    </aside>
  );
}
