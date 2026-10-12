import type { SourceAnchor } from "@/types/api";

export function sourcePageLabel(source: SourceAnchor): string {
  const start = source.page_start ?? source.page;
  const end = source.page_end ?? start;
  if (start === null) return "";
  const unit = source.doc_title.toLowerCase().endsWith(".pptx") ? "Slide" : "Page";
  return end !== null && end !== start ? `${unit}s ${start}-${end}` : `${unit} ${start}`;
}
