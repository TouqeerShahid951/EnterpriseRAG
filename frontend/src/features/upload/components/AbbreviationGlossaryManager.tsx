import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Edit3, FileText, Plus, RefreshCw, Search, Trash2, X } from "lucide-react";

import { useToast } from "@/components/feedback/ToastProvider";
import { EmptyPanel, InlineMessage } from "@/components/layout/Common";
import { Modal } from "@/components/layout/Modal";
import { abbreviationsApi } from "@/lib/api/contracts";
import { errorMessage, formatDateTime } from "@/lib/utils/format";
import type { AbbreviationEntry, AbbreviationSource } from "@/types/api";

type EntryDraft = { abbreviation: string; expansion: string };
const EMPTY_DRAFT: EntryDraft = { abbreviation: "", expansion: "" };

export function AbbreviationGlossaryManager({ importStatusKey }: Props) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<AbbreviationEntry | null>(null);
  const [deleting, setDeleting] = useState<AbbreviationEntry | null>(null);
  const [deletingSource, setDeletingSource] = useState<AbbreviationSource | null>(null);
  const [draft, setDraft] = useState<EntryDraft>(EMPTY_DRAFT);
  const queryKey = ["abbreviation-glossary"] as const;
  const glossaryQuery = useQuery({
    queryKey,
    queryFn: abbreviationsApi.get,
    retry: false,
  });

  useEffect(() => {
    if (importStatusKey) void glossaryQuery.refetch();
    // Refetch when an upload moves between ingestion states.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [importStatusKey]);

  const visibleEntries = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase();
    const items = glossaryQuery.data?.items ?? [];
    if (!normalized) return items;
    return items.filter((entry) =>
      `${entry.abbreviation} ${entry.expansion}`.toLocaleLowerCase().includes(normalized),
    );
  }, [glossaryQuery.data?.items, search]);

  const createMutation = useMutation({
    mutationFn: abbreviationsApi.create,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey });
      setAdding(false);
      setDraft(EMPTY_DRAFT);
      notify({ title: "Abbreviation added", tone: "success" });
    },
  });
  const updateMutation = useMutation({
    mutationFn: ({ entry, value }: { entry: AbbreviationEntry; value: EntryDraft }) =>
      abbreviationsApi.update(entry.id, { ...value, expected_revision: entry.revision }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey });
      setEditing(null);
      setDraft(EMPTY_DRAFT);
      notify({ title: "Abbreviation updated", tone: "success" });
    },
  });
  const deleteMutation = useMutation({
    mutationFn: (entry: AbbreviationEntry) => abbreviationsApi.remove(entry.id, entry.revision),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey });
      setDeleting(null);
      notify({ title: "Abbreviation deleted", tone: "success" });
    },
  });
  const removeSourceMutation = useMutation({
    mutationFn: (source: AbbreviationSource) => abbreviationsApi.removeSource(source.document_id),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey }),
        queryClient.invalidateQueries({ queryKey: ["documents"] }),
      ]);
      setDeletingSource(null);
      notify({ title: "PDF source removed", tone: "success" });
    },
  });

  function beginAdd() {
    setEditing(null);
    setDraft(EMPTY_DRAFT);
    setAdding(true);
  }

  function beginEdit(entry: AbbreviationEntry) {
    setAdding(false);
    setEditing(entry);
    setDraft({ abbreviation: entry.abbreviation, expansion: entry.expansion });
  }

  function cancelDraft() {
    setAdding(false);
    setEditing(null);
    setDraft(EMPTY_DRAFT);
  }

  function submitDraft(event: FormEvent) {
    event.preventDefault();
    if (editing) updateMutation.mutate({ entry: editing, value: draft });
    else createMutation.mutate(draft);
  }

  const mutationError = createMutation.error ?? updateMutation.error ?? deleteMutation.error ?? removeSourceMutation.error;
  const mutationPending = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending || removeSourceMutation.isPending;
  const entries = glossaryQuery.data?.items ?? [];
  const sources = glossaryQuery.data?.sources ?? [];
  const importedCount = entries.filter((entry) => entry.source_kind === "pdf").length;
  const managedCount = entries.length - importedCount;

  return (
    <section className="sv-card overflow-hidden" aria-labelledby="managed-abbreviations-title" aria-busy={glossaryQuery.isLoading}>
      <div className="flex flex-wrap items-start justify-between gap-4 p-5">
        <div className="max-w-2xl">
          <p className="sv-eyebrow">Active definitions</p>
          <h2 id="managed-abbreviations-title" className="sv-section-title mt-1">Terms in use</h2>
          <p className="mt-1 text-body-md text-on-surface-variant">
            Both the abbreviation and full term are added to retrieval queries. Saved changes are active immediately.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="sv-action-secondary" disabled={glossaryQuery.isFetching} onClick={() => void glossaryQuery.refetch()}>
            <RefreshCw aria-hidden="true" className={glossaryQuery.isFetching ? "animate-spin" : ""} size={16} /> Refresh
          </button>
          <button type="button" className="sv-action-primary" disabled={mutationPending || adding} onClick={beginAdd}>
            <Plus aria-hidden="true" size={16} /> Add term
          </button>
        </div>
      </div>

      {!glossaryQuery.isLoading && !glossaryQuery.isError ? (
        <dl className="grid grid-cols-3 border-y border-surface-border bg-surface-container-low">
          <GlossaryMetric label="Total" value={entries.length} />
          <GlossaryMetric label="Imported" value={importedCount} />
          <GlossaryMetric label="Added manually" value={managedCount} />
        </dl>
      ) : null}

      {sources.length > 0 ? (
        <div className="border-b border-surface-border">
          <div className="flex items-center justify-between gap-3 px-4 py-3">
            <div>
              <h3 className="font-bold text-on-surface">PDF sources</h3>
              <p className="text-label-md text-secondary">Each source can be replaced or removed independently.</p>
            </div>
            <span className="sv-pill">{sources.length} active</span>
          </div>
          <ul className="divide-y divide-surface-border" aria-label="Active glossary PDF sources">
            {sources.map((source) => (
              <li key={source.document_id} className="flex items-center gap-3 px-4 py-3 text-body-md">
                <FileText aria-hidden="true" className="shrink-0 text-primary" size={17} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-bold text-on-surface" title={source.document_title}>{source.document_title}</p>
                  <p className="text-label-md text-secondary">{source.entry_count} term{source.entry_count === 1 ? "" : "s"} · Activated {formatDateTime(source.activated_at)}</p>
                </div>
                <button type="button" className="user-row-action user-row-action-danger" disabled={mutationPending} aria-label={`Remove PDF source ${source.document_title}`} onClick={() => setDeletingSource(source)}>
                  <Trash2 aria-hidden="true" size={15} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-3 border-b border-surface-border p-4">
        <label className="relative block min-w-64 max-w-xl flex-1">
          <span className="sr-only">Search abbreviations</span>
          <Search aria-hidden="true" size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
          <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search abbreviation or full term" className="sv-input sv-input-with-leading-icon" />
        </label>
        <p className="text-label-md font-bold text-secondary" role="status" aria-live="polite">
          {search ? `${visibleEntries.length} of ${entries.length} shown` : `${entries.length} total`}
        </p>
      </div>
      {glossaryQuery.isError ? <InlineMessage tone="error">{errorMessage(glossaryQuery.error, "Unable to load this glossary.")}</InlineMessage> : null}
      {mutationError ? <InlineMessage tone="error">{errorMessage(mutationError, "Unable to save the glossary entry.")}</InlineMessage> : null}
      {glossaryQuery.isLoading ? (
        <div className="p-5 text-body-md text-on-surface-variant" role="status">Loading glossary entries…</div>
      ) : adding || visibleEntries.length > 0 ? (
        <form onSubmit={submitDraft}>
          <div className="sv-table-wrap">
            <table className="sv-table abbreviation-glossary-table">
              <thead><tr><th>Abbreviation</th><th>Full term</th><th>Provenance</th><th>Actions</th></tr></thead>
              <tbody>
                {adding ? <DraftRow draft={draft} pending={mutationPending} onCancel={cancelDraft} onChange={setDraft} /> : null}
                {visibleEntries.map((entry) => editing?.id === entry.id ? (
                  <DraftRow key={entry.id} draft={draft} pending={mutationPending} onCancel={cancelDraft} onChange={setDraft} />
                ) : (
                  <tr key={entry.id} className="sv-table-row">
                    <td data-label="Abbreviation"><strong className="text-on-surface">{entry.abbreviation}</strong></td>
                    <td data-label="Full term" className="text-on-surface">{entry.expansion}</td>
                    <td data-label="Provenance">
                      <span className={entry.source_kind === "pdf" ? "sv-pill sv-pill-success" : "sv-pill"}>
                        {entry.source_kind === "pdf" ? "PDF" : "Added here"}
                      </span>
                      {entry.source_page ? <small className="ml-2 text-secondary">Page {entry.source_page}</small> : null}
                      {entry.source_count > 1 ? <small className="ml-2 text-secondary">{entry.source_count} PDFs</small> : null}
                      {entry.source_document_title ? <small className="mt-1 block max-w-60 truncate text-secondary" title={entry.source_document_title}>{entry.source_document_title}</small> : null}
                    </td>
                    <td data-label="Actions">
                      <div className="user-row-actions" role="group" aria-label={`Actions for ${entry.abbreviation}`}>
                        <button type="button" className="user-row-action" disabled={mutationPending} aria-label={`Edit ${entry.abbreviation}`} onClick={() => beginEdit(entry)}><Edit3 aria-hidden="true" size={15} /></button>
                        <button type="button" className="user-row-action user-row-action-danger" disabled={mutationPending} aria-label={`Delete ${entry.abbreviation}`} onClick={() => setDeleting(entry)}><Trash2 aria-hidden="true" size={15} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </form>
      ) : null}
      {!glossaryQuery.isLoading && !glossaryQuery.isError && !adding && visibleEntries.length === 0 ? (
        <div className="p-4"><EmptyPanel>{search ? "No definitions match this search. Try the abbreviation or any word in the full term." : "No definitions yet. Add the first abbreviation here or import a PDF below."}</EmptyPanel></div>
      ) : null}

      <Modal open={Boolean(deleting)} onClose={() => setDeleting(null)} title="Delete abbreviation" description={deleting ? `Remove ${deleting.abbreviation} from query expansion?` : undefined} size="sm">
        <div className="flex justify-end gap-2">
          <button type="button" className="sv-action-secondary" onClick={() => setDeleting(null)}>Cancel</button>
          <button type="button" className="sv-action-danger" disabled={deleteMutation.isPending} onClick={() => deleting && deleteMutation.mutate(deleting)}>Delete</button>
        </div>
      </Modal>
      <Modal open={Boolean(deletingSource)} onClose={() => setDeletingSource(null)} title="Remove PDF source" description={deletingSource ? `Remove ${deletingSource.document_title} and any definitions supplied only by this PDF?` : undefined} size="sm">
        <div className="flex justify-end gap-2">
          <button type="button" className="sv-action-secondary" onClick={() => setDeletingSource(null)}>Cancel</button>
          <button type="button" className="sv-action-danger" disabled={removeSourceMutation.isPending} onClick={() => deletingSource && removeSourceMutation.mutate(deletingSource)}>Remove source</button>
        </div>
      </Modal>
    </section>
  );
}

function GlossaryMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="border-r border-surface-border px-4 py-3 last:border-r-0">
      <dt className="text-label-md font-bold text-secondary">{label}</dt>
      <dd className="mt-1 text-title-md font-extrabold text-on-surface">{value}</dd>
    </div>
  );
}

function DraftRow({ draft, pending, onCancel, onChange }: {
  draft: EntryDraft;
  pending: boolean;
  onCancel: () => void;
  onChange: (value: EntryDraft) => void;
}) {
  return (
    <tr className="sv-table-row">
      <td data-label="Abbreviation"><input required autoFocus maxLength={20} value={draft.abbreviation} onChange={(event) => onChange({ ...draft, abbreviation: event.target.value.toUpperCase() })} placeholder="AD" aria-label="Abbreviation" className="sv-input" /></td>
      <td data-label="Definition"><input required maxLength={240} value={draft.expansion} onChange={(event) => onChange({ ...draft, expansion: event.target.value })} placeholder="Assistant Director" aria-label="Definition" className="sv-input" /></td>
      <td data-label="Provenance"><span className="sv-pill">Added here</span></td>
      <td data-label="Actions">
        <div className="flex flex-wrap gap-2">
          <button type="submit" className="sv-action-primary" disabled={pending}>{pending ? "Saving…" : "Save"}</button>
          <button type="button" className="sv-action-secondary" disabled={pending} onClick={onCancel}><X aria-hidden="true" size={15} /> Cancel</button>
        </div>
      </td>
    </tr>
  );
}

type Props = {
  importStatusKey: string;
};
