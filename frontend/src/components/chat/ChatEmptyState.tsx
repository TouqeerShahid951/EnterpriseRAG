import { FileText, MessageSquare, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import type { Document } from "../../types/api";

export function ChatEmptyState({ documents, hasCorpus, onQuestionChange }: Props) {
  const prompts = promptsForDocuments(documents);

  return (
    <section className="sv-card p-5 text-on-surface">
      <div className="flex flex-col gap-5 md:flex-row md:items-start md:justify-between">
        <div className="max-w-2xl">
          <p className="sv-eyebrow">Start with a source-grounded question</p>
          <h2 className="mt-2 text-headline-sm">{hasCorpus ? "Ask against indexed evidence" : "Index a document to start"}</h2>
          <p className="mt-2 text-body-md text-secondary">
            {hasCorpus
              ? "Ask across accessible documents, or type @ in the composer to scope the search to a specific document."
              : "The chat stays disabled until there is at least one current indexed document in your accessible Knowledge Spaces."}
          </p>
        </div>
      </div>
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {hasCorpus ? (
          prompts.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => onQuestionChange(prompt)}
              className="min-h-11 rounded border border-surface-border bg-surface px-3 py-2 text-left text-body-md text-on-surface hover:bg-surface-container-high"
            >
              {prompt}
            </button>
          ))
        ) : (
          <Capability icon={<FileText size={16} />} label="PDF, DOCX, JPG, and PNG ingestion is active" />
        )}
        <Capability icon={<MessageSquare size={16} />} label="Answers stay tied to retrieved chunks" />
        <Capability icon={<ShieldCheck size={16} />} label="Access follows your Knowledge Spaces" />
      </div>
    </section>
  );
}

function Capability({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <div className="flex min-h-11 items-center gap-2 rounded border border-surface-border bg-surface px-3 py-2 text-body-md text-secondary">
      <span className="text-primary">{icon}</span>
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
