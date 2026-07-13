import { afterEach, describe, expect, it, vi } from "vitest";

import { adminApi, ingestJobsApi, uploadApi } from "./contracts";
import { jsonResponse } from "./contractsTestSupport";

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

  it("loads an encoded user's chat activity", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({
        items: [{ id: "session/1", title: "Budget question", created_at: "2026-06-18T10:00:00Z", updated_at: "2026-06-18T10:05:00Z", question_count: 1 }],
        total: 1,
        limit: 10,
        offset: 20,
      }))
      .mockResolvedValueOnce(jsonResponse({
        id: "session/1",
        title: "Budget question",
        created_at: "2026-06-18T10:00:00Z",
        updated_at: "2026-06-18T10:05:00Z",
        turns: [{ id: "user-1", role: "user", content: "What changed?", createdAt: "2026-06-18T10:00:00Z" }],
      }));
    vi.stubGlobal("fetch", fetchMock);

    const page = await adminApi.listUserChatActivity("user/1", { limit: 10, offset: 20 });
    const session = await adminApi.getUserChatActivitySession("user/1", "session/1");

    const calls = fetchMock.mock.calls as unknown as Array<[unknown]>;
    expect(String(calls[0][0])).toContain("/api/v1/admin/users/user%2F1/chat-activity?limit=10&offset=20");
    expect(String(calls[1][0])).toContain("/api/v1/admin/users/user%2F1/chat-activity/session%2F1");
    expect(page.items[0].questionCount).toBe(1);
    expect(session.turns).toHaveLength(1);
  });

  it("resets an encoded user's password with CSRF protection", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      id: "user/1",
      email: "member@example.test",
      name: "Member",
      account_type: "member",
      group_paths: [],
      clearance_level: "NATO_RESTRICTED",
      is_active: true,
      permission_version: 1,
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await adminApi.resetUserPassword("user/1", { temporary_password: "NewPass123!" });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/admin/users/user%2F1/reset-password");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify({ temporary_password: "NewPass123!" }));
  });

  it("restores the environment-backed RAG config through a CSRF-protected delete", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ source: "env", provider: "ollama" }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    const response = await adminApi.resetRagConfig();

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/admin/rag-config");
    expect(init.method).toBe("DELETE");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(response.source).toBe("env");
  });
});
describe("uploadApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("omits ingestion quality from document uploads", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ job_id: "job-1" }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await uploadApi.document({
      file: new File(["%PDF-1.7"], "policy.pdf", { type: "application/pdf" }),
      group_path: "/legal",
      shared_group_paths: ["/finance", "/ops"],
    });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/upload");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    const body = init.body as FormData;
    expect(body.has("quality_preset")).toBe(false);
    expect(body.get("group_path")).toBe("/legal");
    expect(body.getAll("shared_group_paths")).toEqual(["/finance", "/ops"]);
  });
});

describe("ingestJobsApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("filters ingestion jobs to uploads from the current user", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], total: 0, limit: 20, offset: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await ingestJobsApi.list({ origin: "upload", uploaded_by_me: true, limit: 20, offset: 0 });

    const calls = fetchMock.mock.calls as unknown as Array<[unknown]>;
    const url = String(calls[0][0]);
    expect(url).toContain("/api/v1/ingest-jobs?");
    expect(url).toContain("origin=upload");
    expect(url).toContain("uploaded_by_me=true");
    expect(url).toContain("limit=20");
    expect(url).toContain("offset=0");
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

  it("loads GraphRAG status from ingestion health", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      enabled: true,
      queue_name: "graphrag:jobs",
      queued_jobs: 2,
      queue_error: null,
      worker_online: true,
      worker_error: null,
      active_jobs: 1,
      observed_pool_size: 1,
      workers: [],
      active_tasks: [],
      queued_tasks: [],
    }));
    vi.stubGlobal("fetch", fetchMock);

    await ingestJobsApi.graphragStatus();

    const calls = fetchMock.mock.calls as unknown as Array<[unknown]>;
    expect(String(calls[0][0])).toContain("/api/v1/ingest-jobs/graphrag-status");
  });

  it("cancels graph enrichment with its task id and CSRF protection", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      task_id: "graph/task-1",
      job_id: "job/1",
      document_id: "doc-1",
      status: "cancelled",
      message: "Running graph enrichment cancelled.",
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await ingestJobsApi.cancelGraphEnrichment("job/1", "graph/task-1");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/ingest-jobs/job%2F1/graph-enrichment/cancel");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify({ task_id: "graph/task-1" }));
  });
});
