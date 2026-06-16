import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { Document } from "../../types/api";
import { DocumentDetail } from "./DocumentDetail";

const legacyDocument = {
  id: "doc-1",
  title: "Legacy document",
  doc_type: "report",
  group_path: "/finance",
  effective_date: "2026-05-25",
  expiry_date: null,
  description: null,
  summary: null,
  language: null,
  topics: [],
  llm_topics: [],
  auto_doc_type: null,
  extracted_dates: {},
  metadata_flags: {},
  entities: [],
  cross_references: [],
  claims: [],
  is_current: true,
  uploaded_by: "local",
  superseded_by: null,
  created_at: "2026-05-25T00:00:00Z",
} as unknown as Document;

describe("DocumentDetail", () => {
  it("renders a legacy document response without an ingestion status", () => {
    const markup = renderToStaticMarkup(
      <DocumentDetail
        canDelete={false}
        deleteMutation={{} as never}
        selected={legacyDocument}
        versionsQuery={{ data: { document_id: legacyDocument.id, chain: [] }, isError: false, isLoading: false } as never}
      />,
    );

    expect(markup).toContain("Ingestion Status");
    expect(markup).toContain("Unknown");
  });
});
