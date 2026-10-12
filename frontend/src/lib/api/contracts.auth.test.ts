import { afterEach, describe, expect, it, vi } from "vitest";

import { authApi } from "./contracts";
import { jsonResponse } from "./contractsTestSupport";

describe("authApi", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("changes the current user's email with CSRF protection", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      user_id: "user-1",
      email: "new-admin@example.test",
      account_type: "platform_admin",
      group_paths: [],
      clearance_level: "COSMIC_TOP_SECRET",
      permission_version: 1,
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    const user = await authApi.changeEmail({ current_password: "CurrentPass123!", new_email: "new-admin@example.test" });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/auth/change-email");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify({ current_password: "CurrentPass123!", new_email: "new-admin@example.test" }));
    expect(user.email).toBe("new-admin@example.test");
  });
});
