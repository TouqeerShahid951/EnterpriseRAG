import type { UpdateConnectorSchemaCatalogRequest } from "@/lib/api/contracts";
import type { ClearanceLevel, ConnectorProfile, ConnectorSchemaCatalog } from "@/types/api";

export type ConnectorCatalogEditorProps = {
  catalog: ConnectorSchemaCatalog;
  clearanceOptions: ClearanceLevel[];
  isSaving: boolean;
  mutationError: unknown;
  onClose: () => void;
  onContinueAiEnrichment: () => void;
  onSave: (request: UpdateConnectorSchemaCatalogRequest) => void;
  profile: ConnectorProfile;
  writableSpacePaths: string[];
};
