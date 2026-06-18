import { afterEach, describe, expect, it, vi } from "vitest";

import { adminApi, auditApi, documentsApi, ingestJobsApi, ragEvaluationsApi } from "./contracts";

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
    expect(response.items[0].clearance_level).toBe("NATO_RESTRICTED");
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

  it("updates document clearance through a CSRF-protected patch", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ...legacyDocument, clearance_level: "NATO_SECRET", ingest_status: "completed" }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    const response = await documentsApi.updateClearance("doc/1", { clearance_level: "NATO_SECRET" });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/docs/doc%2F1/clearance");
    expect(init.method).toBe("PATCH");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify({ clearance_level: "NATO_SECRET" }));
    expect(response.clearance_level).toBe("NATO_SECRET");
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

describe("ingestJobsApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("cancels an encoded ingestion job with CSRF protection", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ job_id: "job/1", status: "cancelled", message: "Ingestion job cancelled." }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await ingestJobsApi.cancel("job/1");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/ingest-jobs/job%2F1/cancel");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
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

function auditSummary() {
  return {
    total: 0,
    document_events: 0,
    auth_events: 0,
    system_events: 0,
    actor_count: 0,
    event_type_count: 0,
    category_counts: {},
    target_type_counts: {},
    event_type_counts: {},
  };
}
