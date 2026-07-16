import type { ReactNode } from "react";
import { CheckCircle2, Loader2, RefreshCw, ScanSearch, Upload } from "lucide-react";
import { Skeleton } from "@/components/layout/Common";
import type { RouteId } from "@/routes/routes";

export function ReviewQueueClearState({ onNavigate, onRefresh, refreshing }: { onNavigate: (route: RouteId) => void; onRefresh: () => void; refreshing: boolean }) {
  return (
    <section className="review-clear-state" aria-label="OCR review queue is clear">
      <div className="review-clear-symbol">
        <CheckCircle2 aria-hidden="true" size={30} />
      </div>
      <div className="review-clear-copy">
        <p className="sv-eyebrow">Queue clear</p>
        <h2>No OCR blocks need review</h2>
        <p>Low-confidence extraction blocks will appear here before affected documents continue into the searchable library.</p>
      </div>
      <div className="review-clear-actions">
        <button type="button" onClick={onRefresh} disabled={refreshing} className="sv-action-primary">
          {refreshing ? <Loader2 aria-hidden="true" className="animate-spin" size={16} /> : <RefreshCw aria-hidden="true" size={16} />}
          Refresh queue
        </button>
        <button type="button" onClick={() => onNavigate("upload")} className="sv-action-secondary">
          <Upload aria-hidden="true" size={16} />
          Add documents
        </button>
        <button type="button" onClick={() => onNavigate("document-overview")} className="sv-action-secondary">
          <ScanSearch aria-hidden="true" size={16} />
          Open library
        </button>
      </div>
      <div className="review-clear-strip" aria-label="Review status">
        <ReviewClearFact label="Status" value="Ready" />
        <ReviewClearFact label="Indexing hold" value="None" />
        <ReviewClearFact label="Next queue source" value="OCR confidence checks" />
      </div>
    </section>
  );
}

export function ReviewImageClearState({ onNavigate, onRefresh, refreshing }: { onNavigate: (route: RouteId) => void; onRefresh: () => void; refreshing: boolean }) {
  return (
    <section className="review-clear-state" aria-label="PDF image review queue is clear">
      <div className="review-clear-symbol">
        <CheckCircle2 aria-hidden="true" size={30} />
      </div>
      <div className="review-clear-copy">
        <p className="sv-eyebrow">Queue clear</p>
        <h2>No PDF images need review</h2>
        <p>Large image-analysis batches will pause here so reviewers can choose which images are analyzed or skipped.</p>
      </div>
      <div className="review-clear-actions">
        <button type="button" onClick={onRefresh} disabled={refreshing} className="sv-action-primary">
          {refreshing ? <Loader2 aria-hidden="true" className="animate-spin" size={16} /> : <RefreshCw aria-hidden="true" size={16} />}
          Refresh queue
        </button>
        <button type="button" onClick={() => onNavigate("upload")} className="sv-action-secondary">
          <Upload aria-hidden="true" size={16} />
          Add documents
        </button>
        <button type="button" onClick={() => onNavigate("document-overview")} className="sv-action-secondary">
          <ScanSearch aria-hidden="true" size={16} />
          Open library
        </button>
      </div>
      <div className="review-clear-strip" aria-label="Review status">
        <ReviewClearFact label="Status" value="Ready" />
        <ReviewClearFact label="Indexing hold" value="None" />
        <ReviewClearFact label="Next queue source" value="PDF image batches" />
      </div>
    </section>
  );
}

function ReviewClearFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function ReviewSummaryMetric({ label, loading, value }: { label: string; loading: boolean; value: string }) {
  return (
    <div className="review-summary-metric" aria-busy={loading} data-cursor-glow>
      <span>{label}</span>
      {loading ? (
        <>
          <span className="sr-only">Loading {label.toLowerCase()}</span>
          <Skeleton className="mt-1 h-5 w-12" />
        </>
      ) : <strong>{value}</strong>}
    </div>
  );
}

export function ReviewPlaceholder({ icon, text, title }: { icon: ReactNode; text: string; title: string }) {
  return (
    <div className="review-placeholder">
      <span>{icon}</span>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

export function ReviewFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
