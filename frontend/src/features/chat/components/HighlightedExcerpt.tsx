import type { HighlightRange } from "@/types/api";
import { normalizeHighlightRanges } from "@/features/chat/utils/sourceEvidence";

export function HighlightedExcerpt({ excerpt, ranges }: { excerpt: string; ranges: HighlightRange[] }) {
  const characters = Array.from(excerpt);
  const convertedRanges = ranges.filter(({ start, end }) => Number.isInteger(start) && Number.isInteger(end) && start >= 0 && end > start && end <= characters.length).map(({ start, end }) => ({
    start: characters.slice(0, start).join("").length,
    end: characters.slice(0, end).join("").length,
  }));
  const safeRanges = normalizeHighlightRanges(excerpt, convertedRanges);
  if (safeRanges.length === 0) return <>{excerpt}</>;

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  safeRanges.forEach((range, index) => {
    if (range.start > cursor) parts.push(<span key={`text-${index}`}>{excerpt.slice(cursor, range.start)}</span>);
    parts.push(
      <mark key={`mark-${index}`} className="rag-evidence-highlight">
        {excerpt.slice(range.start, range.end)}
      </mark>,
    );
    cursor = range.end;
  });
  if (cursor < excerpt.length) parts.push(<span key="text-end">{excerpt.slice(cursor)}</span>);
  return <>{parts}</>;
}
