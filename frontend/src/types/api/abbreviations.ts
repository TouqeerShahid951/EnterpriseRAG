type AbbreviationSourceKind = "pdf" | "ui";

export type AbbreviationEntry = {
  id: string;
  abbreviation: string;
  expansion: string;
  source_kind: AbbreviationSourceKind;
  source_document_id: string | null;
  source_document_title: string | null;
  source_page: number | null;
  source_count: number;
  revision: number;
  created_at: string | null;
  updated_at: string | null;
};

type AbbreviationGlossary = {
  source_document_id: string | null;
  source_document_title: string | null;
  updated_at: string | null;
};

export type AbbreviationSource = {
  document_id: string;
  document_title: string;
  entry_count: number;
  activated_at: string | null;
};

export type AbbreviationGlossaryResponse = {
  glossary: AbbreviationGlossary | null;
  sources: AbbreviationSource[];
  items: AbbreviationEntry[];
};

export type AbbreviationEntryCreateRequest = {
  abbreviation: string;
  expansion: string;
};

export type AbbreviationEntryUpdateRequest = {
  abbreviation: string;
  expansion: string;
  expected_revision: number;
};
