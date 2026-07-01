import { ApiClientError, parseResponse, toApiError } from "./response";
import { getCsrfTokenFromCookie, headersToObject, JSON_CONTENT_TYPE, JSON_CONTENT_TYPE_HEADER, UNSAFE_METHODS } from "./headers";
import { parseSseStream } from "./sse";
import { getConfiguredBaseUrl, normalizeBaseUrl } from "./url";

export { ApiClientError } from "./response";

type JsonBody = object | unknown[] | string | number | boolean | null;

export const AUTH_SESSION_EXPIRED_EVENT = "agenticrag:auth-session-expired";
export const AUTH_SESSION_TOUCHED_EVENT = "agenticrag:auth-session-touched";

export interface ApiClientOptions {
  baseUrl?: string;
  csrfHeaderName?: string;
  getCsrfToken?: () => string | null | undefined;
  refreshPath?: string;
  loginPath?: string;
  onSessionExpired?: () => void;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly csrfHeaderName: string;
  private readonly getCsrfToken?: () => string | null | undefined;
  private readonly refreshPath: string;
  private readonly loginPath: string;
  private readonly onSessionExpired?: () => void;
  private refreshPromise: Promise<boolean> | null = null;
  private sessionExpiredNotified = false;

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = normalizeBaseUrl(options.baseUrl ?? getConfiguredBaseUrl());
    this.csrfHeaderName = options.csrfHeaderName ?? "X-CSRF-Token";
    this.getCsrfToken = options.getCsrfToken ?? getCsrfTokenFromCookie;
    this.refreshPath = options.refreshPath ?? "/api/v1/auth/refresh";
    this.loginPath = options.loginPath ?? "/api/v1/auth/login";
    this.onSessionExpired = options.onSessionExpired;
  }

  get<TResponse>(path: string, init?: RequestInit): Promise<TResponse> {
    return this.request<TResponse>(path, { ...init, method: "GET" });
  }

  delete<TResponse>(path: string, init?: RequestInit): Promise<TResponse> {
    return this.request<TResponse>(path, { ...init, method: "DELETE" });
  }

  postJson<TResponse>(path: string, body: JsonBody, init?: RequestInit): Promise<TResponse> {
    return this.json<TResponse>("POST", path, body, init);
  }

  putJson<TResponse>(path: string, body: JsonBody, init?: RequestInit): Promise<TResponse> {
    return this.json<TResponse>("PUT", path, body, init);
  }

  patchJson<TResponse>(path: string, body: JsonBody, init?: RequestInit): Promise<TResponse> {
    return this.json<TResponse>("PATCH", path, body, init);
  }

  postForm<TResponse>(path: string, formData: FormData, init?: RequestInit): Promise<TResponse> {
    return this.request<TResponse>(path, {
      ...init,
      method: "POST",
      body: formData,
    });
  }

  fetchRaw(path: string, init: RequestInit = {}): Promise<Response> {
    return this.fetchWithAuthRefresh(path, init);
  }

  async *postJsonSse<TEvent>(path: string, body: JsonBody, init?: RequestInit): AsyncGenerator<TEvent> {
    const response = await this.fetchWithAuthRefresh(path, {
      ...init,
      method: "POST",
      body: JSON.stringify(body),
      headers: {
        [JSON_CONTENT_TYPE_HEADER]: JSON_CONTENT_TYPE,
        ...headersToObject(init?.headers),
      },
    });

    if (!response.ok) {
      throw new ApiClientError(await toApiError(response));
    }

    if (!response.body) {
      throw new Error("Streaming response did not include a body.");
    }

    yield* parseSseStream<TEvent>(response.body);
  }

  async request<TResponse>(path: string, init: RequestInit = {}): Promise<TResponse> {
    const response = await this.fetchWithAuthRefresh(path, init);

    if (!response.ok) {
      throw new ApiClientError(await toApiError(response));
    }

    if (response.status === 204) {
      return undefined as TResponse;
    }

    return parseResponse<TResponse>(response);
  }

  private async fetchWithAuthRefresh(path: string, init: RequestInit): Promise<Response> {
    const response = await this.fetchOnce(path, init);
    if (response.ok) {
      this.sessionExpiredNotified = false;
      this.notifySessionTouched();
    }
    if (response.status !== 401 || !this.canRefreshFor(path)) {
      return response;
    }

    const refreshed = await this.refreshAccessToken();
    if (!refreshed) {
      this.notifySessionExpired();
      return response;
    }

    return this.fetchOnce(path, init);
  }

  private fetchOnce(path: string, init: RequestInit): Promise<Response> {
    const method = (init.method ?? "GET").toUpperCase();
    const headers = this.buildHeaders(method, init.headers);
    return fetch(this.toUrl(path), {
      ...init,
      method,
      headers,
      credentials: "include",
    });
  }

  private canRefreshFor(path: string): boolean {
    const normalizedPath = this.normalizePath(path);
    return (
      Boolean(this.getCsrfToken?.()) &&
      normalizedPath !== this.normalizePath(this.refreshPath) &&
      normalizedPath !== this.normalizePath(this.loginPath)
    );
  }

  private refreshAccessToken(): Promise<boolean> {
    if (!this.refreshPromise) {
      this.refreshPromise = this.fetchOnce(this.refreshPath, {
        method: "POST",
        body: JSON.stringify(null),
        headers: {
          [JSON_CONTENT_TYPE_HEADER]: JSON_CONTENT_TYPE,
        },
      })
        .then((response) => {
          if (response.ok) {
            this.sessionExpiredNotified = false;
            this.notifySessionTouched();
          }
          return response.ok;
        })
        .catch(() => false)
        .finally(() => {
          this.refreshPromise = null;
        });
    }

    return this.refreshPromise;
  }

  private json<TResponse>(
    method: "POST" | "PUT" | "PATCH",
    path: string,
    body: JsonBody,
    init?: RequestInit,
  ): Promise<TResponse> {
    return this.request<TResponse>(path, {
      ...init,
      method,
      body: JSON.stringify(body),
      headers: {
        [JSON_CONTENT_TYPE_HEADER]: JSON_CONTENT_TYPE,
        ...headersToObject(init?.headers),
      },
    });
  }

  private buildHeaders(method: string, headers?: HeadersInit): Headers {
    const nextHeaders = new Headers(headers);

    if (UNSAFE_METHODS.has(method)) {
      const csrfToken = this.getCsrfToken?.();
      if (csrfToken) {
        nextHeaders.set(this.csrfHeaderName, csrfToken);
      }
    }

    return nextHeaders;
  }

  private toUrl(path: string): string {
    if (/^https?:\/\//i.test(path)) {
      throw new Error("ApiClient paths must be root-relative and use the configured API base URL.");
    }

    const relativePath = path.startsWith("/") ? path : `/${path}`;
    return `${this.baseUrl}${relativePath}`;
  }

  private normalizePath(path: string): string {
    return path.startsWith("/") ? path : `/${path}`;
  }

  private notifySessionExpired(): void {
    if (this.sessionExpiredNotified) return;
    this.sessionExpiredNotified = true;
    if (this.onSessionExpired) {
      this.onSessionExpired();
      return;
    }
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event(AUTH_SESSION_EXPIRED_EVENT));
    }
  }

  private notifySessionTouched(): void {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event(AUTH_SESSION_TOUCHED_EVENT));
    }
  }
}
