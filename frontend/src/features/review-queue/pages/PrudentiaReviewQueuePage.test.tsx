import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ReviewItem } from "@/types/api";
import { ReviewQueueClearState } from "../components/ReviewQueuePrimitives";
import { bulkReviewTargets, confidencePercent, groupReviewItemsByDocument, proportionalScrollTop, reviewApprovalText, reviewDocumentCount, reviewRegionFromItem } from "../utils/reviewQueueUtils";

const baseItem: ReviewItem = {
  id: "review-1",
  assigned_to: null,
  batch_id: "batch-1",
  bbox: [10, 20, 110, 60],
  confidence: 0.42,
  corrected_text: null,
  created_at: "2026-06-13T00:00:00Z",
  doc_id: "doc-1",
  doc_title: "Scanned policy.pdf",
  item_index: 3,
  item_type: "text",
  page_end: 2,
  page_start: 2,
  partial_text: "Raw OCR text.",
  quality_flags: ["source:ocr"],
  status: "pending",
  updated_at: null,
};

it("keeps clear-state copy specific to each review queue", () => {
  const props = { onNavigate: () => undefined, onRefresh: () => undefined, refreshing: false };
  const ocr = renderToStaticMarkup(<ReviewQueueClearState {...props} kind="ocr" />);
  const images = renderToStaticMarkup(<ReviewQueueClearState {...props} kind="images" />);

  expect(ocr).toContain("No OCR blocks need review");
  expect(images).toContain("No PDF images need review");
});

describe("review queue helpers", () => {
  it("keeps original and corrected text at the same relative scroll position", () => {
    expect(proportionalScrollTop(400, 1000, 200, 1800, 200)).toBe(800);
    expect(proportionalScrollTop(0, 200, 200, 1800, 200)).toBe(0);
  });

  it("converts a review item into a document highlight region", () => {
    expect(reviewRegionFromItem(baseItem)).toEqual({
      bbox: [10, 20, 110, 60],
      confidence: 0.42,
      page: 2,
      regionType: "text",
      text: "Raw OCR text.",
    });
  });

  it("drops invalid bounding boxes instead of rendering broken highlights", () => {
    expect(reviewRegionFromItem({ ...baseItem, bbox: [10, 20, 5, 60] }).bbox).toBeNull();
    expect(reviewRegionFromItem({ ...baseItem, bbox: null }).bbox).toBeNull();
  });

  it("groups queue rows by document while preserving item order", () => {
    const groups = groupReviewItemsByDocument([
      baseItem,
      { ...baseItem, id: "review-2", item_index: 4 },
      { ...baseItem, id: "review-3", doc_id: "doc-2", doc_title: "Scanned manual.pdf" },
    ]);

    expect(groups).toHaveLength(2);
    expect(groups[0].docTitle).toBe("Scanned policy.pdf");
    expect(groups[0].items.map((item) => item.id)).toEqual(["review-1", "review-2"]);
    expect(groups[1].docTitle).toBe("Scanned manual.pdf");
  });

  it("targets selected blocks and rejects each batch only once", () => {
    const items = [
      baseItem,
      { ...baseItem, id: "review-2" },
      { ...baseItem, id: "review-3", batch_id: "batch-2", corrected_text: "Corrected text." },
    ];

    expect(bulkReviewTargets(items, [], "approve")).toEqual(items);
    expect(bulkReviewTargets(items, ["review-2", "review-3"], "approve").map((item) => item.id)).toEqual(["review-2", "review-3"]);
    expect(bulkReviewTargets(items, [], "reject").map((item) => item.id)).toEqual(["review-1", "review-3"]);
    expect(reviewApprovalText(items[2])).toBe("Corrected text.");
  });

  it("counts a document once across OCR and image review", () => {
    expect(reviewDocumentCount(
      [baseItem, { ...baseItem, id: "review-2" }],
      [{ doc_id: "doc-1" }, { doc_id: "doc-2" }],
    )).toBe(2);
  });

  it("normalizes confidence for meter display", () => {
    expect(confidencePercent(baseItem)).toBe(42);
    expect(confidencePercent({ ...baseItem, confidence: null })).toBe(0);
    expect(confidencePercent({ ...baseItem, confidence: 1.4 })).toBe(100);
  });
});
