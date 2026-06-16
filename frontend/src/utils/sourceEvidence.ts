import type { HighlightRange, SourceAnchor } from "../types/api";

type SourceEvidenceFields = Pick<SourceAnchor, "excerpt" | "highlight_ranges">;

export function normalizeHighlightRanges(excerpt: string, ranges: HighlightRange[]): HighlightRange[] {
  return ranges
    .filter((range) => range.start >= 0 && range.end > range.start && range.end <= excerpt.length)
    .sort((left, right) => left.start - right.start)
    .reduce<HighlightRange[]>((merged, range) => {
      const previous = merged.at(-1);
      if (!previous || range.start > previous.end) return [...merged, { start: range.start, end: range.end }];
      merged[merged.length - 1] = { start: previous.start, end: Math.max(previous.end, range.end) };
      return merged;
    }, []);
}

export function sourceMatchedRanges(source: SourceEvidenceFields): HighlightRange[] {
  return normalizeHighlightRanges(source.excerpt, source.highlight_ranges);
}

export function sourceMatchedSpanCount(source: SourceEvidenceFields): number {
  return sourceMatchedRanges(source).length;
}

export function sourceMatchedSpanLabel(source: SourceEvidenceFields): string {
  const count = sourceMatchedSpanCount(source);
  if (count === 0) return "No matched evidence spans";
  return count === 1 ? "1 matched evidence span" : `${count} matched evidence spans`;
}

export function sourceMatchedSpanTexts(source: SourceEvidenceFields, limit = 4): string[] {
  const seen = new Set<string>();
  const spans: string[] = [];
  for (const range of sourceMatchedRanges(source)) {
    const text = source.excerpt.slice(range.start, range.end).replace(/\s+/g, " ").trim();
    const key = text.toLowerCase();
    if (!text || seen.has(key)) continue;
    seen.add(key);
    spans.push(text);
    if (spans.length >= limit) break;
  }
  return spans;
}
