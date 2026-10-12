import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type Ref } from "react";
import { BookOpenText, Database, ExternalLink, FileText, X } from "lucide-react";

import { Fact } from "@/components/layout/Common";
import type { SourceAnchor } from "@/types/api";
import { formatDate } from "@/lib/utils/format";
import { sourceCitationLabel } from "@/features/chat/utils/sourceCitation";
import {
  isLiveDatabaseSource,
  isManagedAbbreviationSource,
  sourceMatchedSpanCount,
  sourceMatchedSpanLabel,
} from "@/features/chat/utils/sourceEvidence";
import { sourcePageLabel } from "@/features/documents/utils/sourcePage";
import { sourceViewerHref } from "@/features/source-viewer/utils/sourceViewer";
import { groupSourcesByDocument, type DocumentSourceGroup } from "@/features/chat/utils/sourceGroups";
import { EvidenceWindows } from "./EvidenceWindows";

export function EvidenceInspector({ onClose, returnSessionId, returnTurnId, source, sources }: Props) {
  const group = selectedDocumentGroup(source, sources);
  const citationCountLabel = formatCitationCount(group.citations.length);
  const panelRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const titleId = useId();
  onCloseRef.current = onClose;

  useEffect(() => {
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const modalViewport = window.matchMedia("(min-width: 1181px)");
    const backgroundRegions = Array.from(
      document.querySelectorAll<HTMLElement>(".Prudentia-sidebar, .rag-chat-header, .rag-corpus-rail, .rag-chat-thread"),
    );

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onCloseRef.current();
    }

    window.addEventListener("keydown", handleKeyDown);
    if (modalViewport.matches) {
      backgroundRegions.forEach((element) => element.setAttribute("inert", ""));
      window.requestAnimationFrame(() => closeRef.current?.focus());
    }
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      backgroundRegions.forEach((element) => element.removeAttribute("inert"));
      returnFocusRef.current?.focus({ preventScroll: true });
    };
  }, []);

  function handlePanelKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      panelRef.current?.querySelectorAll<HTMLElement>(
        "button:not([disabled]), a[href], select:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])",
      ) ?? [],
    ).filter((element) => element.offsetParent !== null);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="rag-evidence-drawer-shell">
      <button type="button" className="rag-evidence-drawer-backdrop" onClick={onClose} aria-label="Close source evidence panel" />
      <aside ref={panelRef} className="rag-evidence-panel" aria-labelledby={titleId} role="dialog" aria-modal="true" onKeyDown={handlePanelKeyDown}>
        <div className="rag-evidence-panel-header">
          <div>
            <p className="sv-eyebrow">Citation Inspector</p>
            <h2 id={titleId} className="text-headline-sm text-on-surface">Evidence</h2>
            <span className="sv-pill mt-2">{citationCountLabel}</span>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} className="rag-evidence-close" aria-label="Close evidence panel">
            <X size={16} />
          </button>
        </div>
        <SourceEvidence group={group} returnSessionId={returnSessionId} returnTurnId={returnTurnId} selectedSource={source} />
      </aside>
    </div>
  );
}

export function MobileEvidencePanel({ onClose, panelRef, returnSessionId, returnTurnId, source, sources }: Props & { panelRef?: Ref<HTMLElement> }) {
  const group = selectedDocumentGroup(source, sources);
  const citationCountLabel = formatCitationCount(group.citations.length);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!window.matchMedia("(max-width: 1180px)").matches) return;
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = window.requestAnimationFrame(() => closeRef.current?.focus({ preventScroll: true }));
    return () => {
      window.cancelAnimationFrame(frame);
      returnFocusRef.current?.focus({ preventScroll: true });
    };
  }, []);

  return (
    <section ref={panelRef} className="rag-mobile-evidence-panel rounded-lg border border-surface-border bg-surface p-4" aria-label="Source evidence">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="sv-eyebrow">Citation Inspector</p>
          <h2 className="text-headline-sm text-on-surface">Evidence</h2>
          <span className="sv-pill mt-2">{citationCountLabel}</span>
        </div>
        <button ref={closeRef} type="button" onClick={onClose} className="rag-evidence-close" aria-label="Close evidence panel">
          <X size={16} />
        </button>
      </div>
      <SourceEvidence compact group={group} returnSessionId={returnSessionId} returnTurnId={returnTurnId} selectedSource={source} />
    </section>
  );
}

