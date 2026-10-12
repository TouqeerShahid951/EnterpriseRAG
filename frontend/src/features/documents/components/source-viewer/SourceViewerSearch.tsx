import { ChevronDown, ChevronUp, Search } from "lucide-react";

export interface SourceViewerSearchProps {
  disabled?: boolean;
  isSearching?: boolean;
  onNext?: () => void;
  onPrevious?: () => void;
  onQueryChange: (query: string) => void;
  onSearch: () => void;
  query: string;
  resultLabel?: string;
  status?: string;
}

export function SourceViewerSearch({
  disabled = false,
  isSearching = false,
  onNext,
  onPrevious,
  onQueryChange,
  onSearch,
  query,
  resultLabel,
  status,
}: SourceViewerSearchProps) {
  const canNavigate = !disabled && Boolean(resultLabel);
  return (
    <form className="source-viewer-search" role="search" onSubmit={(event) => { event.preventDefault(); onSearch(); }}>
      <Search aria-hidden="true" className="source-viewer-search-icon" size={16} />
      <label className="sr-only" htmlFor="source-viewer-search-input">Search document</label>
      <input
        id="source-viewer-search-input"
        type="search"
        value={query}
        placeholder="Search document"
        disabled={disabled}
        onChange={(event) => onQueryChange(event.target.value)}
      />
      <button type="submit" disabled={disabled || isSearching} aria-label="Search document" title="Search document">
        {isSearching ? "Searching…" : "Search"}
      </button>
      <span className="source-viewer-search-status" aria-live="polite">{resultLabel ?? status}</span>
      <button
        type="button"
        className="source-viewer-icon-button"
        aria-label="Previous search result"
        title="Previous search result"
        disabled={!canNavigate || !onPrevious}
        onClick={onPrevious}
      >
        <ChevronUp aria-hidden="true" size={16} />
      </button>
      <button
        type="button"
        className="source-viewer-icon-button"
        aria-label="Next search result"
        title="Next search result"
        disabled={!canNavigate || !onNext}
        onClick={onNext}
      >
        <ChevronDown aria-hidden="true" size={16} />
      </button>
    </form>
  );
}
