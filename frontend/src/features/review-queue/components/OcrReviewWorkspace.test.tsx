import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { ToastProvider } from "@/components/feedback/ToastProvider";
import type { ReviewItem } from "@/types/api";
import { ReviewCorrectionPanel } from "./OcrReviewWorkspace";

it("shows one transcription approval with a separately labelled generated description", () => {
  const item: ReviewItem = {
    id: "review", batch_id: "batch", doc_id: "doc", doc_title: "Scanned form.pdf",
    item_index: 0, item_type: "image_text", page_start: 1, page_end: 1,
    bbox: [0, 0, 100, 100], image_asset_id: "image", image_source_kind: "pdf_image",
    quality_flags: ["source:ocr", "ocr_image_consolidated"], confidence: 0.6,
    partial_text: "Retention is 30 days.", image_description: "An administrative form.",
    corrected_text: null, status: "pending", assigned_to: null, created_at: null, updated_at: null,
  };
  const html = renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ToastProvider>
        <ReviewCorrectionPanel item={item} onReviewed={() => undefined} previewMode={false} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  expect(html).toContain("<summary>AI image description</summary>");
  expect(html).toContain("<pre>An administrative form.</pre>");
  expect(html).toContain("<pre>Retention is 30 days.</pre>");
  expect(html.match(/aria-label="Approve correction"/g)).toHaveLength(1);
  expect(html.match(/<textarea/g)).toHaveLength(1);
});
