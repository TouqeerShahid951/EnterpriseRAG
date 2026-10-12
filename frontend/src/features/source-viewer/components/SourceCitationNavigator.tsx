import { useId } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import type { SourceAnchor } from "@/types/api";
import { sourcePageLabel } from "@/features/documents/utils/sourcePage";

export function SourceCitationNavigator({ activeIndex, citations, onNext, onPrevious, onSelect }: Props) {
  const selectId = useId();
  if (citations.length < 2) return null;

  return (
    <div className="source-viewer-citation-navigator" role="group" aria-label="Citations in this answer">
      <label htmlFor={selectId}>Citations in this answer</label>
      <select id={selectId} aria-label="Select citation" value={activeIndex} onChange={(event) => onSelect(Number(event.target.value))}>
        {citations.map((citation, index) => (
          <option key={citation.chunk_id} value={index}>
            {`Citation ${index + 1} · ${sourcePageLabel(citation) || "Location unknown"}`}
          </option>
        ))}
      </select>
      <span className="source-viewer-citation-count" aria-live="polite">Citation {activeIndex + 1} of {citations.length}</span>
      <button type="button" aria-label="Previous citation" disabled={activeIndex <= 0} onClick={onPrevious}>
        <ChevronLeft aria-hidden="true" size={15} />
      </button>
      <button type="button" aria-label="Next citation" disabled={activeIndex >= citations.length - 1} onClick={onNext}>
        <ChevronRight aria-hidden="true" size={15} />
      </button>
    </div>
  );
}

type Props = {
  activeIndex: number;
  citations: SourceAnchor[];
  onNext: () => void;
  onPrevious: () => void;
  onSelect: (index: number) => void;
};
