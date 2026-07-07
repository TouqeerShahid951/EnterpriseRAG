import { describe, expect, it } from "vitest";

import {
  formatIngestRunLabel,
  formatSecondaryStageProgress,
  formatStageProgress,
  formatUploadWarning,
  graphEnrichmentForJob,
  isUploadCancellableStatus,
  isUploadTerminalStatus,
} from "./uploadJobProgress";

describe("upload job progress formatting", () => {
  it("formats metadata stage progress labels", () => {
    expect(formatStageProgress({ unit: "metadata", current: 1, total: 13, label: null })).toBe("Metadata step 1 of 13");
    expect(formatStageProgress({ unit: "metadata", current: 0, total: 1, label: "Waiting on metadata model for 15s" })).toBe("Waiting on metadata model for 15s");
  });

  it("formats image analysis stage progress labels", () => {
    expect(formatStageProgress({ unit: "images", current: 3, total: 12, label: null })).toBe("Images 3 of 12");
    expect(formatStageProgress({ unit: "images", current: 3, total: 12, label: "Image analysis analyzing page image 4 of 12" })).toBe("Image analysis analyzing page image 4 of 12");
  });

  it("maps metadata warning codes to readable labels", () => {
    expect(formatUploadWarning("ollama_metadata_timeout")).toBe("Metadata model timed out; fallback metadata was used");
    expect(formatUploadWarning("unknown_warning")).toBe("Unknown Warning");
  });

  it("labels review resumes separately from retries", () => {
    expect(formatIngestRunLabel({ attempt_count: 1, max_attempts: 3 })).toBe("Attempt 1 of 3");
    expect(formatIngestRunLabel({ attempt_count: 2, max_attempts: 3 })).toBe("Retry 2 of 3");
    expect(formatIngestRunLabel({
      attempt_count: 2,
      max_attempts: 3,
      parser_provenance: {
        version: 1,
        document_kind: "pdf",
        page_count: 359,
        primary_parser: "review_resume",
        secondary_parser: "vision",
        routing_mode: "image_review_resume",
        config: {},
        docling_selection: null,
        parser_item_counts: {},
        parser_page_counts: {},
        quality_flag_counts: {},
        fallback: null,
        errors: [],
      },
    })).toBe("Resumed after review");
  });

  it("suppresses duplicate secondary stage progress", () => {
    const progress = { unit: "pages" as const, current: 1, total: 3, label: "Vision layout repairing page 2 of 3" };

    expect(formatSecondaryStageProgress(progress, "Vision layout repairing page 2 of 3")).toBeNull();
    expect(formatSecondaryStageProgress(progress, "Using the vision model")).toBe("Vision layout repairing page 2 of 3");
  });

  it("maps matched GraphRAG active and queued tasks to enrichment chips", () => {
    const active = graphEnrichmentForJob({ jobId: "job-1", status: "complete", documentId: "doc-1" }, {
      enabled: true,
      queue_name: "graphrag:jobs",
      queued_jobs: 1,
      queue_error: null,
      worker_online: true,
      worker_error: null,
      active_jobs: 1,
      observed_pool_size: 1,
      workers: [],
      active_tasks: [{ task_id: "task-1", task_name: "apps.ingestion.tasks.index_document_graphrag", worker: "graph@node", job_id: "job-1", document_id: "doc-1", started_at: null, elapsed_seconds: 61 }],
      queued_tasks: [],
    });
    const queued = graphEnrichmentForJob({ jobId: "job-2", status: "complete", documentId: "doc-2" }, {
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
      queued_tasks: [{ task_id: "task-2", task_name: "apps.ingestion.tasks.index_document_graphrag", job_id: "job-2", document_id: "doc-2" }],
    });

    expect(active?.label).toBe("Graph enrichment running");
    expect(active?.detail).toBe("Running 1m");
    expect(queued?.label).toBe("Graph enrichment queued");
  });

  it("does not show GraphRAG chips before core indexing completes", () => {
    const chip = graphEnrichmentForJob({ jobId: "job-1", status: "processing" }, {
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
      queued_tasks: [{ task_id: "task-1", task_name: "apps.ingestion.tasks.index_document_graphrag", job_id: "job-1", document_id: null }],
    });

    expect(chip).toBeNull();
  });

  it("hides idle graph enrichment when the workspace toggle is disabled", () => {
    const chip = graphEnrichmentForJob({ jobId: "job-1", status: "complete", documentId: "doc-1" }, {
      enabled: false,
      queue_name: "graphrag:jobs",
      queued_jobs: 0,
      queue_error: null,
      worker_online: true,
      worker_error: null,
      active_jobs: 0,
      observed_pool_size: 1,
      workers: [],
      active_tasks: [],
      queued_tasks: [],
    });

    expect(chip).toBeNull();
  });

  it("keeps running graph enrichment visible after the workspace toggle is disabled", () => {
    const chip = graphEnrichmentForJob({ jobId: "job-1", status: "complete", documentId: "doc-1" }, {
      enabled: false,
      queue_name: "graphrag:jobs",
      queued_jobs: 0,
      queue_error: null,
      worker_online: true,
      worker_error: null,
      active_jobs: 1,
      observed_pool_size: 1,
      workers: [],
      active_tasks: [{ task_id: "task-1", task_name: "apps.ingestion.tasks.index_document_graphrag", worker: "graph@node", job_id: "job-1", document_id: "doc-1", started_at: null, elapsed_seconds: 12 }],
      queued_tasks: [],
    });

    expect(chip?.label).toBe("Graph enrichment running");
  });

  it("treats cancelled jobs as terminal but not cancellable", () => {
    expect(isUploadTerminalStatus("cancelled")).toBe(true);
    expect(isUploadCancellableStatus("cancelled")).toBe(false);
    expect(isUploadCancellableStatus("processing")).toBe(true);
    expect(isUploadCancellableStatus("human_review")).toBe(true);
  });
});
