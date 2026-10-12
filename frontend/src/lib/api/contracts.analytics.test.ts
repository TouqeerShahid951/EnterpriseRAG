import { afterEach, describe, expect, it, vi } from "vitest";

import { analyticsApi } from "./contracts";
import { jsonResponse } from "./contractsTestSupport";

describe("analyticsApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads a detail independently of list pagination and encodes its identifier", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ execution_id: "old/id" }));
    vi.stubGlobal("fetch", fetchMock);
    expect((await analyticsApi.execution("old/id")).execution_id).toBe("old/id");
    const [url] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/executions/old%2Fid");
  });

  it("propagates detail failures and preserves an explicit pagination snapshot", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: { code: "query_analytics_execution_not_found", message: "Missing" } }), { status: 404, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(analyticsApi.execution("missing")).rejects.toMatchObject({ status: 404 });
    fetchMock.mockImplementation(async () => jsonResponse({ items: [], total: 0 }));
    await analyticsApi.executions({ as_of: "2026-09-09T00:00:00Z", origin: "evaluation", work_kind: "all", offset: 50 });
    const [url] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect(url).toContain("as_of=2026-09-09T00%3A00%3A00Z");
  });

  it("builds the summary request with encoded filters", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ total_executions: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await analyticsApi.summary({ from: "2026-01-01T00:00:00Z", group_path: "/finance/ops", outcome: "abstained" });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/admin/query-analytics/summary?");
    expect(url).toContain("from=2026-01-01T00%3A00%3A00Z");
    expect(url).toContain("group_path=%2Ffinance%2Fops");
    expect(url).toContain("outcome=abstained");
    expect(init.method ?? "GET").toBe("GET");
  });

  it("loads the execution list with pagination", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], total: 0, limit: 25, offset: 10 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await analyticsApi.executions({ limit: 25, offset: 10, work_kind: "answer" });

    const [url] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/admin/query-analytics/executions?");
    expect(url).toContain("work_kind=answer");
    expect(url).toContain("limit=25");
    expect(url).toContain("offset=10");
    expect(response.total).toBe(0);
  });

  it("loads zero-filled trend buckets with the same filters", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ bucket_size: "day", buckets: [] }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await analyticsApi.series({ source_mode: "corpus_only" });

    const [url] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/admin/query-analytics/series?");
    expect(url).toContain("source_mode=corpus_only");
    expect(response.bucket_size).toBe("day");
  });

  it("loads retrieval and performance diagnostics with the selected filters", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ capture_status_counts: {}, stages: [], timings: [], data_status: "empty" }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await analyticsApi.diagnostics({ group_path: "/finance/ops", model_cohort: "models-a", configuration_digest: "config-a" });

    const [url] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/admin/query-analytics/diagnostics?");
    expect(url).toContain("group_path=%2Ffinance%2Fops");
    expect(url).toContain("model_cohort=models-a");
    expect(url).toContain("configuration_digest=config-a");
    expect(response.data_status).toBe("empty");
  });
});
