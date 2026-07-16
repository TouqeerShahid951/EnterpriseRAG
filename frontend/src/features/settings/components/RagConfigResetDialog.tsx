import { AlertTriangle, RefreshCw } from "lucide-react";

import { InlineMessage } from "@/components/layout/Common";
import { Modal } from "@/components/layout/Modal";
import { errorMessage } from "@/lib/utils/format";

type RagConfigResetDialogProps = {
  draftIsDirty: boolean;
  error: unknown;
  isError: boolean;
  isPending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  open: boolean;
};

export function RagConfigResetDialog({ draftIsDirty, error, isError, isPending, onCancel, onConfirm, open }: RagConfigResetDialogProps) {
  return (
    <Modal
      description="Remove the saved workspace model routing override and immediately return queries and ingestion to the deployment's environment-backed configuration."
      icon={<AlertTriangle size={18} />}
      onClose={onCancel}
      open={open}
      size="sm"
      title="Restore deployment defaults"
    >
      <div className="space-y-4">
        <InlineMessage tone="warning">
          This discards the workspace override{draftIsDirty ? " and your unsaved draft" : ""}. The deployment configuration will become active as soon as the reset completes.
        </InlineMessage>
        {isError ? (
          <InlineMessage tone="error">
            {errorMessage(error, "Unable to remove the workspace model routing override.")}
          </InlineMessage>
        ) : null}
        <div className="flex flex-wrap justify-end gap-2 border-t border-surface-border pt-4">
          <button type="button" className="sv-action-secondary" disabled={isPending} onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="sv-action-danger disabled:cursor-not-allowed disabled:opacity-60" disabled={isPending} onClick={onConfirm}>
            <RefreshCw size={16} />
            {isPending ? "Restoring" : "Restore defaults"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
