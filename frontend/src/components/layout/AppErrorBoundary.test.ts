import { describe, expect, it } from "vitest";

import { isStaleChunkError } from "./AppErrorBoundary";

describe("isStaleChunkError", () => {
  it("recognizes an outdated lazy-loaded bundle", () => {
    expect(isStaleChunkError(new Error("Failed to fetch dynamically imported module"))).toBe(true);
  });

  it("does not reload for an application error", () => {
    expect(isStaleChunkError(new Error("Invalid settings response"))).toBe(false);
  });
});
