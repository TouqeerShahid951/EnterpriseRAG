import { afterEach, describe, expect, it, vi } from "vitest";

import { adminApi, documentsApi, ragEvaluationsApi } from "./contracts";

const legacyDocument = {
  id: "doc-1",
  title: "Legacy document",
  doc_type: "report",
  group_path: "/finance",
  effective_date: "2026-05-25",
  expiry_date: null,
  description: null,
  summary: null,
  language: null,
  topics: [],
  llm_topics: [],
  auto_doc_type: null,
  extracted_dates: {},
  metadata_flags: {},
  entities: [],
  cross_references: [],
  claims: [],
  is_current: true,
  uploaded_by: "local",
  superseded_by: null,
  created_at: "2026-05-25T00:00:00Z",
};

describe("documentsApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("normalizes legacy document responses without ingest_status", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [legacyDocument], total: 1 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await documentsApi.list();

    expect(response.items[0].ingest_status).toBe("unknown");
    expect(response.items[0].deleted_at).toBeNull();
  });

  it("builds backward-compatible document list filters", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await documentsApi.list({ state: "deleted", group_path: "/finance", include_descendants: false });

    const calls = fetchMock.mock.calls as unknown as Array<[unknown]>;
    const url = String(calls[0][0]);
    expect(url).toContain("/api/v1/docs?");
    expect(url).toContain("state=deleted");
    expect(url).toContain("group_path=%2Ffinance");
    expect(url).not.toContain("include_descendants");
  });
});

describe("adminApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("deletes an encoded user id with CSRF protection", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await adminApi.deleteUser("user/1");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/admin/users/user%2F1");
    expect(init.method).toBe("DELETE");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
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

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
