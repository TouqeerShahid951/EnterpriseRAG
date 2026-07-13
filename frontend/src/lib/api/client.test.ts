import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClient, ApiClientError, AUTH_SESSION_EXPIRED_EVENT, AUTH_SESSION_TOUCHED_EVENT } from "./client";

describe("ApiClient auth refresh", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("refreshes and retries a request once after a 401", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(errorResponse(401, "invalid_token"))
      .mockResolvedValueOnce(jsonResponse({ ok: true }))
      .mockResolvedValueOnce(jsonResponse({ id: "user-1" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient({
      baseUrl: "http://api.test",
      getCsrfToken: () => "csrf-token",
    });

    await expect(client.get("/api/v1/auth/me")).resolves.toEqual({ id: "user-1" });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      "http://api.test/api/v1/auth/me",
      "http://api.test/api/v1/auth/refresh",
      "http://api.test/api/v1/auth/me",
    ]);

    const [, refreshInit] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect(refreshInit.method).toBe("POST");
    expect(new Headers(refreshInit.headers).get("X-CSRF-Token")).toBe("csrf-token");
  });

  it("does not refresh a failed login request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(errorResponse(401, "invalid_credentials"));
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient({
      baseUrl: "http://api.test",
      getCsrfToken: () => "csrf-token",
    });

    await expect(client.postJson("/api/v1/auth/login", { email: "x", password: "bad" })).rejects.toMatchObject({
      code: "invalid_credentials",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shares one in-flight refresh across concurrent 401 responses", async () => {
    const seenPaths = new Set<string>();
    const fetchMock = vi.fn(async (url: string) => {
      const path = new URL(url).pathname;
      if (path === "/api/v1/auth/refresh") {
        return jsonResponse({ ok: true });
      }
      if (!seenPaths.has(path)) {
        seenPaths.add(path);
        return errorResponse(401, "invalid_token");
      }
      return jsonResponse({ path });
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient({
      baseUrl: "http://api.test",
      getCsrfToken: () => "csrf-token",
    });

    await expect(Promise.all([client.get("/api/v1/docs"), client.get("/api/v1/admin/users")])).resolves.toEqual([
      { path: "/api/v1/docs" },
      { path: "/api/v1/admin/users" },
    ]);

    const refreshCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/auth/refresh"));
    expect(refreshCalls).toHaveLength(1);
  });

  it("notifies the app when refresh fails", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(errorResponse(401, "invalid_token"))
      .mockResolvedValueOnce(errorResponse(401, "invalid_refresh_session"));
    const dispatchEvent = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("window", { dispatchEvent });

    const client = new ApiClient({
      baseUrl: "http://api.test",
      getCsrfToken: () => "csrf-token",
    });

    await expect(client.get("/api/v1/auth/me")).rejects.toBeInstanceOf(ApiClientError);
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
    expect(dispatchEvent.mock.calls[0][0]).toMatchObject({ type: AUTH_SESSION_EXPIRED_EVENT });
  });

  it("dedupes session-expired notifications until a later successful request", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(errorResponse(401, "invalid_token"))
      .mockResolvedValueOnce(errorResponse(401, "invalid_refresh_session"))
      .mockResolvedValueOnce(errorResponse(401, "invalid_token"))
      .mockResolvedValueOnce(errorResponse(401, "invalid_refresh_session"))
      .mockResolvedValueOnce(jsonResponse({ ok: true }))
      .mockResolvedValueOnce(errorResponse(401, "invalid_token"))
      .mockResolvedValueOnce(errorResponse(401, "invalid_refresh_session"));
    const dispatchEvent = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("window", { dispatchEvent });

    const client = new ApiClient({
      baseUrl: "http://api.test",
      getCsrfToken: () => "csrf-token",
    });

    await expect(client.get("/api/v1/docs")).rejects.toBeInstanceOf(ApiClientError);
    await expect(client.get("/api/v1/admin/users")).rejects.toBeInstanceOf(ApiClientError);
    expect(dispatchedEventTypes(dispatchEvent)).toEqual([AUTH_SESSION_EXPIRED_EVENT]);

    await expect(client.postJson("/api/v1/auth/login", { email: "admin@prudentia.ai", password: "secret" })).resolves.toEqual({ ok: true });
    await expect(client.get("/api/v1/docs")).rejects.toBeInstanceOf(ApiClientError);
    expect(dispatchedEventTypes(dispatchEvent)).toEqual([
      AUTH_SESSION_EXPIRED_EVENT,
      AUTH_SESSION_TOUCHED_EVENT,
      AUTH_SESSION_EXPIRED_EVENT,
    ]);
  });

  it("aborts a request after the configured timeout", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal?.reason), { once: true });
    }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient({ baseUrl: "http://api.test" });
    const request = client.get("/api/v1/auth/me", { timeoutMs: 25 });
    const assertion = expect(request).rejects.toMatchObject({ name: "TimeoutError" });

    await vi.advanceTimersByTimeAsync(25);

    await assertion;
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.signal?.aborted).toBe(true);
  });
});

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function errorResponse(status: number, code: string) {
  return new Response(JSON.stringify({ error: { code, message: code } }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function dispatchedEventTypes(dispatchEvent: ReturnType<typeof vi.fn>): string[] {
  return dispatchEvent.mock.calls.map(([event]) => (event as Event).type);
}
