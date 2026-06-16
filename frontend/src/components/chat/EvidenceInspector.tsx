import { useEffect } from "react";
import { ExternalLink, FileText, X } from "lucide-react";

import { Fact } from "../layout/Common";
import type { SourceAnchor } from "../../types/api";
import { formatDate } from "../../utils/format";
import { sourceCitationLabel, sourceCitationName } from "../../utils/sourceCitation";
import { sourceMatchedSpanCount, sourceMatchedSpanLabel } from "../../utils/sourceEvidence";
import { sourcePageLabel } from "../../utils/sourcePage";
import { sourceViewerHref } from "../../utils/sourceViewer";
import { EvidenceWindows } from "./EvidenceWindows";

export function EvidenceInspector({ onClose, source, sourceCount, sourceNumber }: Props) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="rag-evidence-drawer-shell">
      <button type="button" className="rag-evidence-drawer-backdrop" onClick={onClose} aria-label="Close source evidence panel" />
      <aside className="rag-evidence-panel" aria-label="Source evidence" role="dialog" aria-modal="true">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <p className="sv-eyebrow">Citation Inspector</p>
            <h2 className="text-headline-sm text-on-surface">Evidence</h2>
            <span className="sv-pill mt-2">{sourceCount} sources</span>
          </div>
          <button type="button" onClick={onClose} className="rounded-full p-2 text-secondary hover:bg-surface-container-high hover:text-on-surface" aria-label="Close evidence panel">
            <X size={16} />
          </button>
        </div>
        <SourceEvidence source={source} sourceNumber={sourceNumber} />
      </aside>
    </div>
  );
}

export function MobileEvidencePanel({ onClose, source, sourceCount, sourceNumber }: Props) {
  return (
    <section className="rag-mobile-evidence-panel rounded-lg border border-surface-border bg-surface p-4" aria-label="Source evidence">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="sv-eyebrow">Citation Inspector</p>
          <h2 className="text-headline-sm text-on-surface">Evidence</h2>
          <span className="sv-pill mt-2">{sourceCount} sources</span>
        </div>
        <button type="button" onClick={onClose} className="rounded-full p-2 text-secondary hover:bg-surface-container-high hover:text-on-surface" aria-label="Close evidence panel">
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
  const evidenceSummary = sourceEvidenceSummary(source, matchedSpanCount);
  return (
    <div className="space-y-4">
      <div className="rag-evidence-source-header">
        <span className="rag-evidence-source-icon" aria-hidden="true">
          <FileText size={17} />
        </span>
        <div className="min-w-0">
          <p className="sv-eyebrow">Document</p>
          <h3 className="rag-evidence-source-title">{source.doc_title}</h3>
          <div className="rag-evidence-source-meta">
            {pageLabel ? <span>{pageLabel}</span> : <span>Page unknown</span>}
            {evidenceSummary ? <span>{evidenceSummary}</span> : null}
          </div>
        </div>
      </div>

      <a className="rag-evidence-open-source" href={sourceViewerHref(source)} target="_blank" rel="noreferrer">
        <ExternalLink aria-hidden="true" size={15} />
        Open original source
      </a>

      <EvidenceWindows source={source} />

      <dl className={`grid gap-3 text-body-md ${compact ? "md:grid-cols-3" : ""}`}>
        <Fact label="Citation" value={sourceName} />
        <Fact label="Page Range" value={pageLabel || "Unknown"} />
        <Fact label="Effective" value={formatDate(source.effective_date)} />
        <Fact label="Knowledge Space" value={source.group_path} />
      </dl>
      <span className="sr-only">{citationLabel}</span>
    </div>
  );
}

function sourceEvidenceSummary(source: SourceAnchor, legacyMatchCount: number): string {
  if (source.evidence_windows !== undefined || source.attribution_status !== undefined) {
    const verifiedCount = source.evidence_windows?.filter((window) => window.support_status === "verified").length ?? 0;
    const fallbackCount = source.evidence_windows?.filter((window) => window.support_status === "semantic_fallback").length ?? 0;
    if (verifiedCount > 0) return verifiedCount === 1 ? "1 verified passage" : `${verifiedCount} verified passages`;
    if (fallbackCount > 0) return fallbackCount === 1 ? "1 likely passage" : `${fallbackCount} likely passages`;
    if (source.attribution_status === "pending") return "Attribution pending";
    return "No verified passage";
  }
  return legacyMatchCount > 0 ? sourceMatchedSpanLabel(source) : "Legacy response";
}

type Props = {
  onClose: () => void;
  source: SourceAnchor;
  sourceCount: number;
  sourceNumber: number | null;
};
