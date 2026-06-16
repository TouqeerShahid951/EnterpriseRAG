import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { SourceAnchor } from "../../types/api";
import { sourceCitationLabel } from "../../utils/sourceCitation";
import { CitedAnswer } from "./CitedAnswer";

const source: SourceAnchor = {
  chunk_id: "chunk-7",
  doc_id: "doc-1",
  doc_title: "FIR_02_kidnapping.pdf",
  effective_date: "2026-06-04",
  excerpt: "FIR number 512/24",
  group_path: "/admin",
  highlight_ranges: [],
  page: 1,
  page_end: 1,
  page_start: 1,
};

describe("CitedAnswer", () => {
  it("renders GFM formatting and citations inside tables and lists", () => {
    const citation = sourceCitationLabel(source);
    const answer = [
      "**FIR Comparison**",
      "",
      "| Document | Accused | FIR Number |",
      "| --- | --- | --- |",
      `| FIR 02 | Waseem Akram Butt | 512/24 ${citation} |`,
      "",
      `- The cited FIR is on page 1 ${citation}`,
    ].join("\n");

    const markup = renderToStaticMarkup(
      <CitedAnswer answer={answer} documents={[]} onSelectSource={vi.fn()} sources={[source]} />,
    );

    expect(markup).toContain("<strong>FIR Comparison</strong>");
    expect(markup).toContain('<div class="rag-markdown-table-wrap"><table>');
    expect(markup).toContain("<th>Document</th>");
    expect(markup).toContain("<ul>");
    expect(markup).toContain('class="rag-inline-citation"');
    expect(markup).toContain("Open [1], FIR_02_kidnapping.pdf, Page 1");
  });

  it("does not render raw HTML from an answer", () => {
    const markup = renderToStaticMarkup(
      <CitedAnswer answer={'<script>alert("unsafe")</script>'} documents={[]} onSelectSource={vi.fn()} sources={[]} />,
    );

    expect(markup).not.toContain("<script>");
  });
});
