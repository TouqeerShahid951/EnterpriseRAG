import type { ApiError } from "../types/api";

const JSON_CONTENT_TYPE = "application/json";

export class ApiClientError extends Error {
  readonly error: ApiError;

  constructor(error: ApiError) {
    super(error.message);
    this.name = "ApiClientError";
    this.error = error;
  }

  get status(): number {
    return this.error.status;
  }

  get code(): string {
    return this.error.code;
  }
}

export async function parseResponse<TResponse>(response: Response): Promise<TResponse> {
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes(JSON_CONTENT_TYPE)) {
    return (await response.json()) as TResponse;
  }

  return (await response.text()) as TResponse;
}

export async function toApiError(response: Response): Promise<ApiError> {
  const fallback: ApiError = {
    status: response.status,
    code: response.statusText || "request_failed",
    message: response.statusText || "Request failed",
  };

  try {
    const contentType = response.headers.get("content-type") ?? "";

    if (!contentType.includes(JSON_CONTENT_TYPE)) {
      const message = await response.text();
      if (!message || contentType.includes("text/html") || message.trimStart().startsWith("<")) {
        return fallback;
      }
      return { ...fallback, message };
    }

    const payload = (await response.json()) as unknown;
    const nested = isObject(payload) && isObject(payload.error) ? payload.error : null;
    if (nested) {
      return {
        ...fallback,
        status: response.status,
        code: typeof nested.code === "string" ? nested.code : fallback.code,
        message: typeof nested.message === "string" ? nested.message : fallback.message,
        details: nested.details ?? nested.context,
      };
    }

    const flat = isObject(payload) ? payload : {};
    const validationMessage = validationErrorMessage(flat.detail);
    return {
      ...fallback,
      ...flat,
      status: response.status,
      code: typeof flat.code === "string" ? flat.code : fallback.code,
      message: typeof flat.message === "string" ? flat.message : validationMessage ?? fallback.message,
      details: flat.details ?? flat.detail,
    };
  } catch {
    return fallback;
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validationErrorMessage(detail: unknown): string | null {
  if (!Array.isArray(detail)) return null;
  const messages = detail
    .map((item) => {
      if (!isObject(item)) return null;
      const location = Array.isArray(item.loc) ? item.loc.map(String).join(".") : null;
      const message = typeof item.msg === "string" ? item.msg : null;
      if (!message) return null;
      return location ? `${location}: ${message}` : message;
    })
    .filter((item): item is string => Boolean(item));
  return messages.length ? messages.join("; ") : null;
}
