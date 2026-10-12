import { useEffect, useMemo, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, FileText, ImageIcon, ListFilter, Loader2, RefreshCw, XCircle } from "lucide-react";

import { reviewApi } from "@/lib/api/contracts";
import { InlineMessage } from "@/components/layout/Common";
import { PrudentiaWorkspace } from "@/components/layout/PrudentiaWorkspace";
import { useBranding } from "@/components/brand/BrandContext";
import { useToast } from "@/components/feedback/ToastProvider";
import type { RouteId } from "@/routes/routes";
import type { User as AuthUser } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";
import { bulkReviewTargets, groupReviewItemsByDocument, itemTypeLabel, reviewApprovalText, reviewDocumentCount } from "@/features/review-queue/utils/reviewQueueUtils";
import {
  ReviewQueueClearState,
  ReviewSummaryMetric,
} from "@/features/review-queue/components/ReviewQueuePrimitives";
import { ImageReviewWorkspace } from "@/features/review-queue/components/ImageReviewWorkspace";
import { ReviewCorrectionPanel, ReviewDocumentPreview, ReviewQueuePanel } from "@/features/review-queue/components/OcrReviewWorkspace";
import { devReviewPreviewItems } from "@/features/review-queue/utils/reviewQueuePreview";

export function PrudentiaReviewQueuePage({ onLogout, onNavigate, user }: Props) {
  const branding = useBranding();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [activeTab, setActiveTab] = useState<ReviewTab>("ocr");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedItemIds, setSelectedItemIds] = useState<string[]>([]);
  const [bulkIntent, setBulkIntent] = useState<BulkIntent | null>(null);
  const [compactWorkbench, setCompactWorkbench] = useState(() => typeof window !== "undefined" && window.matchMedia("(max-width: 1679px)").matches);
  const [queueOpen, setQueueOpen] = useState(false);
  const reviewQuery = useQuery({ queryKey: ["review-queue"], queryFn: reviewApi.list, retry: false });
  const summaryQuery = useQuery({ queryKey: ["review-queue", "summary"], queryFn: reviewApi.summary, retry: false });
  const imageReviewQuery = useQuery({ queryKey: ["review-queue", "image-batches"], queryFn: reviewApi.listImageBatches, retry: false });
  const previewItems = useMemo(() => devReviewPreviewItems(), []);
  const previewMode = previewItems !== null;
  const items = previewItems ?? reviewQuery.data?.items ?? [];
  const imageBatches = imageReviewQuery.data?.batches ?? [];
  const imageCandidateTotal = imageReviewQuery.data?.candidate_total ?? imageBatches.reduce((total, batch) => total + batch.candidates.length, 0);
  const groups = useMemo(() => groupReviewItemsByDocument(items), [items]);
  const detailedDocumentCount = reviewDocumentCount(items, imageBatches);
  const pendingDocumentCount = previewMode
    ? detailedDocumentCount
    : summaryQuery.data?.pending_document_count ?? detailedDocumentCount;
  const selected = items.find((item) => item.id === selectedId) ?? items[0] ?? null;
  const selectedItemIdSet = useMemo(() => new Set(selectedItemIds), [selectedItemIds]);
  const selectedIndex = selected ? items.findIndex((item) => item.id === selected.id) : -1;
  const ocrQueueIsClear = !previewMode && !reviewQuery.isLoading && !reviewQuery.isError && items.length === 0;
  const imageQueueIsClear = !imageReviewQuery.isLoading && !imageReviewQuery.isError && imageBatches.length === 0;
  const handleRefresh = () => {
    if (previewMode) return;
    void reviewQuery.refetch();
    void summaryQuery.refetch();
    void imageReviewQuery.refetch();
  };
  const bulkMutation = useMutation({
    mutationFn: async ({ decision, targets }: { decision: BulkDecision; targets: typeof items }) => {
      const succeededIds: string[] = [];
      const failures: { id: string; message: string }[] = [];
      for (const item of targets) {
        try {
          if (decision === "approve") {
            const correctedText = reviewApprovalText(item);
            if (!correctedText) throw new Error("The OCR block has no text to approve.");
            await reviewApi.approve(item.id, correctedText);
          } else {
            await reviewApi.reject(item.id);
          }
          succeededIds.push(item.id);
        } catch (error) {
          failures.push({ id: item.id, message: errorMessage(error, "The review action failed.") });
        }
      }
      return { decision, failures, succeededIds };
    },
    onSuccess: ({ decision, failures, succeededIds }) => {
      setBulkIntent(null);
      setSelectedItemIds((current) => current.filter((id) => !succeededIds.includes(id)));
      void queryClient.invalidateQueries({ queryKey: ["review-queue"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      const action = decision === "approve" ? "approval" : "rejection";
      notify({
        title: failures.length === 0 ? `Bulk ${action} complete` : `Bulk ${action} incomplete`,
        description: failures.length === 0
          ? `${succeededIds.length} ${decision === "reject" ? "document batches" : "OCR blocks"} processed.`
          : `${succeededIds.length} completed; ${failures.length} failed and remain in the queue. ${failures[0].message}`,
        tone: succeededIds.length === 0 ? "error" : failures.length > 0 ? "warning" : "success",
      });
    },
  });

  useEffect(() => {
    if (items.length === 0) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!selectedId || !items.some((item) => item.id === selectedId)) setSelectedId(items[0].id);
  }, [items, selectedId]);

  useEffect(() => {
    setSelectedItemIds((current) => {
      const visible = current.filter((id) => items.some((item) => item.id === id));
      return visible.length === current.length ? current : visible;
    });
  }, [items]);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(max-width: 1679px)");
    const updateLayout = () => setCompactWorkbench(mediaQuery.matches);
    updateLayout();
    mediaQuery.addEventListener("change", updateLayout);
    return () => mediaQuery.removeEventListener("change", updateLayout);
  }, []);

  function handleReviewed(reviewedId: string) {
    const reviewedIndex = items.findIndex((item) => item.id === reviewedId);
    const nextItem = reviewedIndex >= 0 ? items[reviewedIndex + 1] ?? items[reviewedIndex - 1] ?? null : items[0] ?? null;
    setSelectedId(nextItem?.id ?? null);
    setSelectedItemIds((current) => current.filter((id) => id !== reviewedId));
  }

  function selectItems(itemIds: string[], shouldSelect: boolean) {
    setSelectedItemIds((current) => {
      const next = new Set(current);
      itemIds.forEach((id) => shouldSelect ? next.add(id) : next.delete(id));
      return [...next];
    });
    setBulkIntent(null);
  }

  function prepareBulkAction(decision: BulkDecision) {
    if (previewMode || bulkMutation.isPending) return;
    const targets = bulkReviewTargets(items, selectedItemIds, decision);
    setBulkIntent({ decision, itemIds: targets.map((item) => item.id) });
  }

  const pendingBulkItems = bulkIntent
    ? items.filter((item) => bulkIntent.itemIds.includes(item.id))
    : [];
  const bulkAppliesToAll = selectedItemIds.length === 0 || selectedItemIds.length === items.length;

  function selectReviewItem(itemId: string) {
    setSelectedId(itemId);
    if (compactWorkbench) setQueueOpen(false);
  }

  function moveSelection(offset: -1 | 1) {
    const nextItem = items[selectedIndex + offset];
    if (nextItem) selectReviewItem(nextItem.id);
  }

  function handleTabKeyDown(event: ReactKeyboardEvent<HTMLButtonElement>) {
    const tabs = Array.from(event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role='tab']") ?? []);
    const currentIndex = tabs.indexOf(event.currentTarget);
    if (currentIndex < 0) return;
    const nextIndex = event.key === "ArrowRight"
      ? (currentIndex + 1) % tabs.length
      : event.key === "ArrowLeft"
        ? (currentIndex - 1 + tabs.length) % tabs.length
        : event.key === "Home"
          ? 0
          : event.key === "End"
            ? tabs.length - 1
            : null;
    if (nextIndex === null) return;
    event.preventDefault();
    tabs[nextIndex].focus();
    tabs[nextIndex].click();
  }

  return (
    <PrudentiaWorkspace activeRoute="review" onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page review-workspace" id="main-content">
        <div className="sv-page-inner sv-page-inner-workbench review-page-inner">
          <header className="sv-page-header review-page-header">
            <div>
              <p className="sv-eyebrow">{branding.app_name}</p>
              <h1 className="sv-page-title">Review Queue</h1>
              <p className="sv-page-subtitle">Resolve extraction blocks and PDF image-analysis holds before documents continue into the searchable library.</p>
            </div>
            <div className="review-header-tools">
              <div className="review-summary" aria-label="Review queue summary">
                <ReviewSummaryMetric label="Pending blocks" value={String(items.length)} loading={!previewMode && reviewQuery.isLoading} />
                <ReviewSummaryMetric label="Image candidates" value={String(imageCandidateTotal)} loading={imageReviewQuery.isLoading} />
                <ReviewSummaryMetric label="Documents" value={String(pendingDocumentCount)} loading={!previewMode && summaryQuery.isLoading} />
              </div>
              <button type="button" onClick={handleRefresh} disabled={previewMode || reviewQuery.isFetching || summaryQuery.isFetching || imageReviewQuery.isFetching} className="sv-action-secondary review-refresh-action">
                {!previewMode && (reviewQuery.isFetching || summaryQuery.isFetching || imageReviewQuery.isFetching) ? <Loader2 aria-hidden="true" className="animate-spin" size={15} /> : <RefreshCw aria-hidden="true" size={15} />}
                Refresh
              </button>
            </div>
          </header>

          <div className="review-tabs" role="tablist" aria-label="Review queue type">
            <button type="button" role="tab" id="review-tab-ocr" aria-controls="review-panel-ocr" aria-selected={activeTab === "ocr"} onClick={() => setActiveTab("ocr")} onKeyDown={handleTabKeyDown}>
              <FileText aria-hidden="true" size={15} />
              OCR blocks
              <span>{items.length}</span>
            </button>
            <button type="button" role="tab" id="review-tab-images" aria-controls="review-panel-images" aria-selected={activeTab === "images"} onClick={() => setActiveTab("images")} onKeyDown={handleTabKeyDown}>
              <ImageIcon aria-hidden="true" size={15} />
              PDF images
              <span>{imageCandidateTotal}</span>
            </button>
          </div>

          {previewMode ? <InlineMessage tone="warning">Preview mode: sample review items are shown without changing the database.</InlineMessage> : null}
          {!previewMode && reviewQuery.isError ? <InlineMessage tone="error">{errorMessage(reviewQuery.error, "Unable to load review queue.")}</InlineMessage> : null}
          {!previewMode && summaryQuery.isError ? <InlineMessage tone="warning">{errorMessage(summaryQuery.error, "Unable to load the review document count.")}</InlineMessage> : null}
          {imageReviewQuery.isError ? <InlineMessage tone="error">{errorMessage(imageReviewQuery.error, "Unable to load PDF image review queue.")}</InlineMessage> : null}

          {activeTab === "ocr" && ocrQueueIsClear ? (
            <ReviewQueueClearState kind="ocr" onNavigate={onNavigate} onRefresh={handleRefresh} refreshing={reviewQuery.isFetching} />
          ) : null}

          {activeTab === "ocr" && !ocrQueueIsClear ? (
            <div className="review-ocr-workbench" id="review-panel-ocr" role="tabpanel" aria-labelledby="review-tab-ocr" tabIndex={0}>
              <div className="review-workbench-toolbar" aria-label="OCR review navigation">
                <button
                  type="button"
                  className="sv-action-secondary review-queue-toggle"
                  aria-controls="review-queue-drawer"
                  aria-expanded={compactWorkbench ? queueOpen : true}
                  onClick={() => setQueueOpen((open) => !open)}
                >
                  <ListFilter aria-hidden="true" size={16} />
                  Queue
                  <span>{items.length}</span>
                </button>
                <div className="review-item-navigation">
                  <button type="button" onClick={() => moveSelection(-1)} disabled={selectedIndex <= 0} aria-label="Previous review item">
                    <ChevronLeft aria-hidden="true" size={16} />
                  </button>
                  <span aria-live="polite">{selectedIndex >= 0 ? `${selectedIndex + 1} of ${items.length}` : "No item selected"}</span>
                  <button type="button" onClick={() => moveSelection(1)} disabled={selectedIndex < 0 || selectedIndex >= items.length - 1} aria-label="Next review item">
                    <ChevronRight aria-hidden="true" size={16} />
                  </button>
                </div>
                {selected ? <p className="review-selection-context">{selected.doc_title} · {itemTypeLabel(selected.item_type)} #{selected.item_index}</p> : null}
                <div className="review-bulk-actions" aria-label="Bulk OCR review actions">
                  {selectedItemIds.length > 0 ? (
                    <button type="button" className="review-clear-selection" disabled={bulkMutation.isPending} onClick={() => selectItems(items.map((item) => item.id), false)}>
                      Clear {selectedItemIds.length}
                    </button>
                  ) : null}
                  <button type="button" className="sv-action-primary" disabled={previewMode || bulkMutation.isPending || items.length === 0} onClick={() => prepareBulkAction("approve")}>
                    <CheckCircle2 aria-hidden="true" size={15} />
                    {bulkAppliesToAll ? "Approve all" : `Approve ${selectedItemIds.length}`}
                  </button>
                  <button type="button" className="sv-action-danger" disabled={previewMode || bulkMutation.isPending || items.length === 0} onClick={() => prepareBulkAction("reject")}>
                    <XCircle aria-hidden="true" size={15} />
                    {bulkAppliesToAll ? "Reject all" : `Reject ${selectedItemIds.length}`}
                  </button>
                </div>
              </div>

              {bulkIntent ? (
                <div className="review-bulk-confirmation" role="alert">
                  <AlertTriangle aria-hidden="true" size={18} />
                  <div>
                    <strong>
                      {bulkIntent.decision === "approve"
                        ? `Approve ${pendingBulkItems.length} OCR ${pendingBulkItems.length === 1 ? "block" : "blocks"}?`
                        : `Reject ${pendingBulkItems.length} document ${pendingBulkItems.length === 1 ? "batch" : "batches"}?`}
                    </strong>
                    <span>
                      {bulkIntent.decision === "approve"
                        ? "This saves each block's stored correction, or its current OCR text when no correction exists."
                        : "Rejecting one block rejects its full batch and stops that document's indexing job."}
                    </span>
                  </div>
                  <div className="review-bulk-confirmation-actions">
                    <button type="button" className="sv-action-secondary" disabled={bulkMutation.isPending} onClick={() => setBulkIntent(null)}>Cancel</button>
                    <button
                      type="button"
                      className={bulkIntent.decision === "approve" ? "sv-action-primary" : "sv-action-danger"}
                      disabled={bulkMutation.isPending || pendingBulkItems.length === 0}
                      onClick={() => bulkMutation.mutate({ decision: bulkIntent.decision, targets: pendingBulkItems })}
                    >
                      {bulkMutation.isPending ? <Loader2 aria-hidden="true" className="animate-spin" size={15} /> : null}
                      Confirm {bulkIntent.decision}
                    </button>
                  </div>
                </div>
              ) : null}

              <div className={queueOpen ? "review-layout review-layout-queue-open" : "review-layout"}>
                {compactWorkbench && queueOpen ? (
                  <button type="button" className="review-queue-backdrop" aria-label="Close review queue" onClick={() => setQueueOpen(false)} />
                ) : null}
                {!compactWorkbench || queueOpen ? (
                  <ReviewQueuePanel
                    disabled={previewMode || bulkMutation.isPending}
                    groups={groups}
                    isLoading={!previewMode && reviewQuery.isLoading}
                    onClose={compactWorkbench ? () => setQueueOpen(false) : undefined}
                    onSelect={selectReviewItem}
                    onSelectAll={(checked) => selectItems(items.map((item) => item.id), checked)}
                    onSelectGroup={selectItems}
                    panelId="review-queue-drawer"
                    selectedId={selected?.id ?? null}
                    selectedItemIds={selectedItemIdSet}
                  />
                ) : null}
                <ReviewDocumentPreview item={selected} previewMode={previewMode} />
                <ReviewCorrectionPanel item={selected} onReviewed={handleReviewed} previewMode={previewMode} />
              </div>
            </div>
          ) : null}

          {activeTab === "images" && imageQueueIsClear ? (
            <ReviewQueueClearState kind="images" onNavigate={onNavigate} onRefresh={handleRefresh} refreshing={imageReviewQuery.isFetching} />
          ) : null}

          {activeTab === "images" && !imageQueueIsClear ? (
            <ImageReviewWorkspace
              batches={imageBatches}
              isLoading={imageReviewQuery.isLoading}
              previewMode={previewMode}
            />
          ) : null}
        </div>
      </main>
    </PrudentiaWorkspace>
  );
}

type ReviewTab = "ocr" | "images";
type BulkDecision = "approve" | "reject";
type BulkIntent = { decision: BulkDecision; itemIds: string[] };

type Props = { onLogout: () => void; onNavigate: (route: RouteId) => void; user: AuthUser };
