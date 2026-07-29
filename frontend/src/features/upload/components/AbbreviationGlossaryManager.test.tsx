import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ToastProvider } from "@/components/feedback/ToastProvider";
import type { AbbreviationGlossaryResponse } from "@/types/api/abbreviations";
import { AbbreviationGlossaryManager } from "./AbbreviationGlossaryManager";

describe("AbbreviationGlossaryManager", () => {
  it("makes coverage and PDF provenance visible", () => {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
    client.setQueryData<AbbreviationGlossaryResponse>(["abbreviation-glossary"], {
      glossary: {
        source_document_id: "document-1",
        source_document_title: "directorate-glossary.pdf",
        updated_at: "2026-07-18T10:00:00Z",
      },
      sources: [
        {
          document_id: "document-1",
          document_title: "directorate-glossary.pdf",
          entry_count: 1,
          activated_at: "2026-07-18T10:00:00Z",
        },
      ],
      items: [
        {
          id: "entry-1",
          abbreviation: "AD",
          expansion: "Assistant Director",
          source_kind: "pdf",
          source_document_id: "document-1",
          source_document_title: "directorate-glossary.pdf",
          source_page: 4,
          source_count: 1,
          revision: 1,
          created_at: null,
          updated_at: null,
        },
        {
          id: "entry-2",
          abbreviation: "DD",
          expansion: "Deputy Director",
          source_kind: "ui",
          source_document_id: null,
          source_document_title: null,
          source_page: null,
          source_count: 0,
          revision: 1,
          created_at: null,
          updated_at: null,
        },
      ],
    });

    const markup = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <AbbreviationGlossaryManager importStatusKey="" />
        </ToastProvider>
      </QueryClientProvider>,
    );

    expect(markup).toContain("Active definitions");
    expect(markup).toContain("Both the abbreviation and full term are added to retrieval queries");
    expect(markup).toContain("PDF sources");
    expect(markup).toContain("1 active");
    expect(markup).toContain("directorate-glossary.pdf");
    expect(markup).toContain("Page 4");
    expect(markup).toContain("Added here");
  });
});
