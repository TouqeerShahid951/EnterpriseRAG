import { apiClient } from "./apiClient";
import type {
  AbbreviationEntry,
  AbbreviationEntryCreateRequest,
  AbbreviationEntryUpdateRequest,
  AbbreviationGlossaryResponse,
} from "@/types/api/abbreviations";

export const abbreviationsApi = {
  get: () => apiClient.get<AbbreviationGlossaryResponse>("/api/v1/abbreviation-glossaries"),
  create: (request: AbbreviationEntryCreateRequest) =>
    apiClient.postJson<AbbreviationEntry>("/api/v1/abbreviation-glossaries/entries", request),
  update: (entryId: string, request: AbbreviationEntryUpdateRequest) =>
    apiClient.patchJson<AbbreviationEntry>(
      `/api/v1/abbreviation-glossaries/entries/${encodeURIComponent(entryId)}`,
      request,
    ),
  remove: (entryId: string, expectedRevision: number) => {
    const params = new URLSearchParams({ expected_revision: String(expectedRevision) });
    return apiClient.delete<void>(
      `/api/v1/abbreviation-glossaries/entries/${encodeURIComponent(entryId)}?${params}`,
    );
  },
  removeSource: (documentId: string) => apiClient.delete<void>(
    `/api/v1/abbreviation-glossaries/sources/${encodeURIComponent(documentId)}`,
  ),
};
