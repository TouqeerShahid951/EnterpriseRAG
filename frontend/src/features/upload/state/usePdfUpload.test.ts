import { describe, expect, it } from "vitest";

import type { IngestJob } from "@/types/api";
import { ABBREVIATION_GLOSSARY_DOC_TYPE } from "./pdfUploadBatch";
import { ingestJobToUploadBatchItem, parseDismissedUploadJobIds, uploadHistoryBelongsOnPage } from "./usePdfUpload";

describe("upload job hydration", () => {
  it("keeps generic upload history off the glossary page", () => {
    expect(uploadHistoryBelongsOnPage(ABBREVIATION_GLOSSARY_DOC_TYPE)).toBe(false);
    expect(uploadHistoryBelongsOnPage(null)).toBe(true);
  });

  it("turns a backend upload job into an intake progress row", () => {
    const item = ingestJobToUploadBatchItem({
      job_id: "job-123",
      document_id: "doc-1",
      retry_of_job_id: null,
      document_title: "accepted.png",
      group_path: "/member-space",
      clearance_level: "NATO_SECRET",
      origin: "upload",
      uploaded_by: "user-1",
      status: "processing",
      progress_pct: 37,
      stage: "metadata_enrichment",
      stage_label: "Metadata enrichment",
      stage_detail: "Creating document metadata.",
      stage_progress: null,
      steps: [],
      error_code: null,
      error_message: null,
      attempt_count: 1,
      max_attempts: 3,
      warnings: [],
      parser_provenance: null,
      created_at: "2026-07-03T10:00:00Z",
      updated_at: "2026-07-03T10:01:00Z",
      completed_at: null,
      last_heartbeat_at: "2026-07-03T10:01:00Z",
    } satisfies IngestJob);

    expect(item).toMatchObject({
      id: "job-123",
      fileName: "accepted.png",
      fileSize: null,
      groupPath: "/member-space",
      clearanceLevel: "NATO_SECRET",
      isCurrentSession: false,
      requestState: "accepted",
      uploadError: null,
      jobError: null,
    });
    expect(item.job?.jobId).toBe("job-123");
    expect(item.job?.progressPct).toBe(37);
    expect(item.job?.retryOfJobId).toBe(null);
  });

  it("parses only the newest valid dismissed job ids", () => {
    const stored = JSON.stringify([...Array.from({ length: 101 }, (_, index) => `job-${index}`), 42]);

    expect([...parseDismissedUploadJobIds(stored)]).toEqual(Array.from({ length: 100 }, (_, index) => `job-${index + 1}`));
    expect(parseDismissedUploadJobIds("not-json").size).toBe(0);
  });
});
