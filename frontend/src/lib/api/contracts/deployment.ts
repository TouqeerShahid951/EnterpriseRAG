import type { ResourceSnapshot } from "@/types/api/deployment";
import { apiClient } from "./apiClient";

export const deploymentApi = {
  resources: () => apiClient.get<ResourceSnapshot>("/api/v1/admin/system-resources"),
};
