import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { SourceAnchor } from "@/types/api";
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
  citation_targets: [],
};

describe("EvidenceInspector", () => {
  it("links the selected citation to its originating chat turn in a new tab", () => {
    const markup = renderToStaticMarkup(
      <EvidenceInspector onClose={vi.fn()} returnSessionId="session-1" returnTurnId="turn-1" source={source} sources={[source]} />,
    );

    expect(markup).toContain("Open Citation 1 in document preview");
    expect(markup).toContain("1 citation");
    expect(markup).toContain('href="/source-viewer?docId=doc-1&amp;chunkId=doc-1%3A7&amp;returnSessionId=session-1&amp;returnTurnId=turn-1"');
    expect(markup).toContain('target="_blank"');
  });

  it("groups a document's citations and opens on the selected citation", () => {
    const secondSource: SourceAnchor = {
      ...source,
      chunk_id: "doc-1:12",
      excerpt: "A second cited passage.",
      page: 7,
      page_end: 8,
      page_start: 7,
    };
    const markup = renderToStaticMarkup(
      <EvidenceInspector onClose={vi.fn()} source={secondSource} sources={[source, secondSource]} />,
    );

    expect(markup).toContain("2 citations");
    expect(markup).toContain("Pages 4, 7-8");
    expect(markup).toContain("Citation 1");
    expect(markup).toContain("Citation 2");
    expect(markup).toContain("Open Citation 2 in document preview");
    expect(markup).toContain("citationChunkId=doc-1%3A7&amp;citationChunkId=doc-1%3A12");
    expect(markup).toContain("A second cited passage.");
  });

  it("renders exact claim attribution as verified evidence", () => {
    const markup = renderToStaticMarkup(
      <EvidenceInspector
        onClose={vi.fn()}
        source={{
          ...source,
          citation_protocol_version: 1,
          provenance_kind: "native",
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
        sources={[source]}
      />,
    );

    expect(markup).toContain("Verified supporting passage");
    expect(markup).toContain("Supports claim");
    expect(markup).toContain('class="rag-evidence-highlight"');
    expect(markup).toContain(">Records must be retained for seven years.</mark>");
    expect(markup).toContain("Show full retrieved chunk");
  });

  it("labels semantic fallback and does not highlight it", () => {
    const markup = renderToStaticMarkup(
      <EvidenceInspector
        onClose={vi.fn()}
        source={{
          ...source,
          citation_protocol_version: 1,
          provenance_kind: "native",
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
        sources={[source]}
      />,
    );

    expect(markup).toContain("Candidate passage from retrieved chunk — not verified");
    expect(markup).toContain("Related answer claim");
    expect(markup).toContain("Show full retrieved chunk");
    expect(markup).not.toContain("<mark");
  });

  it("renders structured table evidence with only supporting values highlighted", () => {
    const markup = renderToStaticMarkup(
      <EvidenceInspector
        onClose={vi.fn()}
        source={{
          ...source,
          citation_protocol_version: 1,
          provenance_kind: "native",
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
        sources={[source]}
      />,
    );

    expect(markup).toContain("Server specifications");
    expect(markup).toContain("Form factor");
    expect(markup).toContain(">1U</mark>");
    expect(markup).not.toContain(">R630</mark>");
  });

  it("renders an unverified live database row before raw query context", () => {
    const markup = renderToStaticMarkup(
      <EvidenceInspector
        onClose={vi.fn()}
        source={{
          ...source,
          doc_id: "connector-live-scope:catalog-1",
          doc_title: "Live connector query: Approved cases",
          chunk_id: "connector-live-scope:catalog-1:query:0",
          excerpt: "Connector type: postgres\nRows returned: 2\nstatus: open\nSQL: SELECT status FROM cases",
          citation_protocol_version: 1,
          provenance_kind: "native",
          attribution_status: "complete",
          evidence_windows: [
            {
              claim_id: "claim-1",
              claim: "The case is open.",
              fields: [
                { label: "Case", value: "C-101", supports_claim: false },
                { label: "Status", value: "open", supports_claim: true },
              ],
              highlight_ranges: [],
              kind: "table_row",
              passage: "status: open",
              quote_end: null,
              quote_start: null,
              source_end: 12,
              source_start: 0,
              support_score: 0.5,
              support_status: "semantic_fallback",
              table_title: "Approved cases",
              truncated_end: false,
              truncated_start: false,
            },
          ],
          effective_date: null,
          page: null,
          page_end: null,
          page_start: null,
        }}
        sources={[source]}
      />,
    );

    expect(markup).toContain("Live database");
    expect(markup).toContain("1 returned row");
    expect(markup).toContain("Relevant returned row, not verified");
    expect(markup).toContain("Show query context");
    expect(markup).toContain(">open</dd>");
    expect(markup).not.toContain("<mark");
    expect(markup).not.toContain("Open original source");
    expect(markup).not.toContain("Page unknown");
    expect(markup).not.toContain("Page Range");
    expect(markup).not.toContain("Effective");
  });

  it("renders managed glossary evidence without a broken document link", () => {
    const markup = renderToStaticMarkup(
      <EvidenceInspector
        onClose={vi.fn()}
        source={{
          ...source,
          doc_id: "managed-glossary:/legal",
          doc_title: "Managed Abbreviation Glossary",
          chunk_id: "abbreviation:entry-1",
          excerpt: "AD — Assistant Director",
          effective_date: null,
          page: null,
          page_end: null,
          page_start: null,
        }}
        sources={[source]}
      />,
    );

    expect(markup).toContain("Managed glossary");
    expect(markup).toContain("AD — Assistant Director");
    expect(markup).not.toContain("Open original source");
    expect(markup).not.toContain("Page unknown");
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
        sources={[source]}
      />,
    );

    expect(markup).toContain("Retrieved context");
    expect(markup).toContain("Claim attribution is still being checked");
    expect(markup).not.toContain("<mark");
  });
});

it("does not certify historical windows without the citation protocol", () => {
  const legacy: SourceAnchor = { ...source, attribution_status: "complete", evidence_windows: [{
    claim_id: "old", claim: "Old claim", kind: "text", passage: "Records must be retained for seven years.",
    source_start: 0, source_end: 40, quote_start: 0, quote_end: 40,
    support_status: "verified", support_score: 1, truncated_start: false, truncated_end: false,
    table_title: null, fields: [], highlight_ranges: [{ start: 0, end: 40 }],
  }] };
  const markup = renderToStaticMarkup(<EvidenceInspector source={legacy} sources={[legacy]} onClose={vi.fn()} />);
  expect(markup).toContain("not verified");
  expect(markup).not.toContain("Verified supporting passage");
  expect(markup).not.toContain("<mark");
});
