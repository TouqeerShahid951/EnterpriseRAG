import { describe, expect, it } from "vitest";

import type { SourceAnchor } from "../types/api";
import {
  clampSourcePage,
  citedSourcePage,
  fitContentScale,
  fitContentWidthScale,
  fitPdfPageScale,
  fitPdfWidthScale,
  jsonDocumentText,
  jsonHighlightRange,
  sourcePageFromInput,
  sourceDocumentKind,
  sourceRegionsForPage,
  sourceTextCandidates,
  sourceViewerHref,
  sourceViewerParams,
  sourceZoomLabel,
  stepSourceZoom,
} from "./sourceViewer";

const source: SourceAnchor = {
  chunk_id: "doc-1:7",
  doc_id: "doc-1",
  doc_title: "Records Policy.pdf",
  effective_date: "2026-01-01",
  excerpt: "Records must be retained for seven years.",
  clearance_level: "NATO_RESTRICTED",
  group_path: "/legal",
  highlight_ranges: [],
  page: 4,
  page_end: 5,
  page_start: 4,
  source_regions: [
    {
      bbox: [10, 20, 200, 60],
      confidence: 0.98,
      page: 4,
      region_type: "text",
      text: "Records must be retained for seven years.",
    },
  ],
};

describe("source viewer utilities", () => {
  it("builds and parses an encoded viewer link", () => {
    const href = sourceViewerHref(source);

    expect(href).toBe("/source-viewer?docId=doc-1&chunkId=doc-1%3A7");
    expect(sourceViewerParams(href.slice(href.indexOf("?")))).toEqual({
      documentId: "doc-1",
      chunkId: "doc-1:7",
    });
  });

  it("detects PDF, DOCX, JSON, JPEG, and PNG content from media type or filename", () => {
    expect(sourceDocumentKind("application/pdf", "document")).toBe("pdf");
    expect(sourceDocumentKind("", "policy.DOCX")).toBe("docx");
    expect(sourceDocumentKind("application/json", "records")).toBe("json");
    expect(sourceDocumentKind("", "records.JSON")).toBe("json");
    expect(sourceDocumentKind("image/jpeg", "scan")).toBe("image");
    expect(sourceDocumentKind("", "photo.JPEG")).toBe("image");
    expect(sourceDocumentKind("image/png", "chart")).toBe("image");
    expect(sourceDocumentKind("", "diagram.PNG")).toBe("image");
    expect(sourceDocumentKind("text/plain", "notes.txt")).toBe("unsupported");
  });

  it("uses cited-page geometry and de-duplicates text-match candidates", () => {
    expect(citedSourcePage(source)).toBe(4);
    expect(sourceRegionsForPage(source, 4)).toHaveLength(1);
    expect(sourceTextCandidates(source)).toEqual(["Records must be retained for seven years."]);
  });

  it("pretty-prints JSON and highlights cited values from JSON evidence excerpts", () => {
    const encoded = new TextEncoder().encode('{"case_id":"FIR-001","accused":"Sajjad Hussain"}');
    const { prettyText } = jsonDocumentText(encoded.buffer as ArrayBuffer);
    const range = jsonHighlightRange(prettyText, [
      "JSON path: cases[0]\naccused: Sajjad Hussain\nJSON path for accused: cases[0].accused",
    ]);

    expect(prettyText).toContain('"case_id": "FIR-001"');
    expect(range).not.toBeNull();
    expect(prettyText.slice(range?.start, range?.end)).toBe("Sajjad Hussain");
  });

  it("falls back to page one and excerpt text for old source anchors", () => {
    const oldSource: SourceAnchor = {
      ...source,
      excerpt: "Legacy excerpt",
      page: null,
      page_end: null,
      page_start: null,
      source_regions: undefined,
    };

    expect(citedSourcePage(oldSource)).toBe(1);
    expect(sourceRegionsForPage(oldSource, 1)).toEqual([]);
    expect(sourceTextCandidates(oldSource)).toEqual(["Legacy excerpt"]);
  });

  it("fits PDF pages within both the available width and height", () => {
    expect(fitPdfPageScale({
      containerHeight: 900,
      containerWidth: 1200,
      pageHeight: 1000,
      pageWidth: 700,
    })).toBeCloseTo(0.868);

    expect(fitPdfPageScale({
      containerHeight: 1200,
      containerWidth: 600,
      pageHeight: 1000,
      pageWidth: 700,
    })).toBeCloseTo(0.8114);
  });

  it("fits PDF pages by width when requested", () => {
    expect(fitPdfWidthScale({
      containerWidth: 1200,
      pageWidth: 700,
    })).toBeCloseTo(1.6685);
  });

  it("fits generic image and document content without exceeding the default actual-size cap", () => {
    expect(fitContentScale({
      containerHeight: 900,
      containerWidth: 1200,
      contentHeight: 600,
      contentWidth: 800,
    })).toBe(1);

    expect(fitContentScale({
      containerHeight: 500,
      containerWidth: 600,
      contentHeight: 1000,
      contentWidth: 800,
    })).toBeCloseTo(0.468);

    expect(fitContentWidthScale({
      containerWidth: 600,
      contentWidth: 800,
    })).toBeCloseTo(0.71);
  });

  it("clamps page input and preserves the current page for invalid values", () => {
    expect(clampSourcePage(0, 10)).toBe(1);
    expect(clampSourcePage(12, 10)).toBe(10);
    expect(sourcePageFromInput("7", 2, 10)).toBe(7);
    expect(sourcePageFromInput("99", 2, 10)).toBe(10);
    expect(sourcePageFromInput("not a page", 2, 10)).toBe(2);
    expect(sourcePageFromInput("7abc", 2, 10)).toBe(2);
  });

  it("steps source zoom through fixed values and formats the label", () => {
    expect(stepSourceZoom(1, "in")).toBe(1.1);
    expect(stepSourceZoom(1, "out")).toBe(0.9);
    expect(stepSourceZoom(2.9, "in")).toBe(3);
    expect(stepSourceZoom(0.1, "out")).toBe(0.25);
    expect(sourceZoomLabel(1.254)).toBe("125%");
  });
});
