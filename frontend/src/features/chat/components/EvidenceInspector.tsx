import { useEffect, useId, useRef, type KeyboardEvent as ReactKeyboardEvent, type Ref } from "react";
import { BookOpenText, Database, ExternalLink, FileText, X } from "lucide-react";

import { Fact } from "@/components/layout/Common";
import type { SourceAnchor } from "@/types/api";
import { formatDate } from "@/lib/utils/format";
import { sourceCitationLabel, sourceCitationName } from "@/features/chat/utils/sourceCitation";
import {
  isLiveDatabaseSource,
  isManagedAbbreviationSource,
  sourceMatchedSpanCount,
  sourceMatchedSpanLabel,
} from "@/features/chat/utils/sourceEvidence";
import { sourcePageLabel } from "@/features/documents/utils/sourcePage";
import { sourceViewerHref } from "@/features/source-viewer/utils/sourceViewer";
import { EvidenceWindows } from "./EvidenceWindows";

export function EvidenceInspector({ onClose, source, sourceCount, sourceNumber }: Props) {
  const sourceCountLabel = formatSourceCount(sourceCount);
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
            <span className="sv-pill mt-2">{sourceCountLabel}</span>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} className="rag-evidence-close" aria-label="Close evidence panel">
            <X size={16} />
          </button>
        </div>
        <SourceEvidence source={source} sourceNumber={sourceNumber} />
      </aside>
    </div>
  );
}

export function MobileEvidencePanel({ onClose, panelRef, source, sourceCount, sourceNumber }: Props & { panelRef?: Ref<HTMLElement> }) {
  const sourceCountLabel = formatSourceCount(sourceCount);
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
          <span className="sv-pill mt-2">{sourceCountLabel}</span>
        </div>
        <button ref={closeRef} type="button" onClick={onClose} className="rag-evidence-close" aria-label="Close evidence panel">
          <X size={16} />
        </button>
      </div>
      <SourceEvidence source={source} compact sourceNumber={sourceNumber} />
    </section>
  );
}

function SourceEvidence({ compact = false, source, sourceNumber }: { compact?: boolean; source: SourceAnchor; sourceNumber: number | null }) {
  const pageLabel = sourcePageLabel(source);
  const citationLabel = sourceCitationLabel(source);
  const sourceName = sourceCitationName(sourceNumber);
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
            {!structuredSource ? (pageLabel ? <span>{pageLabel}</span> : <span>Page unknown</span>) : null}
            {evidenceSummary ? <span>{evidenceSummary}</span> : null}
          </div>
        </div>
      </div>

      {!structuredSource ? (
        <a className="rag-evidence-open-source" href={sourceViewerHref(source)} target="_blank" rel="noreferrer">
          <ExternalLink aria-hidden="true" size={15} />
          Open original source
        </a>
      ) : null}

      <EvidenceWindows source={source} />

      <dl className={`rag-evidence-facts text-body-md ${compact ? "md:grid-cols-3" : ""}`}>
        <Fact label="Citation" value={sourceName} />
        {!structuredSource ? <Fact label="Page Range" value={pageLabel || "Unknown"} /> : null}
        {!structuredSource ? <Fact label="Effective" value={formatDate(source.effective_date)} /> : null}
        <Fact label="Knowledge Space" value={source.group_path} />
      </dl>
      <span className="sr-only">{citationLabel}</span>
    </div>
  );
}

function formatSourceCount(count: number): string {
  return count === 1 ? "1 source" : `${count} sources`;
}

function sourceEvidenceSummary(source: SourceAnchor, legacyMatchCount: number, liveDatabase: boolean): string {
  if (source.evidence_windows !== undefined || source.attribution_status !== undefined) {
    const verifiedCount = source.evidence_windows?.filter((window) => window.support_status === "verified").length ?? 0;
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
  source: SourceAnchor;
  sourceCount: number;
  sourceNumber: number | null;
};
