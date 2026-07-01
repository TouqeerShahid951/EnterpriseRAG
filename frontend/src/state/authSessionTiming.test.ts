import { describe, expect, it } from "vitest";

import {
  authSessionTimingFromEnv,
  formatIdleCountdown,
  idleRemainingSeconds,
  shouldShowIdleWarning,
} from "./authSessionTiming";

describe("auth session timing", () => {
  it("uses production defaults that match backend idle timeout defaults", () => {
    expect(authSessionTimingFromEnv({})).toEqual({
      timeoutMs: 30 * 60_000,
      warningMs: 120_000,
    });
  });

  it("accepts positive env overrides and clamps warning below timeout", () => {
    expect(authSessionTimingFromEnv({
      VITE_AUTH_IDLE_TIMEOUT_MINUTES: "10",
      VITE_AUTH_IDLE_WARNING_SECONDS: "900",
    })).toEqual({
      timeoutMs: 600_000,
      warningMs: 300_000,
    });
  });

  it("computes warning visibility and countdown text", () => {
    const timing = authSessionTimingFromEnv({
      VITE_AUTH_IDLE_TIMEOUT_MINUTES: "30",
      VITE_AUTH_IDLE_WARNING_SECONDS: "120",
    });
    const lastTouchedAt = 1000;

    expect(shouldShowIdleWarning(lastTouchedAt, timing, lastTouchedAt + 27 * 60_000)).toBe(false);
    expect(shouldShowIdleWarning(lastTouchedAt, timing, lastTouchedAt + 29 * 60_000)).toBe(true);
    expect(idleRemainingSeconds(lastTouchedAt, timing.timeoutMs, lastTouchedAt + 29 * 60_000 + 500)).toBe(60);
    expect(formatIdleCountdown(60)).toBe("1:00");
    expect(formatIdleCountdown(9)).toBe("0:09");
  });
});
