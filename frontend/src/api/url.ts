const DEFAULT_APP_ORIGIN = "http://localhost:3000";

export function getConfiguredBaseUrl(): string {
  const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();
  if (configuredBaseUrl) return configuredBaseUrl;

  if (typeof window !== "undefined") {
    return window.location.origin;
  }

  return DEFAULT_APP_ORIGIN;
}

export function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}
