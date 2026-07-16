import { type ReactNode } from "react";

import { jsonDocumentText, jsonHighlightRange } from "@/features/source-viewer/utils/sourceViewer";
import { FallbackNotice } from "@/features/documents/components/source-viewer/DocumentRegionViewerPrimitives";
import type { DocumentRegion } from "@/features/documents/components/DocumentRegionViewer";
import { sourceTextCandidates } from "@/features/documents/utils/documentRegionViewerUtils";

export function JsonRegionDocument({
  buffer,
  fallbackMessage,
  regions,
  textCandidates,
  toolbarEnd,
}: {
  buffer: ArrayBuffer;
  fallbackMessage: string;
  regions: DocumentRegion[];
  textCandidates?: string[];
  toolbarEnd?: ReactNode;
}) {
  const { prettyText, rawText } = jsonDocumentText(buffer);
  const candidates = sourceTextCandidates(regions, textCandidates);
  const prettyHighlight = jsonHighlightRange(prettyText, candidates);
  const rawHighlight = prettyHighlight ? null : jsonHighlightRange(rawText, candidates);
  const highlight = prettyHighlight ?? rawHighlight;
  const displayText = rawHighlight ? rawText : prettyText || rawText;
  const lines = jsonLines(displayText);
  return (
    <div className="source-viewer-document">
      <div className="source-viewer-toolbar">
        <div className="source-viewer-toolbar-main">
          <div className="source-viewer-file-label">JSON source</div>
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
                  {renderJsonLine(line, highlight)}
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
) {
  if (!highlight || highlight.end <= line.start || highlight.start >= line.end) {
    return <>{renderJsonSyntax(line.text || " ", "plain")}</>;
  }
  const highlightStart = Math.max(0, highlight.start - line.start);
  const highlightEnd = Math.min(line.text.length, highlight.end - line.start);
  return (
    <>
      {renderJsonSyntax(line.text.slice(0, highlightStart), "before")}
      <mark className="source-viewer-json-highlight">{renderJsonSyntax(line.text.slice(highlightStart, highlightEnd), "highlight")}</mark>
      {renderJsonSyntax(line.text.slice(highlightEnd) || " ", "after")}
    </>
  );
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
