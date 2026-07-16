import { type Dispatch, type FormEvent, type SetStateAction } from "react";

import { InlineMessage } from "@/components/layout/Common";
import {
  ReadOnlyField,
  TextField,
} from "@/features/documents/components/library/DocumentPagePrimitives";
import type { SpaceDraft } from "@/features/documents/utils/documentPageUtils";
import { errorMessage } from "@/lib/utils/format";
import { groupPathIssue, type GroupOption } from "@/lib/utils/groups";

export type SpacePanelState = { kind: "create-space" } | { kind: "edit-space"; space: GroupOption } | null;

export function SpacePanel({
  draft,
  isCreate,
  isPending,
  mutationError,
  onChange,
  onNameChange,
  onSubmit,
  pathExists,
}: SpacePanelProps) {
  const pathIssue = isCreate ? groupPathIssue(draft.path, pathExists) : null;
  const canSubmit = draft.name.trim().length > 0 && (!isCreate || !pathIssue);

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <TextField autoComplete="off" disabled={isPending} helper="Shown in the folder tree and used to generate the default path." label="Space name" onChange={onNameChange} required value={draft.name} />
      {isCreate ? (
        <div className="sv-field">
          <label className="sv-label" htmlFor="space-path">
            Space path
          </label>
          <input
            id="space-path"
            className="sv-input text-code-sm"
            disabled={isPending}
            onChange={(event) => onChange((current) => ({ ...current, path: event.target.value.toLowerCase(), pathTouched: true }))}
            placeholder="/finance/procurement"
            required
            value={draft.path}
          />
          {pathIssue ? <small className="text-error-red">{pathIssue}</small> : <small className="text-secondary">Use a lowercase slash path like /finance.</small>}
          <div className="knowledge-path-preview">
            <span>Path preview</span>
            <strong>{draft.path || "Generated from the space name"}</strong>
          </div>
        </div>
      ) : (
        <ReadOnlyField label="Space path" value={draft.path} />
      )}
      {!isCreate ? <InlineMessage tone="warning">Space paths are immutable. Existing document ACL paths keep using this path.</InlineMessage> : null}
      {mutationError ? <InlineMessage tone="error">{errorMessage(mutationError, isCreate ? "Unable to create Knowledge Space." : "Unable to update Knowledge Space.")}</InlineMessage> : null}
      <div className="flex flex-wrap justify-end gap-2 border-t border-surface-border pt-4">
        <button type="submit" disabled={!canSubmit || isPending} className="sv-action-primary disabled:cursor-not-allowed disabled:opacity-60">
          {isPending ? "Saving" : isCreate ? "Create Space" : "Save Space"}
        </button>
      </div>
    </form>
  );
}

type SpacePanelProps = {
  draft: SpaceDraft;
  isCreate: boolean;
  isPending: boolean;
  mutationError: unknown;
  onChange: Dispatch<SetStateAction<SpaceDraft>>;
  onNameChange: (name: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  pathExists: boolean;
};
