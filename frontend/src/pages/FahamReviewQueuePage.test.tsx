import { describe, expect, it } from "vitest";

import type { ReviewItem } from "../types/api";
import { groupReviewItemsByDocument, reviewRegionFromItem } from "./FahamReviewQueuePage";

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

describe("review queue helpers", () => {
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
});
