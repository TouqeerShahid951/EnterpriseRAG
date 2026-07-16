import type {
  ClearanceLevel,
  ConnectorProfile,
  ConnectorSchemaCatalog,
  ConnectorSchemaCatalogStatus,
  ConnectorSchemaSnapshot,
  ConnectorTestResponse,
  ConnectorType,
} from "@/types/api";
import { apiClient } from "./apiClient";

export interface CreateConnectorProfileRequest {
  name: string;
  connector_type: ConnectorType;
  public_config: Record<string, unknown>;
  secrets: Record<string, unknown>;
}

export interface UpdateConnectorProfileRequest {
  name?: string | null;
  public_config?: Record<string, unknown> | null;
  secrets?: Record<string, unknown> | null;
}

export interface CreateConnectorSchemaCatalogRequest {
  catalog_json?: Record<string, unknown> | null;
  status?: ConnectorSchemaCatalogStatus;
  group_path: string;
  group_paths?: string[];
  clearance_level?: ClearanceLevel;
}

export interface CreateConnectorSchemaCatalogAiDraftRequest {
  group_path: string;
  group_paths?: string[];
  clearance_level?: ClearanceLevel;
}

export interface EnrichConnectorSchemaCatalogTableRequest {
  table_key: string;
}

export interface UpdateConnectorSchemaCatalogRequest {
  catalog_json?: Record<string, unknown> | null;
  status?: ConnectorSchemaCatalogStatus | null;
  group_path?: string | null;
  group_paths?: string[] | null;
  clearance_level?: ClearanceLevel | null;
}

export const connectorApi = {
  listProfiles: () => apiClient.get<{ items: ConnectorProfile[]; total: number }>("/api/v1/connectors/profiles"),
  createProfile: (request: CreateConnectorProfileRequest) =>
    apiClient.postJson<ConnectorProfile>("/api/v1/connectors/profiles", request),
  updateProfile: (profileId: string, request: UpdateConnectorProfileRequest) =>
    apiClient.putJson<ConnectorProfile>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}`, request),
  deleteProfile: (profileId: string) =>
    apiClient.delete<void>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}`),
  testProfile: (profileId: string) =>
    apiClient.postJson<ConnectorTestResponse>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}/test`, null),
  introspectProfile: (profileId: string) =>
    apiClient.postJson<ConnectorSchemaSnapshot>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}/introspect`, null),
  listSchemaCatalogs: async (profileId: string) => {
    const response = await apiClient.get<{ items: ConnectorSchemaCatalog[]; total: number }>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}/schema-catalogs`);
    return { ...response, items: response.items.map(normalizeConnectorSchemaCatalog) };
  },
  createSchemaCatalog: async (profileId: string, request: CreateConnectorSchemaCatalogRequest) =>
    normalizeConnectorSchemaCatalog(await apiClient.postJson<ConnectorSchemaCatalog>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}/schema-catalogs`, request)),
  createAiSchemaCatalogDraft: async (profileId: string, request: CreateConnectorSchemaCatalogAiDraftRequest) =>
    normalizeConnectorSchemaCatalog(await apiClient.postJson<ConnectorSchemaCatalog>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}/schema-catalogs/ai-draft`, request)),
  enrichSchemaCatalogTable: (profileId: string, catalogId: string, request: EnrichConnectorSchemaCatalogTableRequest) =>
    apiClient.postJson<ConnectorSchemaCatalog>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}/schema-catalogs/${encodeURIComponent(catalogId)}/ai-enrich-table`, request).then(normalizeConnectorSchemaCatalog),
  updateSchemaCatalog: (profileId: string, catalogId: string, request: UpdateConnectorSchemaCatalogRequest) =>
    apiClient.putJson<ConnectorSchemaCatalog>(`/api/v1/connectors/profiles/${encodeURIComponent(profileId)}/schema-catalogs/${encodeURIComponent(catalogId)}`, request).then(normalizeConnectorSchemaCatalog),
};

function normalizeConnectorSchemaCatalog(catalog: ConnectorSchemaCatalog): ConnectorSchemaCatalog {
  const ownerGroupPath = catalog.owner_group_path || catalog.group_path;
  const jsonShared = Array.isArray(catalog.catalog_json?.shared_group_paths)
    ? catalog.catalog_json.shared_group_paths.filter((value): value is string => typeof value === "string")
    : [];
  const sharedGroupPaths = Array.isArray(catalog.shared_group_paths) ? catalog.shared_group_paths : jsonShared;
  const accessGroupPaths = Array.isArray(catalog.access_group_paths) && catalog.access_group_paths.length
    ? catalog.access_group_paths
    : [ownerGroupPath, ...sharedGroupPaths].filter(Boolean);
  return {
    ...catalog,
    owner_group_path: ownerGroupPath,
    shared_group_paths: sharedGroupPaths,
    access_group_paths: accessGroupPaths,
  };
}
