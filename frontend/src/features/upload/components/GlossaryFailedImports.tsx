import { useMemo, useState } from "react";
import { AlertTriangle, RefreshCw, Search, Trash2 } from "lucide-react";

import type { UploadBatchItemView } from "@/types/chat";

export function GlossaryFailedImports({ deletingDocumentId, items, onDelete, onRetry, retryingJobId }: Props) {
  const [search, setSearch] = useState("");
  const failedItems = useMemo(
    () => items.filter((item) => item.job?.status === "failed" && item.job.documentId),
    [items],
  );
  const visibleItems = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    if (!query) return failedItems;
    return failedItems.filter((item) => `${item.fileName} ${item.job?.errorMessage ?? ""}`.toLocaleLowerCase().includes(query));
  }, [failedItems, search]);

  if (failedItems.length === 0) return null;

  return (
    <section className="sv-card mt-4 overflow-hidden" aria-labelledby="failed-glossary-imports-title">
      <div className="flex flex-wrap items-start justify-between gap-3 p-4">
        <div>
          <p className="sv-eyebrow">Attention needed</p>
          <h2 id="failed-glossary-imports-title" className="sv-section-title mt-1">Failed glossary imports</h2>
          <p className="mt-1 text-body-md text-on-surface-variant">Retry the stored source or move it to Trash before uploading the same file again.</p>
        </div>
        <span className="sv-pill">{failedItems.length} failed</span>
      </div>
      <div className="border-y border-surface-border p-3">
        <label className="relative block">
          <span className="sr-only">Search failed glossary imports</span>
          <Search aria-hidden="true" size={17} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
          <input className="sv-input sv-input-with-leading-icon" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search file name or error" />
        </label>
      </div>
      <ul className="divide-y divide-surface-border" aria-label="Failed glossary imports">
        {visibleItems.map((item) => {
          const documentId = item.job?.documentId;
          const retrying = item.job?.jobId === retryingJobId;
          const deleting = documentId === deletingDocumentId;
          return (
            <li key={item.id} className="flex flex-wrap items-start gap-3 p-4">
              <AlertTriangle aria-hidden="true" className="mt-0.5 shrink-0 text-error-red" size={18} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-bold text-on-surface">{item.fileName}</p>
                <p className="mt-1 text-label-md text-on-surface-variant">{item.job?.errorMessage ?? "Glossary import failed."}</p>
              </div>
              <div className="flex gap-2">
                <button type="button" className="sv-action-secondary" disabled={retrying || deleting} onClick={() => onRetry(item)}>
                  <RefreshCw aria-hidden="true" className={retrying ? "animate-spin" : ""} size={15} /> {retrying ? "Retrying" : "Retry"}
                </button>
                <button type="button" className="sv-action-danger" disabled={retrying || deleting} onClick={() => onDelete(item)}>
                  <Trash2 aria-hidden="true" size={15} /> {deleting ? "Moving" : "Move to Trash"}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
      {visibleItems.length === 0 ? <p className="p-4 text-body-md text-on-surface-variant" role="status">No failed glossary imports match that search.</p> : null}
    </section>
  );
}

type Props = {
  deletingDocumentId: string | null;
  items: UploadBatchItemView[];
  onDelete: (item: UploadBatchItemView) => void;
  onRetry: (item: UploadBatchItemView) => void;
  retryingJobId: string | null;
};
