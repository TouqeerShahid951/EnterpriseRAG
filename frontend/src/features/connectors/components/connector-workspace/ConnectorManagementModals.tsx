import type { FormEvent } from "react";
import { KeyRound, Trash2 } from "lucide-react";

import { InlineMessage } from "@/components/layout/Common";
import { Modal } from "@/components/layout/Modal";
import { ConnectorProfileSetup } from "@/features/connectors/components/connector-workspace/ConnectorWorkspace";
import { SchemaSnapshotModal } from "@/features/connectors/components/connector-workspace/SchemaSnapshotModal";
import type { ConnectorProfile } from "@/types/api";
import type {
  ConnectorProfileDraft,
  ConnectorSchemaSnapshotViewerState,
} from "@/features/connectors/utils/connectorPanelUtils";

type Props = {
  createError: unknown;
  creating: boolean;
  deletePending: boolean;
  deleteProfile: ConnectorProfile | null;
  pendingActionId: string | null;
  pendingActionType: "test" | "introspect" | null;
  profileDraft: ConnectorProfileDraft;
  profileError: string | null;
  profilesLoading: boolean;
  schemaViewer: ConnectorSchemaSnapshotViewerState | null;
  setupOpen: boolean;
  onCloseDelete: () => void;
  onCloseSchemaViewer: () => void;
  onCloseSetup: () => void;
  onConfirmDelete: () => void;
  onProfileAction: (action: "test" | "introspect", id: string) => void;
  onProfileChange: (patch: Partial<ConnectorProfileDraft>) => void;
  onProfileSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export function ConnectorManagementModals({
  createError,
  creating,
  deletePending,
  deleteProfile,
  pendingActionId,
  pendingActionType,
  profileDraft,
  profileError,
  profilesLoading,
  schemaViewer,
  setupOpen,
  onCloseDelete,
  onCloseSchemaViewer,
  onCloseSetup,
  onConfirmDelete,
  onProfileAction,
  onProfileChange,
  onProfileSubmit,
}: Props) {
  return (
    <>
      <SchemaSnapshotModal onClose={onCloseSchemaViewer} viewer={schemaViewer} />
      <Modal
        description="Save encrypted read-only credentials, then read the schema and review what Live DB may use."
        icon={<KeyRound size={18} />}
        onClose={onCloseSetup}
        open={setupOpen}
        size="md"
        title="Add Connection"
      >
        <ConnectorProfileSetup
          connectorProfiles={[]}
          onClose={onCloseSetup}
          onProfileAction={onProfileAction}
          onProfileChange={onProfileChange}
          onProfileSubmit={onProfileSubmit}
          pendingProfileActionId={pendingActionId}
          pendingProfileActionType={pendingActionType}
          profileDraft={profileDraft}
          profileError={profileError}
          profileMutationError={createError}
          profilesCreating={creating}
          profilesLoading={profilesLoading}
        />
      </Modal>
      <Modal
        description="This removes the connection and its database access review. Uploaded documents are not deleted."
        icon={<Trash2 size={18} />}
        onClose={onCloseDelete}
        open={Boolean(deleteProfile)}
        size="sm"
        title="Delete Connection"
      >
        {deleteProfile ? (
          <section className="space-y-4">
            <InlineMessage tone="warning">
              Delete {deleteProfile.name}? Live DB will no longer use reviews from this connection.
            </InlineMessage>
            <div className="flex flex-wrap justify-end gap-2">
              <button type="button" onClick={onCloseDelete} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-label-md font-bold text-on-surface hover:border-primary">
                Cancel
              </button>
              <button type="button" disabled={deletePending} onClick={onConfirmDelete} className="rounded-md border border-error-red/30 bg-error-container px-3 py-2 text-label-md font-bold text-error-red hover:border-error-red disabled:opacity-50">
                {deletePending ? "Deleting" : "Delete Connection"}
              </button>
            </div>
          </section>
        ) : null}
      </Modal>
    </>
  );
}
