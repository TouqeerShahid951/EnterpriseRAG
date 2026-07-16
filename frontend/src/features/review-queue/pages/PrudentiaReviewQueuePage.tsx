import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, ImageIcon, Loader2, RefreshCw } from "lucide-react";

import { reviewApi } from "@/lib/api/contracts";
import { InlineMessage } from "@/components/layout/Common";
import { PrudentiaWorkspace } from "@/components/layout/PrudentiaWorkspace";
import type { RouteId } from "@/routes/routes";
import type { User as AuthUser } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";
import { groupReviewItemsByDocument } from "@/features/review-queue/utils/reviewQueueUtils";
import {
  ReviewImageClearState,
  ReviewQueueClearState,
  ReviewSummaryMetric,
} from "@/features/review-queue/components/ReviewQueuePrimitives";
import { ImageReviewWorkspace } from "@/features/review-queue/components/ImageReviewWorkspace";
import { ReviewCorrectionPanel, ReviewDocumentPreview, ReviewQueuePanel } from "@/features/review-queue/components/OcrReviewWorkspace";
import { devReviewPreviewItems } from "@/features/review-queue/utils/reviewQueuePreview";


export { confidencePercent, groupReviewItemsByDocument, reviewRegionFromItem } from "@/features/review-queue/utils/reviewQueueUtils";


export function PrudentiaReviewQueuePage({ onLogout, onNavigate, user }: Props) {
  const [activeTab, setActiveTab] = useState<ReviewTab>("ocr");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const reviewQuery = useQuery({ queryKey: ["review-queue"], queryFn: reviewApi.list, retry: false });
  const imageReviewQuery = useQuery({ queryKey: ["review-queue", "image-batches"], queryFn: reviewApi.listImageBatches, retry: false });
  const previewItems = useMemo(() => devReviewPreviewItems(), []);
  const previewMode = previewItems !== null;
  const items = previewItems ?? reviewQuery.data?.items ?? [];
  const imageBatches = imageReviewQuery.data?.batches ?? [];
  const imageCandidateTotal = imageReviewQuery.data?.candidate_total ?? imageBatches.reduce((total, batch) => total + batch.candidates.length, 0);
  const groups = useMemo(() => groupReviewItemsByDocument(items), [items]);
  const selected = items.find((item) => item.id === selectedId) ?? items[0] ?? null;
  const ocrQueueIsClear = !previewMode && !reviewQuery.isLoading && !reviewQuery.isError && items.length === 0;
  const imageQueueIsClear = !imageReviewQuery.isLoading && !imageReviewQuery.isError && imageBatches.length === 0;
  const handleRefresh = () => {
    if (previewMode) return;
    void reviewQuery.refetch();
    void imageReviewQuery.refetch();
  };

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
    <PrudentiaWorkspace activeRoute="review" onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page review-workspace" id="main-content">
        <div className="sv-page-inner sv-page-inner-workbench review-page-inner">
          <header className="sv-page-header review-page-header">
            <div>
              <p className="sv-eyebrow">Prudentia AI</p>
              <h1 className="sv-page-title">Review Queue</h1>
              <p className="sv-page-subtitle">Resolve extraction blocks and PDF image-analysis holds before documents continue into the searchable library.</p>
            </div>
            <div className="review-header-tools">
              <div className="review-summary" aria-label="Review queue summary">
                <ReviewSummaryMetric label="Pending blocks" value={String(items.length)} loading={!previewMode && reviewQuery.isLoading} />
                <ReviewSummaryMetric label="Image candidates" value={String(imageCandidateTotal)} loading={imageReviewQuery.isLoading} />
                <ReviewSummaryMetric label="Documents" value={String(groups.length + imageBatches.length)} loading={(!previewMode && reviewQuery.isLoading) || imageReviewQuery.isLoading} />
              </div>
              <button type="button" onClick={handleRefresh} disabled={previewMode || reviewQuery.isFetching || imageReviewQuery.isFetching} className="sv-action-secondary review-refresh-action">
                {!previewMode && (reviewQuery.isFetching || imageReviewQuery.isFetching) ? <Loader2 aria-hidden="true" className="animate-spin" size={15} /> : <RefreshCw aria-hidden="true" size={15} />}
                Refresh
              </button>
            </div>
          </header>

          <div className="review-tabs" role="tablist" aria-label="Review queue type">
            <button type="button" role="tab" aria-selected={activeTab === "ocr"} onClick={() => setActiveTab("ocr")}>
              <FileText aria-hidden="true" size={15} />
              OCR blocks
              <span>{items.length}</span>
            </button>
            <button type="button" role="tab" aria-selected={activeTab === "images"} onClick={() => setActiveTab("images")}>
              <ImageIcon aria-hidden="true" size={15} />
              PDF images
              <span>{imageCandidateTotal}</span>
            </button>
          </div>

          {previewMode ? <InlineMessage tone="warning">Preview mode: sample review items are shown without changing the database.</InlineMessage> : null}
          {!previewMode && reviewQuery.isError ? <InlineMessage tone="error">{errorMessage(reviewQuery.error, "Unable to load review queue.")}</InlineMessage> : null}
          {imageReviewQuery.isError ? <InlineMessage tone="error">{errorMessage(imageReviewQuery.error, "Unable to load PDF image review queue.")}</InlineMessage> : null}

          {activeTab === "ocr" && ocrQueueIsClear ? (
            <ReviewQueueClearState onNavigate={onNavigate} onRefresh={handleRefresh} refreshing={reviewQuery.isFetching} />
          ) : null}

          {activeTab === "ocr" && !ocrQueueIsClear ? (
            <div className="review-layout">
              <ReviewQueuePanel
                groups={groups}
                isLoading={!previewMode && reviewQuery.isLoading}
                onSelect={setSelectedId}
                selectedId={selected?.id ?? null}
              />
              <ReviewDocumentPreview item={selected} previewMode={previewMode} />
              <ReviewCorrectionPanel item={selected} onReviewed={handleReviewed} previewMode={previewMode} />
            </div>
          ) : null}

          {activeTab === "images" && imageQueueIsClear ? (
            <ReviewImageClearState onNavigate={onNavigate} onRefresh={handleRefresh} refreshing={imageReviewQuery.isFetching} />
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

type Props = { onLogout: () => void; onNavigate: (route: RouteId) => void; user: AuthUser };
