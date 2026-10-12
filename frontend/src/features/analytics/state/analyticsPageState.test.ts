import { describe, expect, it, vi, afterEach } from "vitest";
import { hashKey } from "@tanstack/react-query";

import { analyticsRequests, analyticsUrl, changeAnalyticsState, readAnalyticsState } from "./analyticsPageState";

const now = new Date("2026-09-09T12:00:00Z");
afterEach(() => vi.useRealTimers());

describe("analytics investigation state", () => {
  it("keeps request keys stable while time passes and uses production answers by default", () => {
    vi.useFakeTimers();
    vi.setSystemTime(now);
    const state = readAnalyticsState("");
    const first = analyticsRequests(state);
    vi.advanceTimersByTime(15000);
    const second = analyticsRequests(state);
    expect(hashKey([first])).toEqual(hashKey([second]));
    expect(second.seriesRequest).toMatchObject({ origin: "chat", work_kind: "answer", as_of: now.toISOString() });
    expect(analyticsRequests({ ...state, asOf: new Date().toISOString() })).not.toEqual(first);
  });

  it("round-trips the snapshot, bucket, page and selected execution for reload/back", () => {
    const state = { ...readAnalyticsState("", now), offset: 50, tab: "queries" as const,
      selectedExecutionId: "older-execution", origin: "evaluation", workKind: "all",
      drilldown: { from: "2026-09-08T00:00:00.000Z", to: "2026-09-09T00:00:00.000Z" } };
    const url = new URL(analyticsUrl(new URL("https://example.test/operational-analytics?keep=1"), state), "https://example.test");
    expect(url.searchParams.get("keep")).toBe("1");
    const restored = readAnalyticsState(url.search, now);
    expect(restored).toEqual(state);
    expect(analyticsRequests(restored).listRequest).toMatchObject({ ...state.drilldown, offset: 50, as_of: state.asOf });
    expect(analyticsRequests(restored).seriesRequest.to).toBe(state.asOf);
  });

  it("clears stale investigation filters when the population changes", () => {
    const state = { ...readAnalyticsState("", now), offset: 50, selectedExecutionId: "old", drilldown: { from: "a", to: "b" } };
    expect(changeAnalyticsState(state, { origin: "evaluation" })).toMatchObject({ offset: 0, selectedExecutionId: "", drilldown: null });
    expect(changeAnalyticsState(state, { tab: "performance" }).offset).toBe(50);
  });

  it("rejects invalid URL state and opens a detail-only URL", () => {
    const state = readAnalyticsState("?analytics_days=900&analytics_offset=-1&analytics_as_of=bad&analytics_origin=spoof&analytics_bucket_from=bad&analytics_execution=old", now);
    expect(state).toMatchObject({ days: 7, offset: 0, origin: "chat", asOf: now.toISOString(), drilldown: null, tab: "queries", selectedExecutionId: "old" });
  });
});
