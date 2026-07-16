import { FileText } from "lucide-react";
import type { Document, SourceAnchor } from "@/types/api";
import { sourceCitationLabel, sourceCitationName } from "@/features/chat/utils/sourceCitation";
import { sourceDocumentTitle, withSourceDocumentTitle } from "@/features/chat/utils/sourceDocument";
import { sourceMatchedSpanCount, sourceMatchedSpanLabel } from "@/features/chat/utils/sourceEvidence";
import { sourcePageLabel } from "@/features/documents/utils/sourcePage";

export function SourceChip({
  documents,
  onSelectSource,
  selected,
  source,
  sourceNumber,
}: {
  documents: Document[];
  onSelectSource: (source: SourceAnchor | null) => void;
  selected: boolean;
  source: SourceAnchor;
  sourceNumber: number | null;
}) {
  const pageLabel = sourcePageLabel(source);
  const title = sourceDocumentTitle(source, documents);
  const citationLabel = sourceCitationLabel(source);
  const sourceName = sourceCitationName(sourceNumber);
  const matchedSpanCount = sourceMatchedSpanCount(source);
  const matchedSpanLabel = sourceMatchedSpanLabel(source);
  const ariaDetails = [pageLabel, matchedSpanCount > 0 ? matchedSpanLabel : ""].filter(Boolean).join(", ");
  return (
    <button
      type="button"
      onClick={() => onSelectSource(withSourceDocumentTitle(source, documents))}
      className={`rag-source-chip ${selected ? "is-selected" : ""}`}
      aria-label={`Open ${sourceName}: ${title}${ariaDetails ? `, ${ariaDetails}` : ""}`}
      title={`${sourceName} - ${title}${pageLabel ? ` - ${pageLabel}` : ""} - ${citationLabel}`}
    >
      <FileText aria-hidden="true" size={15} />
      <span className="rag-source-chip-copy">
        <span className="rag-source-chip-title">{title}</span>
        <span className="rag-source-chip-meta">
          {pageLabel ? <span>{pageLabel}</span> : null}
          {matchedSpanCount > 0 ? <span>{matchedSpanLabel}</span> : null}
          <span className="rag-source-chip-label">{sourceName}</span>
        </span>
      </span>
    </button>
  );
}
