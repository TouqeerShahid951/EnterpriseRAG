import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { SourceAnchor } from "../../types/api";
import { EvidenceInspector } from "./EvidenceInspector";

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
  page_end: 4,
  page_start: 4,
  source_regions: [],
};

describe("EvidenceInspector", () => {
  it("links the selected citation to the original source viewer in a new tab", () => {
    const markup = renderToStaticMarkup(
      <EvidenceInspector onClose={vi.fn()} source={source} sourceCount={1} sourceNumber={1} />,
    );

    expect(markup).toContain("Open original source");
    expect(markup).toContain("1 source");
    expect(markup).toContain('href="/source-viewer?docId=doc-1&amp;chunkId=doc-1%3A7"');
    expect(markup).toContain('target="_blank"');
  });

  it("renders exact claim attribution as verified evidence", () => {
    const markup = renderToStaticMarkup(
      <EvidenceInspector
        onClose={vi.fn()}
        source={{
          ...source,
          attribution_status: "complete",
          evidence_windows: [
            {
              claim_id: "claim-1",
              claim: "Records must be retained for seven years.",
              fields: [],
              highlight_ranges: [{ start: 0, end: 41 }],
              kind: "text",
              passage: "Records must be retained for seven years.",
              quote_end: 41,
              quote_start: 0,
              source_end: 41,
              source_start: 0,
              support_score: 0.99,
              support_status: "verified",
              table_title: null,
              truncated_end: false,
              truncated_start: false,
            },
          ],
        }}
        sourceCount={1}
        sourceNumber={1}
      />,
    );

    expect(markup).toContain("Verified supporting passage");
    expect(markup).toContain(">Records must be retained for seven years.</mark>");
    expect(markup).toContain("Show surrounding context");
  });

  it("labels semantic fallback and does not highlight it", () => {
    const markup = renderToStaticMarkup(
      <EvidenceInspector
        onClose={vi.fn()}
        source={{
          ...source,
          attribution_status: "complete",
          evidence_windows: [
            {
              claim_id: "claim-1",
              claim: "Records must be retained for seven years.",
              fields: [],
              highlight_ranges: [],
              kind: "text",
              passage: "The policy contains a records retention schedule.",
              quote_end: null,
              quote_start: null,
              source_end: 49,
              source_start: 0,
              support_score: 0.72,
              support_status: "semantic_fallback",
              table_title: null,
              truncated_end: false,
              truncated_start: false,
            },
          ],
        }}
        sourceCount={1}
        sourceNumber={1}
      />,
    );

    expect(markup).toContain("Likely relevant passage, not verified");
    expect(markup).not.toContain("<mark");
  });

  it("renders structured table evidence with only supporting values highlighted", () => {
    const markup = renderToStaticMarkup(
      <EvidenceInspector
        onClose={vi.fn()}
        source={{
          ...source,
          attribution_status: "complete",
          evidence_windows: [
            {
              claim_id: "claim-1",
              claim: "The R630 uses a 1U form factor.",
              fields: [
                { label: "Model", value: "R630", supports_claim: false },
                { label: "Form factor", value: "1U", supports_claim: true },
              ],
              highlight_ranges: [{ start: 5, end: 7 }],
              kind: "table_row",
              passage: "R630 1U",
              quote_end: 7,
              quote_start: 5,
              source_end: 8,
              source_start: 0,
              support_score: 0.98,
              support_status: "verified",
              table_title: "Server specifications",
              truncated_end: false,
              truncated_start: false,
            },
          ],
        }}
        sourceCount={1}
        sourceNumber={1}
      />,
    );

    expect(markup).toContain("Server specifications");
    expect(markup).toContain("Form factor");
    expect(markup).toContain(">1U</mark>");
    expect(markup).not.toContain(">R630</mark>");
  });

  it("shows pending sources as unverified retrieved context", () => {
    const markup = renderToStaticMarkup(
      <EvidenceInspector
        onClose={vi.fn()}
        source={{
          ...source,
          excerpt: "The R630 supports this form factor.",
          highlight_ranges: [{ start: 23, end: 34 }],
          attribution_status: "pending",
          evidence_windows: [],
        }}
        sourceCount={1}
        sourceNumber={1}
      />,
    );

    expect(markup).toContain("Retrieved context");
    expect(markup).toContain("Claim attribution is still being checked");
    expect(markup).not.toContain("<mark");
  });
});
