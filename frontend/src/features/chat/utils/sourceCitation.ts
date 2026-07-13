import type { SourceAnchor } from "@/types/api";

export function sourceCitationLabel(source: SourceAnchor): string {
  const docPrefix = `${source.doc_id}:`;
  return source.chunk_id.startsWith(docPrefix)
    ? `[${source.chunk_id}]`
    : `[${source.doc_id}:${source.chunk_id}]`;
}

export function sourceCitationDisplayLabel(sourceNumber: number): string {
  return `[${sourceNumber}]`;
}

export function sourceCitationName(sourceNumber: number | null): string {
  return sourceNumber ? `Source ${sourceNumber}` : "Selected source";
}
