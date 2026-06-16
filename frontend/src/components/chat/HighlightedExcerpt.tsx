import type { HighlightRange } from "../../types/api";
import { normalizeHighlightRanges } from "../../utils/sourceEvidence";

export function HighlightedExcerpt({ excerpt, ranges }: { excerpt: string; ranges: HighlightRange[] }) {
  const safeRanges = normalizeHighlightRanges(excerpt, ranges);
  if (safeRanges.length === 0) return <>{excerpt}</>;

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  safeRanges.forEach((range, index) => {
    if (range.start > cursor) parts.push(<span key={`text-${index}`}>{excerpt.slice(cursor, range.start)}</span>);
    parts.push(
      <mark key={`mark-${index}`} className="rounded bg-primary-container px-0.5 text-on-primary-container">
        {excerpt.slice(range.start, range.end)}
      </mark>,
    );
    cursor = range.end;
  });
  if (cursor < excerpt.length) parts.push(<span key="text-end">{excerpt.slice(cursor)}</span>);
  return <>{parts}</>;
}
