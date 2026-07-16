import { Search } from "lucide-react";

import { hasActiveDocumentFilters, resultCountLabel } from "@/features/documents/components/library/documentListFormat";
import type { DocumentIngestFilter, DocumentStateFilter } from "@/features/documents/utils/documentPageUtils";
import type { GroupOption } from "@/lib/utils/groups";

type DocumentFiltersProps = {
  ingestFilter: DocumentIngestFilter;
  onClear: () => void;
  resultCount: number;
  search: string;
  setIngestFilter: (value: DocumentIngestFilter) => void;
  setSearch: (value: string) => void;
  setSpaceFilter?: (value: string) => void;
  spaceFilter?: string;
  spaceOptions?: GroupOption[];
  statusFilter: DocumentStateFilter;
  setStatusFilter: (value: DocumentStateFilter) => void;
};

export function DocumentFilters({ ingestFilter, onClear, resultCount, search, setIngestFilter, setSearch, setSpaceFilter, spaceFilter = "", spaceOptions = [], statusFilter, setStatusFilter }: DocumentFiltersProps) {
  const hasFilters = hasActiveDocumentFilters(search, statusFilter, ingestFilter, spaceFilter);
  const showSpaceFilter = Boolean(setSpaceFilter);
  return (
    <div className="knowledge-toolbar">
      <label className="knowledge-toolbar-search relative">
        <span className="sr-only">Filter documents</span>
        <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
        <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter by document name, ID, or space..." className="sv-input sv-input-with-leading-icon" />
      </label>
      <div className={showSpaceFilter ? "knowledge-toolbar-controls knowledge-toolbar-controls-wide" : "knowledge-toolbar-controls"}>
        {setSpaceFilter ? (
          <select value={spaceFilter} onChange={(event) => setSpaceFilter(event.target.value)} className="sv-select sv-filter-select" aria-label="Knowledge Space filter">
            <option value="">All Spaces</option>
            {spaceOptions.map((space) => (
              <option key={space.path} value={space.path}>{space.path}</option>
            ))}
          </select>
        ) : null}
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as DocumentStateFilter)} className="sv-select sv-filter-select" aria-label="Lifecycle filter">
          <option value="all">All Lifecycle</option>
          <option value="current">Current</option>
          <option value="superseded">Superseded</option>
        </select>
        <select value={ingestFilter} onChange={(event) => setIngestFilter(event.target.value as DocumentIngestFilter)} className="sv-select sv-filter-select" aria-label="Ingestion filter">
          <option value="all">All Ingestion</option>
          <option value="indexed">Indexed</option>
          <option value="active">Active Processing</option>
          <option value="processing">Processing</option>
          <option value="human_review">Needs Review</option>
          <option value="cancelled">Cancelled</option>
          <option value="failed">Failed</option>
          <option value="unknown">Unknown</option>
        </select>
      </div>
      <div className="knowledge-toolbar-meta">
        <span>{resultCountLabel(resultCount)}</span>
        <button type="button" className="knowledge-filter-clear" disabled={!hasFilters} onClick={onClear}>
          Clear
        </button>
      </div>
    </div>
  );
}
