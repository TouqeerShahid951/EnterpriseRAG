import { Children, useMemo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Document, SourceAnchor } from "@/types/api";
import { sourceCitationDisplayLabel, sourceCitationLabel } from "@/features/chat/utils/sourceCitation";
import { sourceDocumentTitle, withSourceDocumentTitle } from "@/features/chat/utils/sourceDocument";
import { sourcePageLabel } from "@/features/documents/utils/sourcePage";

const REMARK_PLUGINS = [remarkGfm];

export function CitedAnswer({ answer, documents, onSelectSource, sources }: Props) {
  const citationsByLabel = useMemo(
    () => new Map(
      sources.map((source, index) => [
        sourceCitationLabel(source),
        {
          displayLabel: sourceCitationDisplayLabel(index + 1),
          source,
        },
      ]),
    ),
    [sources],
  );
  const citationPattern = useMemo(() => citationPatternFor([...citationsByLabel.keys()]), [citationsByLabel]);
  const components = useMemo<Components>(() => {
    const citedChildren = (children: ReactNode) =>
      renderCitedChildren(children, citationPattern, citationsByLabel, documents, onSelectSource);

    return {
      a: ({ children, href }) => (
        <a href={href} rel="noreferrer noopener" target="_blank">
          {citedChildren(children)}
        </a>
      ),
      blockquote: ({ children }) => <blockquote>{citedChildren(children)}</blockquote>,
      code: ({ children, className }) => <code className={className}>{citedChildren(children)}</code>,
      del: ({ children }) => <del>{citedChildren(children)}</del>,
      em: ({ children }) => <em>{citedChildren(children)}</em>,
      h1: ({ children }) => <h3>{citedChildren(children)}</h3>,
      h2: ({ children }) => <h4>{citedChildren(children)}</h4>,
      h3: ({ children }) => <h5>{citedChildren(children)}</h5>,
      h4: ({ children }) => <h6>{citedChildren(children)}</h6>,
      h5: ({ children }) => <h6>{citedChildren(children)}</h6>,
      h6: ({ children }) => <h6>{citedChildren(children)}</h6>,
      img: ({ alt }) => <span className="rag-markdown-image-alt">{alt || "Image"}</span>,
      li: ({ children }) => <li>{citedChildren(children)}</li>,
      p: ({ children }) => <p>{citedChildren(children)}</p>,
      strong: ({ children }) => <strong>{citedChildren(children)}</strong>,
      table: ({ children }) => (
        <div className="rag-markdown-table-wrap">
          <table>{children}</table>
        </div>
      ),
      td: ({ children }) => <td>{citedChildren(children)}</td>,
      th: ({ children }) => <th>{citedChildren(children)}</th>,
    };
  }, [citationPattern, citationsByLabel, documents, onSelectSource]);

  return (
    <div className="rag-markdown">
      <ReactMarkdown components={components} remarkPlugins={REMARK_PLUGINS}>
        {answer}
      </ReactMarkdown>
    </div>
  );
}

function renderCitedChildren(
  children: ReactNode,
  citationPattern: RegExp | null,
  citationsByLabel: Map<string, Citation>,
  documents: Document[],
  onSelectSource: (source: SourceAnchor | null) => void,
): ReactNode {
  if (!citationPattern) return children;
  return Children.map(children, (child, childIndex) => {
    if (typeof child !== "string") return child;
    const parts = child.split(citationPattern);
    if (parts.length === 1) return child;
    return parts.map((part, partIndex) => {
      if (!part) return null;
      const citation = citationsByLabel.get(part);
      if (!citation) return part;
      const title = sourceDocumentTitle(citation.source, documents);
      const page = sourcePageLabel(citation.source);
      return (
        <button
          key={`${part}-${childIndex}-${partIndex}`}
          type="button"
          className="rag-inline-citation"
          onClick={() => onSelectSource(withSourceDocumentTitle(citation.source, documents))}
          aria-label={`Open ${citation.displayLabel}, ${title}${page ? `, ${page}` : ""}`}
          title={`${citation.displayLabel} - ${title}${page ? ` - ${page}` : ""} - ${part}`}
        >
          {citation.displayLabel}
        </button>
      );
    });
  });
}

function citationPatternFor(labels: string[]): RegExp | null {
  if (labels.length === 0) return null;
  const alternatives = labels
    .sort((left, right) => right.length - left.length)
    .map((label) => label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp(`(${alternatives.join("|")})`, "g");
}

type Citation = {
  displayLabel: string;
  source: SourceAnchor;
};

type Props = {
  answer: string;
  documents: Document[];
  onSelectSource: (source: SourceAnchor | null) => void;
  sources: SourceAnchor[];
};
