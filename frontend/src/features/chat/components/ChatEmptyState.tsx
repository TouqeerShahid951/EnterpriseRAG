import { FileText, MessageSquare, Search, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

export function ChatEmptyState({ hasCorpus }: Props) {
  return (
    <section className="rag-empty-state" aria-labelledby="rag-empty-title">
      <div className="rag-empty-copy">
        <span className="rag-empty-icon" aria-hidden="true">
          <Search size={15} strokeWidth={2.4} />
        </span>
        <div>
          <p className="rag-empty-eyebrow">Source-grounded question</p>
          <h2 id="rag-empty-title">{hasCorpus ? "Ask indexed evidence" : "Index a document to start"}</h2>
          <p>
            {hasCorpus
              ? "Ask across accessible documents, or use @ to scope the answer to a document."
              : "Chat unlocks after at least one accessible document is indexed."}
          </p>
        </div>
      </div>

      <div className="rag-empty-capabilities" aria-label="Answer safeguards">
        {hasCorpus ? null : <Capability icon={<FileText size={14} />} label="PDF, DOCX, JPG, PNG, and JSON ingestion is active" />}
        <Capability icon={<MessageSquare size={14} />} label="Answers stay tied to retrieved chunks" />
        <Capability icon={<ShieldCheck size={14} />} label="Access follows Knowledge Spaces" />
      </div>
    </section>
  );
}

function Capability({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <div className="rag-empty-capability">
      <span aria-hidden="true">{icon}</span>
      {label}
    </div>
  );
}

type Props = {
  hasCorpus: boolean;
};
