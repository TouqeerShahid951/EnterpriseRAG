import type { Document, SourceAnchor } from "@/types/api";

export function sourceDocumentTitle(source: SourceAnchor, documents: Document[]): string {
  return documents.find((document) => document.id === source.doc_id)?.title ?? source.doc_title;
}

export function withSourceDocumentTitle(source: SourceAnchor, documents: Document[]): SourceAnchor {
  const docTitle = sourceDocumentTitle(source, documents);
  return docTitle === source.doc_title ? source : { ...source, doc_title: docTitle };
}
