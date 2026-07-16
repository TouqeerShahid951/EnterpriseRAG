import type { FormEvent } from "react";
import { Edit3, Plus, Share2, Shuffle, Unlink, X } from "lucide-react";
import { canUnshareTargetSpace } from "@/features/documents/utils/documentPageUtils";
import type { User as AuthUser } from "@/types/api";
import type { GroupOption } from "@/lib/utils/groups";

export type OwnerTransferControlProps = {
  canTransfer: boolean;
  currentGroupPath: string;
  disabled: boolean;
  onTransfer: () => void;
  options: GroupOption[];
  selectedCandidate: string;
  setSelectedCandidate: (path: string) => void;
};

export type ShareControlProps = {
  canEdit: boolean;
  disabled: boolean;
  draft: string[];
  onAdd: (path: string) => void;
  onRemove: (path: string) => void;
  onRevert: () => void;
  onSave: () => void;
  onUnshare: (path: string) => void;
  options: GroupOption[];
  ownerGroupPath: string;
  selectedCandidate: string;
  setSelectedCandidate: (path: string) => void;
  sharesChanged: boolean;
  user: AuthUser;
};

export type TopicEditorProps = {
  changed: boolean;
  disabled: boolean;
  inputValue: string;
  onAdd: (value: string) => void;
  onInputChange: (value: string) => void;
  onRemove: (value: string) => void;
  onRevert: () => void;
  onSave: () => void;
  values: string[];
};

export function OwnerTransferControl({
  canTransfer,
  currentGroupPath,
  disabled,
  onTransfer,
  options,
  selectedCandidate,
  setSelectedCandidate,
}: OwnerTransferControlProps) {
  const canSubmit = canTransfer && Boolean(selectedCandidate) && !disabled;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (canSubmit) onTransfer();
  }

  return (
    <div className="knowledge-topic-editor">
      <label className="sv-field" htmlFor="document-owner-current">
        <span className="sv-label">Current owner</span>
        <input id="document-owner-current" className="sv-input" disabled readOnly value={currentGroupPath} />
      </label>
      {canTransfer ? (
        <form className="knowledge-topic-form" onSubmit={submit}>
          <label className="sv-field" htmlFor="document-owner-space">
            <span className="sv-label">Transfer to</span>
            <select
              id="document-owner-space"
              className="sv-select"
              disabled={disabled || options.length === 0}
              onChange={(event) => setSelectedCandidate(event.target.value)}
              value={selectedCandidate}
            >
              <option value="">Select space</option>
              {options.map((space) => (
                <option key={space.path} value={space.path}>
                  {space.name} {space.path}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="sv-action-primary" disabled={!canSubmit}>
            <Shuffle size={15} /> Transfer Ownership
          </button>
        </form>
      ) : null}
    </div>
  );
}

export function ShareControl({
  canEdit,
  disabled,
  draft,
  onAdd,
  onRemove,
  onRevert,
  onSave,
  onUnshare,
  options,
  ownerGroupPath,
  selectedCandidate,
  setSelectedCandidate,
  sharesChanged,
  user,
}: ShareControlProps) {
  const canAdd = canEdit && Boolean(selectedCandidate) && !disabled;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (canAdd) onAdd(selectedCandidate);
  }

  if (!canEdit) {
    if (!draft.length) return <p className="text-body-md text-secondary">No shared Knowledge Spaces.</p>;
    return (
      <div className="knowledge-topic-chips">
        {draft.map((path) => (
          <span key={path} className="sv-pill knowledge-topic-pill">
            {path}
            {canUnshareTargetSpace(user, path) ? (
              <button type="button" disabled={disabled} onClick={() => onUnshare(path)} aria-label={`Remove ${path}`} title="Remove from this Knowledge Space">
                <Unlink size={13} />
              </button>
            ) : null}
          </span>
        ))}
      </div>
    );
  }

  return (
    <div className="knowledge-topic-editor">
      {draft.length ? (
        <div className="knowledge-topic-chips">
          {draft.map((path) => (
            <span key={path} className="sv-pill knowledge-topic-pill">
              {path}
              <button type="button" onClick={() => onRemove(path)} disabled={disabled} aria-label={`Remove ${path}`}>
                <X size={13} />
              </button>
            </span>
          ))}
        </div>
      ) : (
        <p className="text-body-md text-secondary">No shared Knowledge Spaces.</p>
      )}
      <form className="knowledge-topic-form" onSubmit={submit}>
        <label className="sv-field" htmlFor="document-share-space">
          <span className="sv-label">Knowledge Space</span>
          <select
            id="document-share-space"
            className="sv-select"
            disabled={disabled || options.length === 0}
            onChange={(event) => setSelectedCandidate(event.target.value)}
            value={selectedCandidate}
          >
            <option value="">Select space</option>
            {options.map((space) => (
              <option key={space.path} value={space.path}>
                {space.path === ownerGroupPath ? `${space.name} (${space.path})` : `${space.name} ${space.path}`}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="sv-action-secondary" disabled={!canAdd}>
          <Plus size={15} /> Add
        </button>
      </form>
      <div className="knowledge-topic-actions">
        <button type="button" className="sv-action-primary" disabled={!sharesChanged || disabled} onClick={onSave}>
          <Share2 size={15} /> Save Sharing
        </button>
        <button type="button" className="sv-action-secondary" disabled={!sharesChanged || disabled} onClick={onRevert}>
          Revert
        </button>
      </div>
    </div>
  );
}

export function TopicEditor({ changed, disabled, inputValue, onAdd, onInputChange, onRemove, onRevert, onSave, values }: TopicEditorProps) {
  const trimmedInput = inputValue.trim();
  const inputExists = values.some((value) => value.toLowerCase() === trimmedInput.toLowerCase());
  const canAdd = Boolean(trimmedInput) && trimmedInput.length <= 80 && !inputExists && values.length < 32 && !disabled;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (canAdd) onAdd(trimmedInput);
  }

  return (
    <div className="knowledge-topic-editor">
      {values.length ? (
        <div className="knowledge-topic-chips">
          {values.map((value) => (
            <span key={value} className="sv-pill knowledge-topic-pill">
              {value}
              <button type="button" onClick={() => onRemove(value)} disabled={disabled} aria-label={`Remove ${value}`}>
                <X size={13} />
              </button>
            </span>
          ))}
        </div>
      ) : (
        <p className="text-body-md text-secondary">No topics saved yet.</p>
      )}
      <form className="knowledge-topic-form" onSubmit={submit}>
        <label className="sv-field" htmlFor="document-topic-input">
          <span className="sv-label">Topic</span>
          <input
            id="document-topic-input"
            className="sv-input"
            disabled={disabled || values.length >= 32}
            maxLength={80}
            onChange={(event) => onInputChange(event.target.value)}
            placeholder="Add topic"
            value={inputValue}
          />
        </label>
        <button type="submit" className="sv-action-secondary" disabled={!canAdd}>
          <Plus size={15} /> Add
        </button>
      </form>
      <div className="knowledge-topic-actions">
        <button type="button" className="sv-action-primary" disabled={!changed || disabled} onClick={onSave}>
          <Edit3 size={15} /> Save Topics
        </button>
        <button type="button" className="sv-action-secondary" disabled={!changed || disabled} onClick={onRevert}>
          Revert
        </button>
      </div>
    </div>
  );
}
