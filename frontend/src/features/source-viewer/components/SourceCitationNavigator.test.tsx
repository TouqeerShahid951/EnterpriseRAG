import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { SourceAnchor } from "@/types/api";
import { SourceCitationNavigator } from "./SourceCitationNavigator";

const source = (chunkId: string, page: number): SourceAnchor => ({
  chunk_id: chunkId,
  doc_id: "doc-1",
  doc_title: "Records Policy.pdf",
  effective_date: null,
  excerpt: `Cited passage from page ${page}.`,
  clearance_level: "NATO_RESTRICTED",
  group_path: "/legal",
  highlight_ranges: [],
  page,
  page_end: page,
  page_start: page,
  citation_targets: [],
});

describe("SourceCitationNavigator", () => {
  it("renders the active citation and all same-document choices", () => {
    const markup = renderToStaticMarkup(
      <SourceCitationNavigator
        activeIndex={1}
        citations={[source("doc-1:7", 4), source("doc-1:12", 7)]}
        onNext={vi.fn()}
        onPrevious={vi.fn()}
        onSelect={vi.fn()}
      />,
    );

    expect(markup).toContain("Citations in this answer");
    expect(markup).toContain("Citation 2 of 2");
    expect(markup).toContain('aria-label="Select citation"');
    expect(markup).toContain("Citation 1 · Page 4");
    expect(markup).toContain("Citation 2 · Page 7");
  });
});
