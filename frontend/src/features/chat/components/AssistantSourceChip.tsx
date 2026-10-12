import { FileText } from "lucide-react";
import type { Document, SourceAnchor } from "@/types/api";
import { sourceDocumentTitle, withSourceDocumentTitle } from "@/features/chat/utils/sourceDocument";
import type { DocumentSourceGroup } from "@/features/chat/utils/sourceGroups";

export function SourceChip({
  documents,
  group,
  onSelectSource,
  selected,
}: {
  documents: Document[];
  group: DocumentSourceGroup;
  onSelectSource: (source: SourceAnchor | null) => void;
  selected: boolean;
}) {
  const source = group.citations[0].source;
  const title = sourceDocumentTitle(source, documents);
  const citationLabel = group.citations.length === 1 ? "1 citation" : `${group.citations.length} citations`;
  const matchedSpanLabel = group.matchedSpanCount === 1 ? "1 matched evidence span" : `${group.matchedSpanCount} matched evidence spans`;
  const ariaDetails = [citationLabel, group.pageLabel, group.matchedSpanCount > 0 ? matchedSpanLabel : ""].filter(Boolean).join(", ");
  return (
    <button
      type="button"
      onClick={() => onSelectSource(withSourceDocumentTitle(source, documents))}
      className={`rag-source-chip ${selected ? "is-selected" : ""}`}
      aria-label={`Open citations for ${title}${ariaDetails ? `, ${ariaDetails}` : ""}`}
      title={`Open citations for ${title}`}
    >
      <FileText aria-hidden="true" size={15} />
      <span className="rag-source-chip-copy">
        <span className="rag-source-chip-title">{title}</span>
        <span className="rag-source-chip-meta">
          {group.pageLabel ? <span>{group.pageLabel}</span> : null}
          {group.matchedSpanCount > 0 ? <span>{matchedSpanLabel}</span> : null}
          <span className="rag-source-chip-label">{citationLabel}</span>
        </span>
      </span>
    </button>
  );
}
