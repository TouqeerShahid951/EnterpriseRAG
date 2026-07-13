import { useEffect, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronUp, Search, TextSearch } from "lucide-react";

import type { EvidenceField, EvidenceWindow, HighlightRange, SourceAnchor } from "@/types/api";
import { HighlightedExcerpt } from "./HighlightedExcerpt";

export function EvidenceWindows({ source }: { source: SourceAnchor }) {
  const [expanded, setExpanded] = useState(false);
  const windows = source.evidence_windows;
  const isLegacy = windows === undefined && source.attribution_status === undefined;

  useEffect(() => {
    setExpanded(false);
  }, [source.chunk_id, source.doc_id]);

  const verifiedQuoteRanges = verifiedRanges(windows ?? []);

  if (isLegacy) {
    return (
      <section className="rag-evidence-legacy" aria-label="Legacy query matches">
        <div className="rag-evidence-section-heading">
          <span>
            <TextSearch aria-hidden="true" size={14} />
            Legacy query matches
          </span>
        </div>
        <div className="rag-evidence-excerpt">
          <HighlightedExcerpt excerpt={source.excerpt} ranges={source.highlight_ranges} />
        </div>
        <p>These highlights show literal query overlap from an older response. They are not verified claim support.</p>
      </section>
    );
  }

  const hasFocusedWindows = Boolean(windows?.length);
  const canExpand = hasFocusedWindows || source.excerpt.length > 600;

  return (
    <section className="rag-evidence-attribution" aria-label="Claim evidence">
      {hasFocusedWindows ? (
        <div className="rag-evidence-window-list">
          {windows?.map((window) => (
            <EvidenceWindowView key={`${window.claim_id}-${window.source_start}-${window.support_status}`} window={window} />
          ))}
        </div>
      ) : (
        <RetrievedContext source={source} expanded={expanded} />
      )}

      {expanded && hasFocusedWindows ? (
        <div className="rag-evidence-context" aria-label="Surrounding source context">
          <div className="rag-evidence-section-heading">
            <span>Surrounding source context</span>
          </div>
          <div className="rag-evidence-excerpt">
            <HighlightedExcerpt excerpt={source.excerpt} ranges={verifiedQuoteRanges} />
          </div>
        </div>
      ) : null}

      {canExpand ? (
        <button
          type="button"
          className="rag-evidence-context-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? <ChevronUp aria-hidden="true" size={15} /> : <ChevronDown aria-hidden="true" size={15} />}
          {expanded ? "Show focused evidence" : "Show surrounding context"}
        </button>
      ) : null}
    </section>
  );
}

function EvidenceWindowView({ window }: { window: EvidenceWindow }) {
  const verified = window.support_status === "verified";
  const StatusIcon = verified ? CheckCircle2 : Search;
  return (
    <article className={`rag-evidence-window ${verified ? "is-verified" : "is-fallback"}`}>
      <div className="rag-evidence-window-status">
        <span>
          <StatusIcon aria-hidden="true" size={14} />
          {verified ? "Verified supporting passage" : "Likely relevant passage, not verified"}
        </span>
      </div>
      <div className="rag-evidence-claim">
        <span>Supports claim</span>
        <p>{window.claim}</p>
      </div>
      {window.kind === "table_row" && window.fields.length > 0 ? (
        <EvidenceTable fields={window.fields} tableTitle={window.table_title} verified={verified} />
      ) : (
        <p className="rag-evidence-excerpt">
          {window.truncated_start ? <span aria-hidden="true">... </span> : null}
          <HighlightedExcerpt excerpt={window.passage} ranges={verified ? window.highlight_ranges : []} />
          {window.truncated_end ? <span aria-hidden="true"> ...</span> : null}
        </p>
      )}
    </article>
  );
}

function EvidenceTable({
  fields,
  tableTitle,
  verified,
}: {
  fields: EvidenceField[];
  tableTitle: string | null;
  verified: boolean;
}) {
  return (
    <div className="rag-evidence-table-wrap">
      {tableTitle ? <p className="rag-evidence-table-title">{tableTitle}</p> : null}
      <dl className="rag-evidence-table">
        {fields.map((field) => (
          <div key={`${field.label}-${field.value}`}>
            <dt>{field.label}</dt>
            <dd>
              {verified && field.supports_claim ? <mark>{field.value}</mark> : field.value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function RetrievedContext({ expanded, source }: { expanded: boolean; source: SourceAnchor }) {
  const pending = source.attribution_status === "pending";
  const unavailable = source.attribution_status === "unavailable";
  const preview = expanded ? source.excerpt : contextPreview(source.excerpt);
  return (
    <div className="rag-evidence-context">
      <div className="rag-evidence-section-heading">
        <span>
          <TextSearch aria-hidden="true" size={14} />
          Retrieved context
        </span>
      </div>
      <p className="rag-evidence-excerpt">
        {preview}
        {!expanded && preview.length < source.excerpt.length ? <span aria-hidden="true"> ...</span> : null}
      </p>
      <p className="rag-evidence-context-note">
        {pending
          ? "Claim attribution is still being checked. Retrieved context is not verified support."
          : unavailable
            ? "Exact claim attribution was unavailable. This context is not verified support."
            : "No claim-level supporting passage was returned for this source."}
      </p>
    </div>
  );
}

function verifiedRanges(windows: EvidenceWindow[]): HighlightRange[] {
  return windows
    .filter(
      (window) =>
        window.support_status === "verified"
        && window.quote_start !== null
        && window.quote_end !== null,
    )
    .map((window) => ({ start: window.quote_start as number, end: window.quote_end as number }));
}

function contextPreview(excerpt: string): string {
  if (excerpt.length <= 600) return excerpt;
  const boundary = excerpt.lastIndexOf(" ", 600);
  return excerpt.slice(0, boundary > 400 ? boundary : 600).trimEnd();
}
