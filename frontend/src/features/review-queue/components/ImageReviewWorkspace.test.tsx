import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { ToastProvider } from "@/components/feedback/ToastProvider";
import type { ImageReviewBatch } from "@/types/api";
import { ImageReviewWorkspace } from "./ImageReviewWorkspace";

const batch: ImageReviewBatch = {
  id: "batch-1",
  job_id: "job-1",
  doc_id: "doc-1",
  doc_title: "Scanned policy.pdf",
  status: "pending",
  candidate_count: 1,
  recommended_count: 1,
  pending_count: 1,
  approved_count: 0,
  skipped_count: 0,
  candidates: [{
    id: "candidate-1",
    batch_id: "batch-1",
    doc_id: "doc-1",
    doc_title: "Scanned policy.pdf",
    candidate_key: "page-1",
    filename: "page-1.png",
    source_kind: "pdf_image",
    page: 1,
    bbox: null,
    page_area_ratio: 0.4,
    content_url: "/api/v1/review-queue/image-candidates/candidate-1/content",
    content_type: "image/png",
    width: 100,
    height: 100,
    quality_flags: [],
    score: 0.9,
    recommended: true,
    status: "pending",
    assigned_to: null,
    skip_reason: null,
    created_at: null,
    updated_at: null,
  }],
  created_at: null,
  updated_at: null,
};

it("keeps image decisions available at the top and in the decision panel", () => {
  const markup = renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ToastProvider>
        <ImageReviewWorkspace batches={[batch]} isLoading={false} previewMode={false} />
      </ToastProvider>
    </QueryClientProvider>,
  );

  expect(markup).toContain('aria-label="Quick PDF image review decisions"');
  expect(markup.match(/Analyze selected/g)).toHaveLength(2);
  expect(markup.match(/Analyze recommended/g)).toHaveLength(2);
  expect(markup.match(/Skip selected/g)).toHaveLength(2);
  expect(markup.match(/Skip all pending/g)).toHaveLength(2);
  expect(markup.indexOf("Quick PDF image review decisions")).toBeLessThan(markup.indexOf("PDF image candidates"));
});
