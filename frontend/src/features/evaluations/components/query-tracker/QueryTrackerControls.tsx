import { Database, FileText, Layers3, Loader2, Play, Search, ShieldCheck, Square, XCircle, type LucideIcon } from "lucide-react";

import { InlineMessage, Skeleton } from "@/components/layout/Common";
import type { QuerySourceMode } from "@/types/api";
import type { QueryTrackerControlsViewModel } from "./useQueryTrackerController";

const SOURCE_MODES: Array<{ mode: QuerySourceMode; label: string; icon: LucideIcon }> = [
  { mode: "auto", label: "Auto", icon: Search },
  { mode: "corpus_only", label: "Documents", icon: FileText },
  { mode: "db_only", label: "Live DB", icon: Database },
  { mode: "hybrid", label: "Hybrid", icon: Layers3 },
];

export function QueryTrackerControls({ model }: { model: QueryTrackerControlsViewModel }) {
  return (
    <form className="rag-eval-tracker-form" onSubmit={model.onSubmit}>
      <div className="rag-eval-tracker-notice">
        <ShieldCheck size={16} />
        <span>Tracker queries run against the live system and are saved like normal chat queries.</span>
      </div>
      <label className="sv-field">
        <span className="sv-label">Query</span>
        <textarea
          className="sv-textarea rag-eval-tracker-query"
          disabled={model.query.disabled}
          onChange={(event) => model.query.onChange(event.target.value)}
          placeholder="Ask the system a question to trace..."
          rows={4}
          value={model.query.value}
        />
      </label>
      <div className="rag-eval-tracker-controls">
        <label className="sv-field">
          <span className="sv-label">Knowledge Space</span>
          <select
            className="sv-input"
            disabled={model.spaces.disabled}
            onChange={(event) => model.spaces.onChange(event.target.value || null)}
            value={model.spaces.activePath ?? ""}
          >
            {model.spaces.showAllVisible ? <option value="">All visible spaces</option> : null}
            {model.spaces.options.map((space) => (
              <option key={space.path} value={space.path}>
                {space.name} ({space.documentCount})
              </option>
            ))}
          </select>
        </label>
        <div className="sv-field">
          <span className="sv-label">Source mode</span>
          <div className="rag-eval-tracker-source-segments" aria-label="Query source mode">
            {SOURCE_MODES.map(({ mode, label, icon: Icon }) => (
              <button
                key={mode}
                type="button"
                aria-pressed={model.sources.mode === mode}
                className={model.sources.mode === mode ? "active" : ""}
                disabled={model.isRunning}
                onClick={() => model.sources.onModeChange(mode)}
              >
                <Icon size={14} />
                <span>{label}</span>
              </button>
            ))}
          </div>
        </div>
        <label className="sv-field">
          <span className="sv-label">DB source</span>
          <select
            className="sv-input"
            disabled={model.sources.dbSelectDisabled}
            onChange={(event) => model.sources.onQuerySourceChange(event.target.value)}
            value={model.sources.selectedQuerySourceId}
          >
            <option value="">{model.sources.sourcesLoading ? "Loading sources" : model.sources.items.length ? "All visible DB sources" : "No DB sources"}</option>
            {model.sources.items.map((source) => (
              <option key={source.id} value={source.id}>
                {source.name}
              </option>
            ))}
          </select>
        </label>
        <label className="sv-field">
          <span className="sv-label">Document scope</span>
          {model.documents.isLoading ? (
            <Skeleton className="h-28 w-full" />
          ) : (
            <select
              className="sv-input rag-eval-tracker-document-select"
              disabled={model.documents.disabled}
              multiple
              onChange={(event) => model.documents.onChange(Array.from(event.currentTarget.selectedOptions, (option) => option.value))}
              size={Math.min(6, Math.max(3, model.documents.scoped.length))}
              value={model.documents.selectedIds}
            >
              {model.documents.scoped.map((document) => (
                <option key={document.id} value={document.id}>
                  {document.title}
                </option>
              ))}
            </select>
          )}
        </label>
        <label className="rag-eval-tracker-toggle">
          <input
            checked={model.expansion.checked}
            disabled={model.expansion.disabled}
            onChange={(event) => model.expansion.onChange(event.target.checked)}
            type="checkbox"
          />
          <span>
            <strong>Allow source expansion</strong>
            <small>Let the router expand beyond the selected mode when needed.</small>
          </span>
        </label>
      </div>
      {model.documents.selected.length > 0 ? (
        <div className="rag-eval-tracker-scope" aria-label="Selected document scope">
          <span>Scoped documents</span>
          {model.documents.selected.map((document) => (
            <button
              key={document.id}
              type="button"
              disabled={model.isRunning}
              onClick={() => model.documents.onRemove(document.id)}
            >
              <FileText size={13} />
              {document.title}
              <XCircle size={13} />
            </button>
          ))}
        </div>
      ) : null}
      {model.submitHint ? <InlineMessage tone="warning">{model.submitHint}</InlineMessage> : null}
      {model.sources.errorMessage ? <InlineMessage tone="warning">{model.sources.errorMessage}</InlineMessage> : null}
      <div className="rag-eval-tracker-actions">
        <button type="submit" className="sv-action-primary" disabled={!model.canSubmit}>
          {model.isRunning ? <Loader2 className="animate-spin" size={16} /> : <Play size={16} />}
          {model.isRunning ? "Streaming" : "Run query"}
        </button>
        {model.isRunning ? (
          <button type="button" className="sv-action-danger" onClick={model.onCancel}>
            <Square fill="currentColor" size={14} />
            Stop
          </button>
        ) : null}
      </div>
    </form>
  );
}
