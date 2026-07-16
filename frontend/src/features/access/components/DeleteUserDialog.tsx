import { AlertTriangle, Trash2 } from "lucide-react";

import { Modal } from "@/components/layout/Modal";
import { ReadOnlyField } from "@/features/access/components/AccessUserPanel";
import type { UserAdmin } from "@/types/api";

type DeleteUserDialogProps = {
  confirmation: string;
  isPending: boolean;
  onClose: () => void;
  onConfirmationChange: (value: string) => void;
  onDelete: (userId: string) => void;
  target: UserAdmin | null;
};

export function DeleteUserDialog({ confirmation, isPending, onClose, onConfirmationChange, onDelete, target }: DeleteUserDialogProps) {
  return (
    <Modal
      description="This permanently removes the account, its memberships, chat history, and generated artifacts. Documents and audit history are retained."
      icon={<AlertTriangle size={18} />}
      onClose={onClose}
      open={Boolean(target)}
      size="sm"
      title="Delete user"
    >
      {target ? (
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (confirmation === target.email) onDelete(target.id);
          }}
        >
          <ReadOnlyField label="Account" value={target.email} />
          <label className="sv-field" htmlFor="delete-user-confirmation">
            <span className="sv-label">Type the email address to confirm</span>
            <input
              autoComplete="off"
              className="sv-input"
              disabled={isPending}
              id="delete-user-confirmation"
              onChange={(event) => onConfirmationChange(event.target.value)}
              value={confirmation}
            />
          </label>
          <div className="flex flex-wrap justify-end gap-2 border-t border-surface-border pt-4">
            <button type="button" onClick={onClose} disabled={isPending} className="sv-action-secondary">
              Cancel
            </button>
            <button type="submit" disabled={confirmation !== target.email || isPending} className="sv-action-danger disabled:cursor-not-allowed disabled:opacity-60">
              <Trash2 size={16} /> {isPending ? "Deleting" : "Delete user"}
            </button>
          </div>
        </form>
      ) : null}
    </Modal>
  );
}
