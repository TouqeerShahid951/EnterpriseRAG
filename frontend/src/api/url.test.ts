import { afterEach, describe, expect, it, vi } from "vitest";

import { getConfiguredBaseUrl } from "./url";

describe("getConfiguredBaseUrl", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("uses the current browser origin for non-localhost access", () => {
    vi.stubGlobal("window", {
      location: {
        hostname: "10.33.29.80",
        origin: "http://10.33.29.80:3000",
      },
    });

    expect(getConfiguredBaseUrl()).toBe("http://10.33.29.80:3000");
  });

  it("keeps the explicit API base URL override", () => {
    vi.stubEnv("VITE_API_BASE_URL", "http://api.override:8000");
    vi.stubGlobal("window", {
      location: {
        hostname: "10.33.29.80",
        origin: "http://10.33.29.80:3000",
      },
    });

    expect(getConfiguredBaseUrl()).toBe("http://api.override:8000");
  });

  it("uses the current browser origin for localhost access", () => {
    vi.stubGlobal("window", {
      location: {
        hostname: "localhost",
        origin: "http://localhost:3000",
        protocol: "http:",
      },
    });

    expect(getConfiguredBaseUrl()).toBe("http://localhost:3000");
  });

  it("uses the local app origin when no browser window is available", () => {
    expect(getConfiguredBaseUrl()).toBe("http://localhost:3000");
  });
});
