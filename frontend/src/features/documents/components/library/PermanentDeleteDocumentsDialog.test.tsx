import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { PermanentDeleteDocumentsDialog } from "./PermanentDeleteDocumentsDialog";
import type { Document } from "@/types/api";

describe("PermanentDeleteDocumentsDialog", () => {
  it("renders the typed confirmation inside the application", () => {
    const markup = renderToStaticMarkup(
      <PermanentDeleteDocumentsDialog documents={[_document("doc-1")]} isPending={false} onClose={vi.fn()} onConfirm={vi.fn()} />,
    );

    expect(markup).toContain("Type DELETE to confirm");
    expect(markup).toContain("doc-1.pdf");
    expect(markup).toContain("disabled");
  });

  it("renders the selected count for bulk deletion", () => {
    const markup = renderToStaticMarkup(
      <PermanentDeleteDocumentsDialog documents={[_document("doc-1"), _document("doc-2")]} isPending={false} onClose={vi.fn()} onConfirm={vi.fn()} />,
    );

    expect(markup).toContain("Type DELETE 2 to confirm");
    expect(markup).toContain("2 selected documents");
  });
});

function _document(id: string): Document {
  return {
    id,
    title: `${id}.pdf`,
    doc_type: "abbreviation_glossary",
    group_path: "/test",
    owner_group_path: "/test",
    shared_group_paths: [],
    access_group_paths: ["/test"],
    governance_owner: "space",
    clearance_level: "NATO_UNCLASSIFIED",
    effective_date: null,
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
    is_current: false,
    ingest_status: "complete",
    uploaded_by: "user-1",
    superseded_by: null,
    deleted_at: "2026-08-28T00:00:00Z",
    created_at: "2026-08-28T00:00:00Z",
  };
}
