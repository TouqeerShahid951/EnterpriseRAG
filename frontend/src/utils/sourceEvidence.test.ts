import { describe, expect, it } from "vitest";

import type { SourceAnchor } from "../types/api";
import { sourceCitationDisplayLabel, sourceCitationLabel, sourceCitationName } from "./sourceCitation";
import {
  normalizeHighlightRanges,
  sourceMatchedSpanCount,
  sourceMatchedSpanLabel,
  sourceMatchedSpanTexts,
} from "./sourceEvidence";
import { sourcePageLabel } from "./sourcePage";

describe("source citation presentation", () => {
  it("keeps backend citation labels stable while page ranges use reader-facing labels", () => {
    const source = buildSource({
      chunk_id: "chunk-9",
      page: 4,
      page_start: 4,
      page_end: 6,
    });

    expect(sourceCitationLabel(source)).toBe("[doc-1:chunk-9]");
    expect(sourceCitationDisplayLabel(1)).toBe("[1]");
    expect(sourceCitationName(1)).toBe("Source 1");
    expect(sourcePageLabel(source)).toBe("Pages 4-6");
  });

  it("does not duplicate the document id in citation labels when chunk ids already include it", () => {
    const source = buildSource({ chunk_id: "doc-1:0" });

    expect(sourceCitationLabel(source)).toBe("[doc-1:0]");
  });

  it("normalizes matched evidence ranges before displaying counts and excerpts", () => {
    const source = buildSource({
      excerpt: "Retention period is seven years. Disposal requires approval.",
      highlight_ranges: [
        { start: 0, end: 9 },
        { start: 10, end: 16 },
        { start: 14, end: 25 },
        { start: 500, end: 510 },
      ],
    });

    expect(normalizeHighlightRanges(source.excerpt, source.highlight_ranges)).toEqual([
      { start: 0, end: 9 },
      { start: 10, end: 25 },
    ]);
    expect(sourceMatchedSpanCount(source)).toBe(2);
    expect(sourceMatchedSpanLabel(source)).toBe("2 matched evidence spans");
    expect(sourceMatchedSpanTexts(source)).toEqual(["Retention", "period is seven"]);
  });

  it("uses an explicit empty-state label when no matched spans are available", () => {
    const source = buildSource({ highlight_ranges: [] });

    expect(sourceMatchedSpanCount(source)).toBe(0);
    expect(sourceMatchedSpanLabel(source)).toBe("No matched evidence spans");
    expect(sourceMatchedSpanTexts(source)).toEqual([]);
  });
});

function buildSource(overrides: Partial<SourceAnchor> = {}): SourceAnchor {
  return {
    doc_id: "doc-1",
    doc_title: "Records Policy",
    chunk_id: "doc-1:0",
    page: 4,
    page_start: 4,
    page_end: 4,
    excerpt: "Records must be retained for seven years.",
    group_path: "/legal",
    effective_date: "2026-01-01",
    highlight_ranges: [],
    ...overrides,
  };
}
