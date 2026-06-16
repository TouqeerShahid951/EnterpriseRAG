import type { SourceAnchor } from "../types/api";

export function sourcePageLabel(source: SourceAnchor): string {
  const start = source.page_start ?? source.page;
  const end = source.page_end ?? start;
  if (start === null) return "";
  return end !== null && end !== start ? `Pages ${start}-${end}` : `Page ${start}`;
}
