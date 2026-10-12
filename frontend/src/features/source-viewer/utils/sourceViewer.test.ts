import { describe, expect, it } from "vitest";

import type { SourceAnchor } from "@/types/api";
import {
  clampSourcePage,
  citedSourcePage,
  documentViewerHref,
  fitContentScale,
  fitContentWidthScale,
  fitPdfPageScale,
  fitPdfWidthScale,
  highlightPdfTextLayer,
  jsonDocumentText,
  jsonPointerRange,
  sourcePageFromInput,
  sourceDocumentKind,
  sourceTextMatchPages,
  sourceTextMatchRanges,
  sourceTextCandidates,
  sourceViewerHref,
  sourceViewerParams,
  sourceViewerReturnHref,
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
  citation_targets: [
    {
      bbox: [10, 20, 200, 60],
      confidence: 0.98,
      exact_text: "Records must be retained for seven years.",
      extraction_method: null,
      image_asset_id: null,
      image_source_kind: null,
      kind: "page",
      page: 4,
      region_type: "text",
    },
  ],
};

describe("source viewer utilities", () => {
  it("builds a return link to the originating chat turn", () => {
    const href = sourceViewerHref(source, { sessionId: "session-1", turnId: "turn-1" });

    expect(href).toBe("/source-viewer?docId=doc-1&chunkId=doc-1%3A7&returnSessionId=session-1&returnTurnId=turn-1");
    expect(sourceViewerParams(href.slice(href.indexOf("?")))).toEqual({
      revision: { index_generation_id: null, content_hash: null, evidence_hash: null },
      documentId: "doc-1",
      chunkId: "doc-1:7",
      citationChunkIds: [],
      returnSessionId: "session-1",
      returnTurnId: "turn-1",
    });
    expect(sourceViewerReturnHref(sourceViewerParams(href.slice(href.indexOf("?"))))).toBe("/chat?sessionId=session-1&turnId=turn-1");
    expect(sourceViewerReturnHref(sourceViewerParams("?docId=doc-1&chunkId=doc-1%3A7"))).toBe("/chat");
  });

  it("builds and parses a document-library preview link without a citation", () => {
    const href = documentViewerHref("doc/1");

    expect(href).toBe("/source-viewer?docId=doc%2F1");
    expect(sourceViewerParams(href.slice(href.indexOf("?")))).toEqual({
      revision: { index_generation_id: null, content_hash: null, evidence_hash: null },
      documentId: "doc/1",
      chunkId: null,
      citationChunkIds: [],
      returnSessionId: null,
      returnTurnId: null,
    });
    expect(sourceViewerReturnHref(sourceViewerParams(href.slice(href.indexOf("?"))))).toBe("/documents");
  });

  it("round-trips same-document citation ids for preview navigation", () => {
    const href = sourceViewerHref(source, {
      sessionId: "session-1",
      turnId: "turn-1",
      citationChunkIds: [source.chunk_id, "doc-1:12", source.chunk_id],
    });

    expect(href).toBe("/source-viewer?docId=doc-1&chunkId=doc-1%3A7&citationChunkId=doc-1%3A7&citationChunkId=doc-1%3A12&returnSessionId=session-1&returnTurnId=turn-1");
    expect(sourceViewerParams(href.slice(href.indexOf("?")))?.citationChunkIds).toEqual(["doc-1:7", "doc-1:12"]);
  });

  it("detects every supported document type from media type or filename", () => {
    expect(sourceDocumentKind("application/pdf", "document")).toBe("pdf");
    expect(sourceDocumentKind("", "policy.DOCX")).toBe("docx");
    expect(sourceDocumentKind("", "briefing.PPTX")).toBe("pptx");
    expect(sourceDocumentKind("text/csv", "records")).toBe("spreadsheet");
    expect(sourceDocumentKind("", "records.CSV")).toBe("spreadsheet");
    expect(sourceDocumentKind("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "records")).toBe("spreadsheet");
    expect(sourceDocumentKind("", "records.XLSX")).toBe("spreadsheet");
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
    expect(sourceTextCandidates(source)).toEqual(["Records must be retained for seven years."]);
  });

  it("pretty-prints JSON and resolves an exact JSON pointer even when values repeat", () => {
    const encoded = new TextEncoder().encode('{"first":"open","second":"open"}');
    const { prettyText } = jsonDocumentText(encoded.buffer as ArrayBuffer);
    const range = jsonPointerRange(prettyText, "/second");

    expect(prettyText).toContain('"first": "open"');
    expect(range).not.toBeNull();
    expect(prettyText.slice(range?.start, range?.end)).toBe('"open"');
    expect(range?.start).toBeGreaterThan(prettyText.indexOf('"open"'));
  });

  it("falls back to page one without citation targets", () => {
    const sourceWithoutTargets: SourceAnchor = {
      ...source,
      page: null,
      page_end: null,
      page_start: null,
      citation_targets: [],
    };

    expect(citedSourcePage(sourceWithoutTargets)).toBe(1);
    expect(sourceTextCandidates(sourceWithoutTargets)).toEqual([]);
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

  it("matches text across case and whitespace differences", () => {
    expect(sourceTextMatchRanges("Space\nResources are useful", "space resources")).toEqual([{ start: 0, end: 15 }]);
    expect(sourceTextMatchPages(["first page", "SPACE   RESOURCES", "last page"], "space resources")).toEqual([2]);
    expect(sourceTextMatchPages(["page one"], "")).toEqual([]);
  });

  it("highlights matching PDF text-layer spans and marks the active result", () => {
    const makeTextLayerSpan = (text: string) => {
      const classes = new Set<string>();
      return {
        textContent: text,
        classList: {
          add: (...names: string[]) => names.forEach((name) => classes.add(name)),
          contains: (name: string) => classes.has(name),
          remove: (...names: string[]) => names.forEach((name) => classes.delete(name)),
        },
      } as unknown as HTMLElement;
    };
    const first = makeTextLayerSpan("Space");
    const second = makeTextLayerSpan("Resources");
    const third = makeTextLayerSpan("Other text");

    expect(highlightPdfTextLayer([first, second, third], "space resources", true)).toBe(1);
    expect(first.classList.contains("source-viewer-pdf-search-highlight")).toBe(true);
    expect(first.classList.contains("is-active")).toBe(true);
    expect(second.classList.contains("source-viewer-pdf-search-highlight")).toBe(true);
    expect(third.classList.contains("source-viewer-pdf-search-highlight")).toBe(false);

    expect(highlightPdfTextLayer([first, second, third], "missing", true)).toBe(0);
    expect(first.classList.contains("source-viewer-pdf-search-highlight")).toBe(false);
    expect(first.classList.contains("is-active")).toBe(false);
    expect(second.classList.contains("source-viewer-pdf-search-highlight")).toBe(false);
  });
});

it("round-trips revision constraints and encoded identifiers", () => {
  const revision = { index_generation_id: "generation/2", content_hash: "a".repeat(64), evidence_hash: "b".repeat(64) };
  const href = sourceViewerHref({ ...source, doc_id: "doc/1", ...revision });
  const parsed = sourceViewerParams(href.slice(href.indexOf("?")));
  expect(parsed?.documentId).toBe("doc/1");
  expect(parsed?.revision).toEqual(revision);
});
