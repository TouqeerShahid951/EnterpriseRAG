import { describe, expect, it } from "vitest";

import { compactDocumentTopics, hasActiveDocumentFilters, resultCountLabel, shortDocumentId } from "./documentListFormat";

describe("document list formatting", () => {
  it("truncates long document ids while preserving both ends", () => {
    expect(shortDocumentId("2dba89de-42c9-45ed-8158-475cd298f8b5")).toBe("2dba89de...f8b5");
    expect(shortDocumentId("short-id")).toBe("short-id");
  });

  it("deduplicates and limits visible topics", () => {
    expect(compactDocumentTopics(["Risk", "risk", "AI", "Controls", "Governance"], 3)).toEqual({
      remaining: 1,
      visible: ["Risk", "AI", "Controls"],
    });
  });

  it("detects active document filters", () => {
    expect(hasActiveDocumentFilters("", "all", "all")).toBe(false);
    expect(hasActiveDocumentFilters("invoice", "all", "all")).toBe(true);
    expect(hasActiveDocumentFilters("", "current", "all")).toBe(true);
    expect(hasActiveDocumentFilters("", "all", "failed")).toBe(true);
    expect(hasActiveDocumentFilters("", "all", "all", "/member-space")).toBe(true);
  });

  it("formats result counts", () => {
    expect(resultCountLabel(1)).toBe("1 result");
    expect(resultCountLabel(12)).toBe("12 results");
  });
});
