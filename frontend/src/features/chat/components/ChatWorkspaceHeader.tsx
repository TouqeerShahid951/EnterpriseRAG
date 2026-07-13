import { Database, MessageSquare } from "lucide-react";

export function ChatWorkspaceHeader({ onOpenHistory, savedSessionsTotal }: HeaderProps) {
  return (
    <header className="rag-chat-header">
      <div>
        <p className="sv-eyebrow">Prudentia AI</p>
        <h1 className="sv-page-title">Query Intelligence</h1>
        <p className="mt-1 max-w-3xl text-body-md text-on-surface-variant">
          Ask evidence-grounded questions across your Knowledge Space. Use @ to scope a query to specific documents.
        </p>
      </div>
      <button
        type="button"
        className="rag-mobile-history-trigger"
        data-chat-history-trigger
        onClick={onOpenHistory}
        aria-haspopup="dialog"
        aria-label={`Open chat history, ${savedSessionsTotal} saved conversations`}
      >
        <MessageSquare size={16} aria-hidden="true" />
        <span>History</span>
        {savedSessionsTotal > 0 ? <small>{savedSessionsTotal > 99 ? "99+" : savedSessionsTotal}</small> : null}
      </button>
    </header>
  );
}

type HeaderProps = {
  onOpenHistory: () => void;
  savedSessionsTotal: number;
};

export function ChatKnowledgeSpaceControl({ activeSpacePath, allowAllSpaces = false, documentCount, documentsLoading, onActiveSpaceChange, spaceSwitchDisabled, spaces }: Props) {
  const corpusText = documentsLoading ? "Loading docs" : `${documentCount} document${documentCount === 1 ? "" : "s"}`;
  const activeSpace = spaces.find((space) => space.path === activeSpacePath) ?? null;
  const selectDisabled = spaceSwitchDisabled || (!allowAllSpaces && spaces.length === 0);

  return (
    <div className="rag-space-menu-control">
      <label className="rag-space-switcher">
        <span className="sr-only">Active Knowledge Space</span>
        <select
          aria-label="Active Knowledge Space"
          disabled={selectDisabled}
          onChange={(event) => onActiveSpaceChange(event.target.value || null)}
          value={activeSpacePath ?? ""}
        >
          {allowAllSpaces ? <option value="">All Knowledge Spaces</option> : spaces.length === 0 ? <option value="">No spaces</option> : null}
          {spaces.map((space) => (
            <option key={space.path} value={space.path}>
              {space.name} ({space.documentCount})
            </option>
          ))}
        </select>
      </label>
      <div className="rag-space-meta">
        <small title={activeSpace?.path ?? undefined}>
          {activeSpace?.path ?? (allowAllSpaces ? "All visible spaces" : "No active space")}
        </small>
        <span>
          <Database size={14} aria-hidden="true" />
          {corpusText}
        </span>
      </div>
    </div>
  );
}

type Props = {
  activeSpacePath: string | null;
  allowAllSpaces?: boolean;
  documentCount: number;
  documentsLoading: boolean;
  onActiveSpaceChange: (groupPath: string | null) => void;
  spaceSwitchDisabled: boolean;
  spaces: ChatSpaceOption[];
};

export type ChatSpaceOption = {
  documentCount: number;
  name: string;
  path: string;
};
