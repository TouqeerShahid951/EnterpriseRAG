import { describe, expect, it } from "vitest";

import type { PdfUploadDraft } from "@/types/chat";
import { ABBREVIATION_GLOSSARY_DOC_TYPE, mergeDocumentFiles, toUploadRequests, validateDocumentFiles, validateGlossaryPdfFiles } from "./pdfUploadBatch";

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
      sharedGroupPaths: ["/legal", "/ops"],
      clearanceLevel: "NATO_SECRET",
      effectiveDate: "2026-06-09",
      expiryDate: "2026-12-31",
      description: "Shared batch context",
      supersedesText: "old-document-id",
    };

    const requests = toUploadRequests(draft);

    expect(requests).toHaveLength(2);
    expect(requests.map((request) => request.file)).toEqual(files);
    expect(requests.every((request) => request.group_path === "/finance")).toBe(true);
    expect(requests.every((request) => request.shared_group_paths?.join(",") === "/legal,/ops")).toBe(true);
    expect(requests.every((request) => request.clearance_level === "NATO_SECRET")).toBe(true);
    expect(requests.every((request) => !("quality_preset" in request))).toBe(true);
    expect(requests.every((request) => request.description === "Shared batch context")).toBe(true);
    expect(requests.every((request) => !("doc_type" in request))).toBe(true);
    expect(requests.every((request) => request.supersedes?.length === 0)).toBe(true);
  });

  it("keeps supersession metadata for a single-document upload", () => {
    const file = new File(["%PDF-1.7"], "replacement.pdf", { type: "application/pdf" });
    const requests = toUploadRequests({
      files: [file],
      groupPath: "/legal",
      sharedGroupPaths: [],
      clearanceLevel: "NATO_RESTRICTED",
      effectiveDate: "2026-06-09",
      expiryDate: "",
      description: "",
      supersedesText: "first-id, second-id",
    });

    expect(requests[0]?.supersedes).toEqual(["first-id", "second-id"]);
  });

  it("sends no effective date when the field is blank", () => {
    const requests = toUploadRequests({
      files: [new File(["pdf"], "report.pdf", { type: "application/pdf" })],
      groupPath: "/finance",
      sharedGroupPaths: [],
      clearanceLevel: "NATO_RESTRICTED",
      effectiveDate: "",
      expiryDate: "",
      description: "",
      supersedesText: "",
    });

    expect(requests[0]?.effective_date).toBeNull();
  });

  it("creates typed glossary requests for multiple PDFs and rejects non-PDF files", () => {
    const pdf = new File(["%PDF-1.7"], "glossary.pdf", { type: "application/pdf" });
    const docx = new File(["docx"], "glossary.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    const draft: PdfUploadDraft = {
      files: [pdf, new File(["%PDF-1.7"], "operations.pdf", { type: "application/pdf" })],
      groupPath: "/legal",
      sharedGroupPaths: [],
      clearanceLevel: "NATO_RESTRICTED",
      effectiveDate: "",
      expiryDate: "",
      description: "Authoritative abbreviations",
      supersedesText: "current-glossary-id",
    };

    const requests = toUploadRequests(draft, ABBREVIATION_GLOSSARY_DOC_TYPE);
    expect(requests).toHaveLength(2);
    expect(requests.every((request) => request.doc_type === ABBREVIATION_GLOSSARY_DOC_TYPE)).toBe(true);
    expect(requests.every((request) => request.supersedes?.length === 0)).toBe(true);
    expect(validateGlossaryPdfFiles([docx]).accepted).toEqual([]);
    expect(validateGlossaryPdfFiles(draft.files).accepted).toEqual(draft.files);
  });

  it("deduplicates selections and rejects unsupported or oversized files", () => {
    const pdf = new File(["%PDF-1.7"], "manual.pdf", { type: "application/pdf", lastModified: 1 });
    const jpg = new File(["jpeg"], "receipt.jpg", { type: "image/jpeg", lastModified: 3 });
    const png = new File(["png"], "diagram.png", { type: "image/png", lastModified: 4 });
    const json = new File(['{"case_id":"FIR-001"}'], "records.json", { type: "application/json", lastModified: 5 });
    const text = new File(["notes"], "notes.txt", { type: "text/plain", lastModified: 2 });
    const oversized = { name: "large.pdf", type: "application/pdf", size: 50 * 1024 * 1024 + 1 } as File;

    expect(mergeDocumentFiles([pdf], [pdf])).toEqual([pdf]);

    const validation = validateDocumentFiles([pdf, jpg, png, json, text, oversized]);
    expect(validation.accepted).toEqual([pdf, jpg, png, json]);
    expect(validation.rejectedMessages).toEqual([
      "notes.txt is not a PDF, DOCX, JPG, PNG, or JSON file.",
      "large.pdf exceeds the 50 MB upload limit.",
    ]);
  });
});
