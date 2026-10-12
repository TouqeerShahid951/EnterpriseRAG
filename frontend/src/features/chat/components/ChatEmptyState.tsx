import { ArrowUpRight, FileOutput, ScanSearch, Search, ShieldCheck, Upload } from "lucide-react";
import type { ReactNode } from "react";

import { useBranding } from "@/components/brand/BrandContext";
import { canAccessRoute } from "@/routes/routes";
import type { NavigateOptions, RouteId } from "@/routes/routes";
import type { User as AuthUser } from "@/types/api";

export function ChatEmptyState({ composer, hasCorpus, onFocusComposer, onNavigate, user }: Props) {
  const branding = useBranding();
  const canUploadDocuments = canAccessRoute(user, "upload");
  const canReviewDocuments = canAccessRoute(user, "review");
  const canStartAsking = hasCorpus || canUploadDocuments;

  return (
    <section className="rag-empty-state" aria-labelledby="rag-empty-title">
      <div className="rag-empty-intro">
        <p className="rag-empty-eyebrow">Grounded workspace</p>
        <h2 id="rag-empty-title">How can {branding.app_name} help you today?</h2>
        <p>Ask grounded questions across approved documents and live data.</p>
      </div>

      <div className="rag-empty-composer">{composer}</div>

      <p className="rag-empty-trust">
        <ShieldCheck size={15} aria-hidden="true" />
        Answers are grounded in your active Knowledge Space and obey clearance and policy.
      </p>

      <div className="rag-empty-actions" aria-label="Query workspace actions">
        <ActionCard
          description={hasCorpus ? "Get cited answers with source anchors, follow-up questions, and conflict warnings." : canUploadDocuments ? "No indexed documents yet. Start with a governed upload." : "No indexed documents are available in your scope."}
          disabled={!canStartAsking}
          icon={<Search size={20} aria-hidden="true" />}
          label="Ask indexed evidence"
          onClick={() => (hasCorpus ? onFocusComposer() : onNavigate("upload"))}
          tone="query"
        />
        {canUploadDocuments ? (
          <ActionCard
            description="Add files with metadata, clearance, and retention. Track ingestion jobs and parsing outcomes."
            icon={<Upload size={20} aria-hidden="true" />}
            label="Upload governed documents"
            onClick={() => onNavigate("upload")}
            tone="upload"
          />
        ) : null}
        {canReviewDocuments ? (
          <ActionCard
            description="Validate OCR confidence, correct extracted content, and approve or reject items before indexing."
            icon={<ScanSearch size={20} aria-hidden="true" />}
            label="Review OCR and image queues"
            onClick={() => onNavigate("review")}
            tone="review"
          />
        ) : null}
        <ActionCard
          description="Create DOCX, PDF, or PPTX outputs from evidence-backed content with full traceability."
          icon={<FileOutput size={20} aria-hidden="true" />}
          label="Generate artifacts"
          onClick={onFocusComposer}
          tone="artifact"
        />
      </div>
    </section>
  );
}

function ActionCard({ description, disabled = false, icon, label, onClick, tone }: ActionCardProps) {
  return (
    <button type="button" className={`rag-empty-action rag-empty-action-${tone}`} disabled={disabled} onClick={onClick}>
      <span className="rag-empty-action-icon">{icon}</span>
      <span className="rag-empty-action-copy">
        <strong>{label}</strong>
        <small>{description}</small>
      </span>
      <ArrowUpRight className="rag-empty-action-arrow" size={18} aria-hidden="true" />
    </button>
  );
}

type Props = {
  composer: ReactNode;
  hasCorpus: boolean;
  onFocusComposer: () => void;
  onNavigate: (route: RouteId, options?: NavigateOptions) => void;
  user: AuthUser;
};

type ActionCardProps = {
  description: string;
  disabled?: boolean;
  icon: ReactNode;
  label: string;
  onClick: () => void;
  tone: "artifact" | "query" | "review" | "upload";
};
