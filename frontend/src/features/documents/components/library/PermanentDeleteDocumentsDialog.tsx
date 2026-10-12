import { useEffect, useState } from "react";
import { AlertTriangle, Trash2 } from "lucide-react";

import { InlineMessage } from "@/components/layout/Common";
import { Modal } from "@/components/layout/Modal";
import { permanentDeleteConfirmation } from "@/features/documents/utils/documentPageUtils";
import type { Document } from "@/types/api";

export function PermanentDeleteDocumentsDialog({ documents, isPending, onClose, onConfirm }: Props) {
  const [confirmation, setConfirmation] = useState("");
  const expected = permanentDeleteConfirmation(documents.length);

  useEffect(() => setConfirmation(""), [documents]);

  return (
    <Modal
      description="This permanently removes database records, indexed assets, and source files. This action cannot be undone."
      icon={<AlertTriangle size={18} />}
      onClose={isPending ? () => undefined : onClose}
      open={documents.length > 0}
      size="sm"
      title={documents.length === 1 ? "Permanently delete document" : `Permanently delete ${documents.length} documents`}
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (confirmation === expected) onConfirm();
        }}
      >
        <InlineMessage tone="warning">
          {documents.length === 1 ? documents[0]?.title : `${documents.length} selected documents`}
        </InlineMessage>
        <label className="sv-field" htmlFor="permanent-delete-confirmation">
          <span className="sv-label">Type {expected} to confirm</span>
          <input
            autoComplete="off"
            autoFocus
            className="sv-input"
            disabled={isPending}
            id="permanent-delete-confirmation"
            onChange={(event) => setConfirmation(event.target.value)}
            value={confirmation}
          />
        </label>
        <div className="flex flex-wrap justify-end gap-2 border-t border-surface-border pt-4">
          <button type="button" onClick={onClose} disabled={isPending} className="sv-action-secondary">
            Cancel
          </button>
          <button type="submit" disabled={confirmation !== expected || isPending} className="sv-action-danger disabled:cursor-not-allowed disabled:opacity-60">
            <Trash2 size={16} /> {isPending ? "Deleting" : "Permanently delete"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

type Props = {
  documents: Document[];
  isPending: boolean;
  onClose: () => void;
  onConfirm: () => void;
};
