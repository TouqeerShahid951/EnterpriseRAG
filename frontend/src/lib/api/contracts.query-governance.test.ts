import { afterEach, describe, expect, it, vi } from "vitest";

import { auditApi, queryApi, ragEvaluationsApi } from "./contracts";
import { auditSummary, jsonResponse, queryResponse } from "./contractsTestSupport";

describe("queryApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads visible query sources for the selected Knowledge Space", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      items: [{
        id: "connector_catalog:catalog-1",
        kind: "connector_schema_catalog",
        name: "Cases approved database scope",
        description: null,
        connector_type: "postgres",
        scope: "database_scope",
        group_path: "/ops",
        clearance_level: "NATO_RESTRICTED",
      }],
      total: 1,
    }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await queryApi.sources({ group_path: " /ops " });

    const calls = fetchMock.mock.calls as unknown as Array<[unknown]>;
    expect(String(calls[0][0])).toContain("/api/v1/query/sources?group_path=%2Fops");
    expect(response.items[0].id).toBe("connector_catalog:catalog-1");
  });

  it("sends explicit source controls in query requests", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(queryResponse()));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await queryApi.ask({
      query: "Count cases",
      session_id: "session-1",
      source_mode: "db_only",
      query_source_id: "connector_catalog:catalog-1",
      allow_source_expansion: true,
    });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/query");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify({
      query: "Count cases",
      session_id: "session-1",
      source_mode: "db_only",
      query_source_id: "connector_catalog:catalog-1",
      allow_source_expansion: true,
    }));
  });
});

describe("auditApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds filtered audit list queries", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], total: 0, limit: 25, offset: 50, summary: auditSummary() }));
    vi.stubGlobal("fetch", fetchMock);

    await auditApi.list({
      search: "budget",
      category: "document",
      event_type: "upload.queued",
      actor_id: "auditor@example.test",
      target_type: "document",
      target_id: "doc-1",
      group_path: "/finance",
      created_from: "2026-06-01T00:00:00Z",
      created_to: "2026-06-18T23:59:59Z",
      limit: 25,
      offset: 50,
    });

    const calls = fetchMock.mock.calls as unknown as Array<[unknown]>;
    const url = String(calls[0][0]);
    expect(url).toContain("/api/v1/audit-log?");
    expect(url).toContain("search=budget");
    expect(url).toContain("category=document");
    expect(url).toContain("event_type=upload.queued");
    expect(url).toContain("actor_id=auditor%40example.test");
    expect(url).toContain("target_type=document");
    expect(url).toContain("target_id=doc-1");
    expect(url).toContain("group_path=%2Ffinance");
    expect(url).toContain("created_from=2026-06-01T00%3A00%3A00Z");
    expect(url).toContain("created_to=2026-06-18T23%3A59%3A59Z");
    expect(url).toContain("limit=25");
    expect(url).toContain("offset=50");
  });

  it("builds filtered audit export queries without pagination", async () => {
    const fetchMock = vi.fn(async () => new Response("id,event_type\n1,upload.queued\n", { status: 200, headers: { "Content-Type": "text/csv" } }));
    vi.stubGlobal("fetch", fetchMock);

    await auditApi.exportCsv({
      search: "budget",
      category: "document",
      group_path: "/finance",
      created_from: "2026-06-01T00:00:00Z",
      created_to: "2026-06-18T23:59:59Z",
      limit: 25,
      offset: 50,
      max_rows: 250,
    });

    const calls = fetchMock.mock.calls as unknown as Array<[unknown]>;
    const url = String(calls[0][0]);
    expect(url).toContain("/api/v1/audit-log/export?");
    expect(url).toContain("search=budget");
    expect(url).toContain("category=document");
    expect(url).toContain("group_path=%2Ffinance");
    expect(url).toContain("created_from=2026-06-01T00%3A00%3A00Z");
    expect(url).toContain("created_to=2026-06-18T23%3A59%3A59Z");
    expect(url).toContain("max_rows=250");
    expect(url).not.toContain("limit=25");
    expect(url).not.toContain("offset=50");
  });
});

describe("ragEvaluationsApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("imports datasets and launches runs through the RAG evaluation routes", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ id: "dataset-1", name: "Smoke", source_format: "jsonl", case_count: 1, cases: [], metadata: {} }))
      .mockResolvedValueOnce(jsonResponse({ id: "run-1", dataset_id: "dataset-1", dataset_name: "Smoke", status: "queued", stage: "queued", progress_pct: 0, case_count: 1, completed_count: 0, passed_count: 0, failed_count: 0, summary: {}, document_ids: [] }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await ragEvaluationsApi.importDataset({ name: "Smoke", content: "{\"id\":\"case-1\"}", source_format: "jsonl" });
    await ragEvaluationsApi.createRun({ dataset_id: "dataset-1", group_path: "/finance" });

    const [importUrl, importInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const [runUrl, runInit] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect(importUrl).toContain("/api/v1/rag-evaluations/datasets");
    expect(importInit.method).toBe("POST");
    expect(runUrl).toContain("/api/v1/rag-evaluations/runs");
    expect(runInit.method).toBe("POST");
    expect(new Headers(runInit.headers).get("X-CSRF-Token")).toBe("test-token");
  });
});
