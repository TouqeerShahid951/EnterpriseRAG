import type { SourceAnchor } from "@/types/api";
import type { ChatTurn } from "@/types/chat";
import { sourceMatchedSpanCount } from "@/features/chat/utils/sourceEvidence";

export type DocumentSourceGroup = {
  citations: Array<{ number: number; source: SourceAnchor }>;
  docId: string;
  matchedSpanCount: number;
  pageLabel: string;
};

export function groupSourcesByDocument(sources: SourceAnchor[]): DocumentSourceGroup[] {
  const grouped = new Map<string, Array<{ number: number; source: SourceAnchor }>>();
  sources.forEach((source, index) => {
    const citations = grouped.get(source.doc_id) ?? [];
    if (!citations.some((citation) => citation.source.chunk_id === source.chunk_id)) {
      citations.push({ number: index + 1, source });
    }
    grouped.set(source.doc_id, citations);
  });

  return [...grouped.entries()].map(([docId, citations]) => ({
    citations,
    docId,
    matchedSpanCount: citations.reduce((total, citation) => total + sourceMatchedSpanCount(citation.source), 0),
    pageLabel: groupedPageLabel(citations.map((citation) => citation.source)),
  }));
}

export function sourcesForTurn(turn: ChatTurn | undefined): SourceAnchor[] {
  if (!turn || turn.role !== "assistant") return [];
  if (turn.response) return turn.response.sources;

  const seen = new Set<string>();
  return turn.progress.flatMap((item) => {
    if (!item.source) return [];
    const key = `${item.source.doc_id}:${item.source.chunk_id}`;
    if (seen.has(key)) return [];
    seen.add(key);
    return [item.source];
  });
}

function groupedPageLabel(sources: SourceAnchor[]): string {
  const ranges = sources
    .map((source) => {
      const start = source.page_start ?? source.page;
      const end = source.page_end ?? start;
      return start === null ? null : [Math.min(start, end ?? start), Math.max(start, end ?? start)] as const;
    })
    .filter((range): range is readonly [number, number] => range !== null)
    .sort((left, right) => left[0] - right[0]);
  if (ranges.length === 0) return "";

  const merged: Array<[number, number]> = [];
  for (const [start, end] of ranges) {
    const previous = merged.at(-1);
    if (previous && start <= previous[1] + 1) previous[1] = Math.max(previous[1], end);
    else merged.push([start, end]);
  }

  const slide = sources[0]?.doc_title.toLowerCase().endsWith(".pptx");
  const rangesLabel = merged.map(([start, end]) => start === end ? `${start}` : `${start}-${end}`).join(", ");
  return `${slide ? merged.length === 1 && merged[0][0] === merged[0][1] ? "Slide" : "Slides" : merged.length === 1 && merged[0][0] === merged[0][1] ? "Page" : "Pages"} ${rangesLabel}`;
}
