import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { GraphRAGStatus, UploadJobState, User } from "@/types/api";
import type { UploadBatchItemView, UploadJobView } from "@/types/chat";
import { BatchUploadStatus, partitionUploadItems } from "./BatchUploadStatus";

describe("upload status presentation", () => {
  it("collapses current successes and keeps failures detailed", () => {
    const markup = renderToStaticMarkup(
      <BatchUploadStatus
        cancelingJobId={null}
        currentUser={user}
        graphStatus={undefined}
        graphStatusError={null}
        items={[
          item("current-complete", "current.pdf", "complete", true),
          item("historical-complete", "old.pdf", "complete", false),
          item("failed", "failed.pdf", "failed", false),
        ]}
        onCancelIngestJob={() => undefined}
        onClearUploadJobs={() => undefined}
        onRetryIngestJob={() => undefined}
        onViewActivity={() => undefined}
        retryingJobId={null}
      />,
    );

    expect(markup).toContain("1 upload completed");
    expect(markup).toContain("Dismiss completed (1)");
    expect(markup).toContain("1 needs attention");
    expect(markup).toContain("failed.pdf");
    expect(markup).not.toContain("current.pdf");
    expect(markup).not.toContain("old.pdf");
  });

  it("keeps graph enrichment visible after core indexing completes", () => {
    const graphStatus: GraphRAGStatus = {
      enabled: true,
      queue_name: "graphrag:jobs",
      queued_jobs: 1,
      queue_error: null,
      worker_online: true,
      worker_error: null,
      active_jobs: 0,
      observed_pool_size: 1,
      workers: [],
      active_tasks: [],
      queued_tasks: [{ task_id: "task-1", task_name: "index", job_id: "job-current-complete", document_id: "doc-current-complete" }],
    };

    const partition = partitionUploadItems([item("current-complete", "current.pdf", "complete", true)], graphStatus, null);

    expect(partition.completedItems).toEqual([]);
    expect(partition.visibleItems).toHaveLength(1);
  });
});

const user: User = {
  user_id: "user-1",
  email: "user@example.test",
  account_type: "contributor",
  clearance_level: "NATO_SECRET",
  group_paths: ["/legal"],
  permission_version: 1,
};

function item(id: string, fileName: string, status: UploadJobState, isCurrentSession: boolean): UploadBatchItemView {
  return {
    id,
    fileName,
    fileSize: null,
    groupPath: "/legal",
    clearanceLevel: "NATO_RESTRICTED",
    isCurrentSession,
    requestState: "accepted",
    job: job(id, status),
    uploadError: null,
    jobError: null,
  };
}

function job(id: string, status: UploadJobState): UploadJobView {
  return {
    jobId: `job-${id}`,
    documentId: `doc-${id}`,
    retryOfJobId: null,
    status,
    progressPct: status === "complete" ? 100 : 50,
    stage: status === "processing" ? "parsing_document" : status,
    stageLabel: status,
    stageDetail: status,
    stageProgress: null,
    steps: [],
    warnings: [],
    parserProvenance: null,
    errorCode: status === "failed" ? "ingest_failed" : null,
    errorMessage: status === "failed" ? "Ingestion failed." : null,
    attemptCount: 1,
    maxAttempts: 3,
    createdAt: null,
    updatedAt: null,
    completedAt: null,
    lastHeartbeatAt: null,
  };
}
