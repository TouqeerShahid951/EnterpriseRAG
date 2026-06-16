import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { AlertTriangle, Trash2 } from "lucide-react";

import { EmptyPanel, Fact, InlineMessage } from "../../components/layout/Common";
import type { DeleteDocumentResponse, Document, VersionChainResponse } from "../../types/api";
import { errorMessage, formatDate, formatDateTime } from "../../utils/format";

export function DocumentDetail({ canDelete, deleteMutation, detailError, detailLoading, selected, versionsQuery }: Props) {
  const flags = selected?.metadata_flags ?? {};
  const flagEntries = Object.entries(flags).filter(([, value]) => Boolean(value));
  return (
    <aside className="document-detail">
      <p className="sv-eyebrow">Inspector</p>
      <h2 className="mt-1 text-headline-sm text-on-surface">Document Detail</h2>
      {selected ? (
        <div className="mt-6 space-y-5">
          <dl className="space-y-3">
            <Fact label="Title" value={selected.title} />
            <Fact label="Document ID" value={selected.id} />
            <Fact label="Knowledge Space" value={selected.group_path} />
            <Fact label="Ingestion Status" value={labelize(selected.ingest_status)} />
            <Fact label="Uploaded by" value={selected.uploaded_by} />
            <Fact label="Created" value={formatDateTime(selected.created_at)} />
            <Fact label="Effective" value={formatDate(selected.effective_date)} />
            <Fact label="Expires" value={selected.expiry_date ? formatDate(selected.expiry_date) : "No expiry"} />
            <Fact label="Language" value={selected.language || "Unknown"} />
          </dl>
          {detailLoading ? <p className="text-secondary">Loading extracted metadata.</p> : null}
          {detailError ? <InlineMessage tone="warning">{errorMessage(detailError, "Extracted metadata could not be loaded.")}</InlineMessage> : null}
          {selected.description ? <MetadataSection title="Description"><p className="text-body-md text-on-surface-variant">{selected.description}</p></MetadataSection> : null}
          {selected.summary ? <MetadataSection title="Summary"><p className="text-body-md text-on-surface-variant">{selected.summary}</p></MetadataSection> : null}
          {flagEntries.length > 0 ? (
            <MetadataSection title="Metadata Review Flags">
              <div className="space-y-2">
                {flagEntries.map(([key, value]) => (
                  <div key={key} className="rounded border border-warning-amber/25 bg-warning-amber/10 p-3 text-body-md text-on-surface">
                    <div className="flex items-center gap-2 font-bold text-warning-amber"><AlertTriangle size={15} /> {labelize(key)}</div>
                    <pre className="mt-2 whitespace-pre-wrap break-words text-label-md text-on-surface-variant">{JSON.stringify(value, null, 2)}</pre>
                  </div>
                ))}
              </div>
            </MetadataSection>
          ) : null}
          <MetadataSection title="Topics">
            <ChipList values={[...selected.topics, ...selected.llm_topics]} empty="No topics extracted yet." />
          </MetadataSection>
          <MetadataSection title="Entities">
            <KeyValueList
              empty="No entities extracted yet."
              items={selected.entities.slice(0, 12).map((entity) => ({ key: entity.type, value: entity.text }))}
            />
          </MetadataSection>
          <MetadataSection title="Cross References">
            <KeyValueList
              empty="No cross-references extracted yet."
              items={selected.cross_references.slice(0, 12).map((ref) => ({ key: ref.ref_type, value: ref.ref_text }))}
            />
          </MetadataSection>
          <MetadataSection title="Claims">
            <KeyValueList
              empty="No claims extracted yet."
              items={selected.claims.slice(0, 12).map((claim) => ({ key: `${claim.entity}.${claim.attribute}`, value: claim.value }))}
            />
          </MetadataSection>
          <section>
            <h3 className="mb-2 text-body-md font-bold text-on-surface">Version Chain</h3>
            {versionsQuery.isLoading ? <p className="text-secondary">Loading versions.</p> : null}
            {versionsQuery.isError ? <InlineMessage tone="warning">Version history could not be loaded.</InlineMessage> : null}
            {versionsQuery.data?.chain.map((version) => (
              <div key={version.id} className="mb-2 rounded-lg border border-surface-border bg-surface-card p-3 text-body-md">
                <span className="block break-all font-semibold text-on-surface">{version.id}</span>
                <span className={version.is_current ? "sv-pill sv-pill-success mt-2" : "sv-pill mt-2"}>{version.is_current ? "Current" : "Superseded"}</span>
              </div>
            ))}
          </section>
          {canDelete ? (
            <>
              <InlineMessage tone="warning">Permanent deletion removes this document, its indexed chunks, and its uploaded file.</InlineMessage>
              <button
                type="button"
                disabled={deleteMutation.isPending}
                onClick={() => {
                  if (window.confirm(`Permanently delete "${selected.title}"?\n\nThis cannot be undone.`)) {
                    deleteMutation.mutate(selected.id);
                  }
                }}
                className="sv-action-danger w-full disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Trash2 size={16} />
                {deleteMutation.isPending ? "Deleting permanently" : "Permanently delete document"}
              </button>
              {deleteMutation.isError ? <InlineMessage tone="error">{errorMessage(deleteMutation.error, "Delete failed.")}</InlineMessage> : null}
            </>
          ) : null}
        </div>
      ) : (
        <EmptyPanel>No document selected.</EmptyPanel>
      )}
    </aside>
  );
}

type Props = {
  canDelete: boolean;
  deleteMutation: UseMutationResult<DeleteDocumentResponse, Error, string>;
  detailError?: Error | null;
  detailLoading?: boolean;
  selected: Document | null;
  versionsQuery: UseQueryResult<VersionChainResponse, Error>;
};

function MetadataSection({ children, title }: { children: ReactNode; title: string }) {
  return (
    <section>
      <h3 className="mb-2 text-body-md font-bold text-on-surface">{title}</h3>
      {children}
    </section>
  );
}

function ChipList({ empty, values }: { empty: string; values: string[] }) {
  const unique = Array.from(new Set(values.filter(Boolean)));
  if (!unique.length) return <p className="text-body-md text-secondary">{empty}</p>;
  return (
    <div className="flex flex-wrap gap-2">
      {unique.slice(0, 16).map((value) => <span key={value} className="sv-pill">{value}</span>)}
    </div>
  );
}

function KeyValueList({ empty, items }: { empty: string; items: Array<{ key: string; value: string }> }) {
  if (!items.length) return <p className="text-body-md text-secondary">{empty}</p>;
  return (
    <div className="space-y-2">
      {items.map((item, index) => (
        <div key={`${item.key}-${item.value}-${index}`} className="rounded-lg border border-surface-border bg-surface-card p-3 text-body-md">
          <span className="sv-metadata">{item.key}</span>
          <p className="mt-1 break-words font-semibold text-on-surface">{item.value}</p>
        </div>
      ))}
    </div>
  );
}

function labelize(value: string | null | undefined) {
  if (!value) return "Unknown";
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
