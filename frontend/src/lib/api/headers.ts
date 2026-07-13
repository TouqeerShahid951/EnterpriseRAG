export const JSON_CONTENT_TYPE = "application/json";
export const JSON_CONTENT_TYPE_HEADER = "Content-Type";

export const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export function getCsrfTokenFromCookie(): string | null {
  if (typeof document === "undefined") {
    return null;
  }

  const cookie = document.cookie
    .split("; ")
    .find(
      (entry) =>
        entry.startsWith("csrf_token=") ||
        entry.startsWith("csrftoken=") ||
        entry.startsWith("XSRF-TOKEN="),
    );

  return cookie ? decodeURIComponent(cookie.split("=")[1] ?? "") : null;
}

export function headersToObject(headers?: HeadersInit): Record<string, string> {
  return headers ? Object.fromEntries(new Headers(headers).entries()) : {};
}
