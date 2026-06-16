const DEFAULT_API_PORT = "8000";

export function getConfiguredBaseUrl(): string {
  const localDefault = getLocalDefaultBaseUrl();
  if (isBrowserOnLocalHost()) return localDefault;

  return import.meta.env.VITE_API_BASE_URL?.trim() || localDefault;
}

export function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}

function getLocalDefaultBaseUrl(): string {
  if (typeof window === "undefined") {
    return `http://localhost:${DEFAULT_API_PORT}`;
  }

  const { protocol, hostname } = window.location;
  if (isLocalHostname(hostname)) {
    const normalizedHost = hostname === "::1" ? "[::1]" : hostname;
    return `${protocol}//${normalizedHost}:${DEFAULT_API_PORT}`;
  }

  return `http://localhost:${DEFAULT_API_PORT}`;
}

function isBrowserOnLocalHost(): boolean {
  return typeof window !== "undefined" && isLocalHostname(window.location.hostname);
}

function isLocalHostname(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}