function SourceEvidence({ compact = false, group, returnSessionId, returnTurnId, selectedSource }: { compact?: boolean; group: DocumentSourceGroup; returnSessionId?: string | null; returnTurnId?: string | null; selectedSource: SourceAnchor }) {
  const [activeChunkId, setActiveChunkId] = useState(selectedSource.chunk_id);
  useEffect(() => setActiveChunkId(selectedSource.chunk_id), [selectedSource.chunk_id]);
  const activeCitation = group.citations.find((citation) => citation.source.chunk_id === activeChunkId) ?? group.citations[0];
  const source = activeCitation.source.chunk_id === selectedSource.chunk_id ? selectedSource : activeCitation.source;
  const pageLabel = sourcePageLabel(source);
  const citationLabel = sourceCitationLabel(source);
  const matchedSpanCount = sourceMatchedSpanCount(source);
  const liveDatabase = isLiveDatabaseSource(source);
  const managedGlossary = isManagedAbbreviationSource(source);
  const structuredSource = liveDatabase || managedGlossary;
  const evidenceSummary = sourceEvidenceSummary(source, matchedSpanCount, structuredSource);
  const SourceIcon = liveDatabase ? Database : managedGlossary ? BookOpenText : FileText;
  return (
    <div className="space-y-4">
      <div className="rag-evidence-source-header">
        <span className="rag-evidence-source-icon" aria-hidden="true">
          <SourceIcon size={17} />
        </span>
        <div className="min-w-0">
          <p className="sv-eyebrow">{liveDatabase ? "Live database" : managedGlossary ? "Managed glossary" : "Document"}</p>
          <h3 className="rag-evidence-source-title">{source.doc_title}</h3>
          <div className="rag-evidence-source-meta">
            {!structuredSource ? (group.pageLabel ? <span>{group.pageLabel}</span> : <span>Page unknown</span>) : null}
            <span>{formatCitationCount(group.citations.length)}</span>
            {group.matchedSpanCount > 0 ? <span>{formatMatchedSpanCount(group.matchedSpanCount)}</span> : null}
          </div>
        </div>
      </div>

      {!structuredSource ? (
        <a className="rag-evidence-open-source" href={sourceViewerHref(source, { sessionId: returnSessionId ?? null, turnId: returnTurnId ?? null, citationChunkIds: group.citations.length > 1 ? group.citations.map((citation) => citation.source.chunk_id) : undefined })} target="_blank" rel="noreferrer">
          <ExternalLink aria-hidden="true" size={15} />
          Open Citation {activeCitation.number} in document preview
        </a>
      ) : null}

      {group.citations.length > 1 ? (
        <section className="rag-evidence-citations" aria-label="Document citations">
          <p className="rag-evidence-section-heading">Citations</p>
          <div className="rag-evidence-citation-tabs">
            {group.citations.map((citation) => {
              const citationPageLabel = sourcePageLabel(citation.source);
              const selected = citation.source.chunk_id === activeCitation.source.chunk_id;
              return (
                <button
                  key={citation.source.chunk_id}
                  type="button"
                  className={`rag-evidence-citation-tab ${selected ? "is-selected" : ""}`}
                  aria-pressed={selected}
                  onClick={() => setActiveChunkId(citation.source.chunk_id)}
                >
                  <span>Citation {citation.number}</span>
                  {citationPageLabel ? <span>{citationPageLabel}</span> : null}
                </button>
              );
            })}
          </div>
        </section>
      ) : null}

      <div className="rag-evidence-active-citation" aria-live="polite">
        <div className="rag-evidence-active-citation-heading">
          <span>Citation {activeCitation.number}</span>
          {evidenceSummary ? <span>{evidenceSummary}</span> : null}
        </div>
        <EvidenceWindows citationChunkIds={group.citations.length > 1 ? group.citations.map((citation) => citation.source.chunk_id) : undefined} key={source.chunk_id} returnSessionId={returnSessionId} returnTurnId={returnTurnId} source={source} />
      </div>

      <dl className={`rag-evidence-facts text-body-md ${compact ? "md:grid-cols-3" : ""}`}>
        <Fact label="Citation" value={`Citation ${activeCitation.number} of ${group.citations.length}`} />
        {!structuredSource ? <Fact label="Page Range" value={pageLabel || "Unknown"} /> : null}
        {!structuredSource ? <Fact label="Effective" value={formatDate(source.effective_date)} /> : null}
        <Fact label="Knowledge Space" value={source.group_path} />
      </dl>
      <span className="sr-only">{citationLabel}</span>
    </div>
  );
}

function selectedDocumentGroup(source: SourceAnchor, sources: SourceAnchor[]): DocumentSourceGroup {
  return groupSourcesByDocument(sources).find((group) => group.docId === source.doc_id)
    ?? groupSourcesByDocument([source])[0];
}

function formatCitationCount(count: number): string {
  return count === 1 ? "1 citation" : `${count} citations`;
}

function formatMatchedSpanCount(count: number): string {
  return count === 1 ? "1 matched evidence span" : `${count} matched evidence spans`;
}

function sourceEvidenceSummary(source: SourceAnchor, legacyMatchCount: number, liveDatabase: boolean): string {
  if (source.evidence_windows !== undefined || source.attribution_status !== undefined) {
    const verifiedCount = source.evidence_windows?.filter((window) => window.support_status === "verified" && source.citation_protocol_version === 1).length ?? 0;
    const matchedCount = source.evidence_windows?.filter((window) => window.support_status === "source_matched").length ?? 0;
    if (matchedCount > 0) return `${matchedCount} source text ${matchedCount === 1 ? "match" : "matches"}`;
    const fallbackCount = source.evidence_windows?.filter((window) => window.support_status === "semantic_fallback").length ?? 0;
    if (verifiedCount > 0) {
      if (liveDatabase) return verifiedCount === 1 ? "1 supported row" : `${verifiedCount} supported rows`;
      return verifiedCount === 1 ? "1 verified passage" : `${verifiedCount} verified passages`;
    }
    if (fallbackCount > 0) {
      if (liveDatabase) return fallbackCount === 1 ? "1 returned row" : `${fallbackCount} returned rows`;
      return fallbackCount === 1 ? "1 likely passage" : `${fallbackCount} likely passages`;
    }
    if (source.attribution_status === "pending") return "Attribution pending";
    return liveDatabase ? "No supported row" : "No verified passage";
  }
  return legacyMatchCount > 0 ? sourceMatchedSpanLabel(source) : "Legacy response";
}

type Props = {
  onClose: () => void;
  returnSessionId?: string | null;
  returnTurnId?: string | null;
  source: SourceAnchor;
  sources: SourceAnchor[];
};
