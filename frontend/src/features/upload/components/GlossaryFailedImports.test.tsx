import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import type { UploadBatchItemView } from "@/types/chat";
import { GlossaryFailedImports } from "./GlossaryFailedImports";

it("offers retry or recoverable Trash removal for failed glossary sources", () => {
  const markup = renderToStaticMarkup(
    <GlossaryFailedImports
      deletingDocumentId={null}
      items={[failedItem()]}
      onDelete={() => undefined}
      onRetry={() => undefined}
      retryingJobId={null}
    />,
  );

  expect(markup).toContain("Retry");
  expect(markup).toContain("Move to Trash");
  expect(markup).not.toContain(">Delete<");
});

function failedItem(): UploadBatchItemView {
  return {
    id: "job-1",
    fileName: "glossary.pdf",
    fileSize: null,
    groupPath: "/ops",
    clearanceLevel: "NATO_UNCLASSIFIED",
    isCurrentSession: false,
    requestState: "accepted",
    uploadError: null,
    jobError: null,
    job: {
      jobId: "job-1",
      documentId: "document-1",
      retryOfJobId: null,
      status: "failed",
      progressPct: 20,
      stage: "failed",
      stageLabel: "Failed",
      stageDetail: "No recognized entries.",
      stageProgress: null,
      steps: [],
      warnings: [],
      parserProvenance: null,
      errorCode: "abbreviation_glossary_empty",
      errorMessage: "No recognized entries.",
      attemptCount: 1,
      maxAttempts: 3,
      createdAt: null,
      updatedAt: null,
      completedAt: null,
      lastHeartbeatAt: null,
    },
  };
}
