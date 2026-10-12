import { describe, expect, it } from "vitest";
import { documentsForView } from "./documentPageUtils";
import { buildNextStep } from "../pages/PrudentiaDocumentOverviewPage";
import type { Document } from "@/types/api";

const base = { canOpenFolderSources: false, canUpload: true, canViewJobs: true, documentsCount: 54, indexedCurrentCount: 49, needsAttention: 3, processingCount: 0, failedCount: 3, reviewCount: 0, unknownCount: 0, cancelledCount: 2 };

describe("document attention consistency", () => {
  it("opens exactly current failed documents for an all-failure banner", () => {
    expect(buildNextStep(base)).toMatchObject({ title: "3 documents failed ingestion", primaryLabel: "Investigate failures", primarySearch: "?lifecycle=current&ingest=failed" });
    expect(buildNextStep({ ...base, failedCount: 1, reviewCount: 1, unknownCount: 1 }).primarySearch).toBe("?lifecycle=current&ingest=attention");
    expect(buildNextStep({ ...base, needsAttention: 0, failedCount: 0 }).title).toBe("Ingestion cancelled");
    expect(buildNextStep({ ...base, needsAttention: 0, failedCount: 0, cancelledCount: 0 }).title).toBe("No ingestion issues detected");
  });
  it("excludes processing, cancelled and superseded documents from attention", () => {
    const documents = ["failed", "human_review", "unknown", "queued", "processing", "cancelled", "complete"].map((status) => ({ id: status, ingest_status: status, is_current: true }) as Document);
    documents.push({ id: "old", ingest_status: "failed", is_current: false } as Document);
    const filtered = documentsForView("documents", { kind: "overview" }, documents, [], "", "current", "attention", "");
    expect(filtered.map((doc) => doc.id)).toEqual(["failed", "human_review", "unknown"]);
  });
});
