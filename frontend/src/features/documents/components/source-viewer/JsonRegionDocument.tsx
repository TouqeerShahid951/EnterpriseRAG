import { useEffect, useState, type ReactNode } from "react";

import { jsonDocumentText, jsonPointerRange, sourceTextMatchRanges, type SourceTextRange } from "@/features/source-viewer/utils/sourceViewer";
import { FallbackNotice } from "@/features/documents/components/source-viewer/DocumentRegionViewerPrimitives";
import { SourceViewerSearch } from "@/features/documents/components/source-viewer/SourceViewerSearch";
import type { CitationTarget } from "@/types/query";

export function JsonRegionDocument({
  buffer,
  fallbackMessage,
  targets,
  toolbarEnd,
}: {
  buffer: ArrayBuffer;
  fallbackMessage: string;
  targets: Array<Extract<CitationTarget, { kind: "json" }>>;
  toolbarEnd?: ReactNode;
}) {
  const { prettyText, rawText } = jsonDocumentText(buffer);
  const displayText = prettyText || rawText;
  const highlight = targets.map((target) => jsonPointerRange(displayText, target.pointer)).find(Boolean) ?? null;
  const [searchQuery, setSearchQuery] = useState("");
  const [searchRanges, setSearchRanges] = useState<SourceTextRange[]>([]);
  const [searchIndex, setSearchIndex] = useState(-1);
  const [searchStatus, setSearchStatus] = useState<string | undefined>();
  const lines = jsonLines(displayText);

  function resetSearch() {
    setSearchRanges([]);
    setSearchIndex(-1);
    setSearchStatus(undefined);
  }

  function runSearch() {
    const query = searchQuery.trim();
    if (!query) {
      resetSearch();
      return;
    }
    const ranges = sourceTextMatchRanges(displayText, query);
    setSearchRanges(ranges);
    setSearchIndex(ranges.length ? 0 : -1);
    setSearchStatus(ranges.length ? undefined : "No matches");
  }

  function goToSearchResult(direction: -1 | 1) {
    if (!searchRanges.length) return;
    setSearchIndex((currentIndex) => (currentIndex + direction + searchRanges.length) % searchRanges.length);
  }

  useEffect(() => {
    if (searchIndex < 0) return;
    requestAnimationFrame(() => document.querySelector<HTMLElement>(".source-viewer-json-search-highlight.is-active")?.scrollIntoView({ block: "center" }));
  }, [searchIndex, searchRanges]);

  const activeSearchRange = searchRanges[searchIndex] ?? null;
  return (
    <div className="source-viewer-document">
      <div className="source-viewer-toolbar">
        <div className="source-viewer-toolbar-main">
          <div className="source-viewer-file-label">JSON source</div>
          <SourceViewerSearch
            onNext={() => goToSearchResult(1)}
            onPrevious={() => goToSearchResult(-1)}
            onQueryChange={(query) => { setSearchQuery(query); resetSearch(); }}
            onSearch={runSearch}
            query={searchQuery}
            resultLabel={searchRanges.length ? `${searchIndex + 1} of ${searchRanges.length}` : undefined}
            status={searchStatus}
          />
        </div>
        <div className="source-viewer-toolbar-end">{toolbarEnd}</div>
      </div>
      {highlight ? null : <FallbackNotice message={fallbackMessage} />}
      <div className="source-viewer-json-scroll">
        <div className="source-viewer-json-document" role="region" aria-label="JSON source preview">
          <div className="source-viewer-json-ruler" aria-hidden="true" />
          <pre className="source-viewer-json-code">
            {lines.map((line) => (
              <span className="source-viewer-json-line" key={line.number}>
                <span className="source-viewer-json-line-number" aria-hidden="true">{line.number}</span>
                <span className="source-viewer-json-line-content">
                  {renderJsonLine(line, highlight, searchRanges, activeSearchRange)}
                </span>
              </span>
            ))}
          </pre>
        </div>
      </div>
    </div>
  );
}

function jsonLines(text: string): Array<{ end: number; number: number; start: number; text: string }> {
  const sourceLines = text.split("\n");
  let offset = 0;
  return sourceLines.map((line, index) => {
    const start = offset;
    const end = start + line.length;
    offset = end + 1;
    return { end, number: index + 1, start, text: line };
  });
}

function renderJsonLine(
  line: { end: number; start: number; text: string },
  highlight: { start: number; end: number } | null,
  searchRanges: SourceTextRange[],
  activeSearchRange: SourceTextRange | null,
) {
  const ranges = [
    ...(highlight && highlight.end > line.start && highlight.start < line.end ? [highlight] : []),
    ...searchRanges.filter((range) => range.end > line.start && range.start < line.end),
  ];
  if (!ranges.length) {
    return <>{renderJsonSyntax(line.text || " ", "plain")}</>;
  }
  const boundaries = new Set([line.start, line.end]);
  for (const range of ranges) {
    boundaries.add(Math.max(line.start, range.start));
    boundaries.add(Math.min(line.end, range.end));
  }
  const offsets = [...boundaries].sort((left, right) => left - right);
  return offsets.slice(0, -1).map((start, index) => {
    const end = offsets[index + 1];
    const content = renderJsonSyntax(line.text.slice(start - line.start, end - line.start), `segment-${start}`);
    const citation = highlight && highlight.start <= start && highlight.end >= end;
    const search = ranges.some((range) => searchRanges.includes(range) && range.start <= start && range.end >= end);
    const active = activeSearchRange && searchRanges.includes(activeSearchRange)
      && activeSearchRange.start <= start && activeSearchRange.end >= end;
    let rendered: ReactNode = content;
    if (citation) rendered = <mark className="source-viewer-json-highlight">{rendered}</mark>;
    if (search) rendered = <mark className={active ? "source-viewer-json-search-highlight is-active" : "source-viewer-json-search-highlight"}>{rendered}</mark>;
    return <span key={`${start}-${end}`}>{rendered}</span>;
  });
}

function renderJsonSyntax(text: string, keyPrefix: string) {
  const nodes: ReactNode[] = [];
  const tokenPattern = /("(?:\\.|[^"\\])*")(\s*:)?|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\b(?:true|false|null)\b|[{}\[\],:]/g;
  let cursor = 0;
  let tokenIndex = 0;
  for (const match of text.matchAll(tokenPattern)) {
    const index = match.index ?? 0;
    if (index > cursor) nodes.push(text.slice(cursor, index));
    if (match[1]) {
      const isKey = Boolean(match[2]);
      nodes.push(
        <span className={isKey ? "source-viewer-json-token-key" : "source-viewer-json-token-string"} key={`${keyPrefix}-${tokenIndex}-string`}>
          {match[1]}
        </span>
      );
      if (match[2]) {
        nodes.push(<span className="source-viewer-json-token-punctuation" key={`${keyPrefix}-${tokenIndex}-colon`}>{match[2]}</span>);
      }
    } else {
      const token = match[0];
      const className = jsonTokenClass(token);
      nodes.push(<span className={className} key={`${keyPrefix}-${tokenIndex}`}>{token}</span>);
    }
    cursor = index + match[0].length;
    tokenIndex += 1;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function jsonTokenClass(token: string): string {
  if (/^-?\d/.test(token)) return "source-viewer-json-token-number";
  if (token === "true" || token === "false") return "source-viewer-json-token-boolean";
  if (token === "null") return "source-viewer-json-token-null";
  return "source-viewer-json-token-punctuation";
}
