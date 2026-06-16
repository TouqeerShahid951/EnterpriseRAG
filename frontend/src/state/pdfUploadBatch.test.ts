import { describe, expect, it } from "vitest";

import type { PdfUploadDraft } from "../types/chat";
import { mergeDocumentFiles, toUploadRequests, validateDocumentFiles } from "./pdfUploadBatch";

describe("PDF upload batches", () => {
  it("creates one backend request per selected document with shared metadata", () => {
    const files = [
      new File(["%PDF-1.7"], "policy.pdf", { type: "application/pdf", lastModified: 1 }),
      new File(["docx"], "procedure.docx", {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        lastModified: 2,
      }),
    ];
    const draft: PdfUploadDraft = {
      files,
      groupPath: "/finance",
      effectiveDate: "2026-06-09",
      expiryDate: "2026-12-31",
      docType: "policy",
      description: "Shared batch context",
      supersedesText: "old-document-id",
    };

    const requests = toUploadRequests(draft);

    expect(requests).toHaveLength(2);
    expect(requests.map((request) => request.file)).toEqual(files);
    expect(requests.every((request) => request.group_path === "/finance")).toBe(true);
    expect(requests.every((request) => request.description === "Shared batch context")).toBe(true);
    expect(requests.every((request) => request.supersedes?.length === 0)).toBe(true);
  });

  it("keeps supersession metadata for a single-document upload", () => {
    const file = new File(["%PDF-1.7"], "replacement.pdf", { type: "application/pdf" });
    const requests = toUploadRequests({
      files: [file],
      groupPath: "/legal",
      effectiveDate: "2026-06-09",
      expiryDate: "",
      docType: "contract",
      description: "",
      supersedesText: "first-id, second-id",
    });

    expect(requests[0]?.supersedes).toEqual(["first-id", "second-id"]);
  });

  it("sends no effective date when the field is blank", () => {
    const requests = toUploadRequests({
      files: [new File(["pdf"], "report.pdf", { type: "application/pdf" })],
      groupPath: "/finance",
      effectiveDate: "",
      expiryDate: "",
      docType: "report",
      description: "",
      supersedesText: "",
    });

    expect(requests[0]?.effective_date).toBeNull();
  });

  it("deduplicates selections and rejects unsupported or oversized files", () => {
    const pdf = new File(["%PDF-1.7"], "manual.pdf", { type: "application/pdf", lastModified: 1 });
    const jpg = new File(["jpeg"], "receipt.jpg", { type: "image/jpeg", lastModified: 3 });
    const png = new File(["png"], "diagram.png", { type: "image/png", lastModified: 4 });
    const text = new File(["notes"], "notes.txt", { type: "text/plain", lastModified: 2 });
    const oversized = { name: "large.pdf", type: "application/pdf", size: 50 * 1024 * 1024 + 1 } as File;

    expect(mergeDocumentFiles([pdf], [pdf])).toEqual([pdf]);

    const validation = validateDocumentFiles([pdf, jpg, png, text, oversized]);
    expect(validation.accepted).toEqual([pdf, jpg, png]);
    expect(validation.rejectedMessages).toEqual([
      "notes.txt is not a PDF, DOCX, JPG, or PNG file.",
      "large.pdf exceeds the 50 MB upload limit.",
    ]);
  });
});
