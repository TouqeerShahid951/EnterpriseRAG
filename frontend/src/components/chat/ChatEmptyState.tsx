import { FileText, MessageSquare, Search, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import type { Document } from "../../types/api";

export function ChatEmptyState({ documents, hasCorpus, onQuestionChange }: Props) {
  const prompts = promptsForDocuments(documents);

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

      {hasCorpus ? (
        <div className="rag-empty-actions">
          {prompts.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => onQuestionChange(prompt)}
              className="rag-empty-prompt"
            >
              {prompt}
            </button>
          ))}
        </div>
      ) : null}

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

function promptsForDocuments(documents: Document[]): string[] {
  const titleText = documents.map((document) => document.title).join(" ").toLowerCase();
  if (titleText.includes("fir")) {
    return [
      "Who is accused in the FIR?",
      "Which offences or sections are mentioned?",
      "Summarize the FIR with citations.",
    ];
  }
  return [
    "Summarize the key facts with citations.",
    "What entities, dates, or obligations are mentioned?",
    "Which source supports the main finding?",
  ];
}

type Props = {
  documents: Document[];
  hasCorpus: boolean;
  onQuestionChange: (value: string) => void;
};
