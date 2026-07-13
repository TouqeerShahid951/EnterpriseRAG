import { afterEach, describe, expect, it, vi } from "vitest";

import { adminApi, auditApi, connectorApi, documentsApi, ingestJobsApi, queryApi, ragEvaluationsApi, uploadApi } from "./contracts";

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
    expect(response.items[0].owner_group_path).toBe("/finance");
    expect(response.items[0].shared_group_paths).toEqual([]);
    expect(response.items[0].access_group_paths).toEqual(["/finance"]);
    expect(response.items[0].governance_owner).toBe("space");
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

  it("updates document topics through a CSRF-protected patch", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ...legacyDocument, topics: ["OCR"], llm_topics: [], ingest_status: "complete" }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    const response = await documentsApi.updateTopics("doc/1", { topics: ["OCR"], llm_topics: [] });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/docs/doc%2F1/topics");
    expect(init.method).toBe("PATCH");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify({ topics: ["OCR"], llm_topics: [] }));
    expect(response.topics).toEqual(["OCR"]);
    expect(response.llm_topics).toEqual([]);
  });

  it("replaces document shares with CSRF protection", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      document_id: "doc-1",
      owner_group_path: "/legal",
      shared_group_paths: ["/finance"],
      access_group_paths: ["/legal", "/finance"],
      governance_owner: "system",
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    const response = await documentsApi.updateShares("doc/1", { group_paths: ["/finance"] });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/docs/doc%2F1/shares");
    expect(init.method).toBe("PUT");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify({ group_paths: ["/finance"] }));
    expect(response.governance_owner).toBe("system");
  });

  it("transfers document ownership through a CSRF-protected patch", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      ...legacyDocument,
      group_path: "/finance",
      owner_group_path: "/finance",
      shared_group_paths: ["/legal"],
      access_group_paths: ["/finance", "/legal"],
      governance_owner: "system",
      ingest_status: "complete",
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    const response = await documentsApi.transferOwnership("doc/1", { group_path: "/finance" });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/docs/doc%2F1/owner");
    expect(init.method).toBe("PATCH");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify({ group_path: "/finance" }));
    expect(response.owner_group_path).toBe("/finance");
    expect(response.shared_group_paths).toEqual(["/legal"]);
  });

  it("queues optional graph enrichment with CSRF protection", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      document_id: "doc/1",
      job_id: "job-1",
      status: "queued",
      message: "Graph enrichment queued.",
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await documentsApi.enrichGraph("doc/1");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/docs/doc%2F1/graph-enrichment");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
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

describe("documentsApi reingest", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("links a manual retry to the failed ingestion job", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ document_id: "doc/1", job_id: "job-2", status: "queued" }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await documentsApi.reingest("doc/1", { retry_of_job_id: "job-1" });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/docs/doc%2F1/reingest");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify({ retry_of_job_id: "job-1" }));
  });
});

describe("connectorApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates PostgreSQL connector profiles through the connector contract", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      id: "profile-1",
      name: "Postgres cases",
      connector_type: "postgres",
      public_config: { host: "postgres.internal", database: "cases", sslmode: "require" },
      secrets_redacted: { username: "********", password: "********" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await connectorApi.createProfile({
      name: "Postgres cases",
      connector_type: "postgres",
      public_config: { host: "postgres.internal", database: "cases", sslmode: "require" },
      secrets: { username: "readonly", password: "secret" },
    });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/connectors/profiles");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify({
      name: "Postgres cases",
      connector_type: "postgres",
      public_config: { host: "postgres.internal", database: "cases", sslmode: "require" },
      secrets: { username: "readonly", password: "secret" },
    }));
  });

  it("updates connector profiles through the connector contract", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      id: "profile-1",
      name: "Postgres reporting",
      connector_type: "postgres",
      public_config: { host: "db.internal", port: 5432, database: "cases", sslmode: "require" },
      secrets_redacted: { username: "********", password: "********" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await connectorApi.updateProfile("profile-1", {
      name: "Postgres reporting",
      public_config: { host: "db.internal", port: 5432, database: "cases", sslmode: "require" },
      secrets: { username: "readonly", password: "new-secret" },
    });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/connectors/profiles/profile-1");
    expect(init.method).toBe("PUT");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify({
      name: "Postgres reporting",
      public_config: { host: "db.internal", port: 5432, database: "cases", sslmode: "require" },
      secrets: { username: "readonly", password: "new-secret" },
    }));
  });

  it("deletes connector profiles through the connector contract", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await connectorApi.deleteProfile("profile-1");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/connectors/profiles/profile-1");
    expect(init.method).toBe("DELETE");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
  });

  it("creates approved schema catalogs through the connector contract", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      id: "catalog-1",
      profile_id: "profile-1",
      connector_type: "postgres",
      status: "approved",
      group_path: "/ops",
      clearance_level: "NATO_RESTRICTED",
      catalog_json: { tables: [] },
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await connectorApi.createSchemaCatalog("profile-1", {
      status: "approved",
      group_path: "/ops",
      clearance_level: "NATO_RESTRICTED",
      catalog_json: { tables: [] },
    });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/connectors/profiles/profile-1/schema-catalogs");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify({
      status: "approved",
      group_path: "/ops",
      clearance_level: "NATO_RESTRICTED",
      catalog_json: { tables: [] },
    }));
  });

  it("creates AI schema catalog drafts through the connector contract", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      id: "catalog-1",
      profile_id: "profile-1",
      connector_type: "postgres",
      status: "draft",
      group_path: "/ops",
      clearance_level: "NATO_RESTRICTED",
      catalog_json: { tables: [], ai_enrichment: { requires_admin_review: true } },
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await connectorApi.createAiSchemaCatalogDraft("profile-1", {
      group_path: "/ops",
      clearance_level: "NATO_RESTRICTED",
    });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/connectors/profiles/profile-1/schema-catalogs/ai-draft");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify({
      group_path: "/ops",
      clearance_level: "NATO_RESTRICTED",
    }));
  });

  it("enriches one schema catalog table through the connector contract", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      id: "catalog-1",
      profile_id: "profile-1",
      connector_type: "postgres",
      status: "draft",
      group_path: "/ops",
      clearance_level: "NATO_RESTRICTED",
      catalog_json: { tables: [], ai_enrichment: { status: "in_progress" } },
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await connectorApi.enrichSchemaCatalogTable("profile-1", "catalog-1", { table_key: "public.cases" });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/connectors/profiles/profile-1/schema-catalogs/catalog-1/ai-enrich-table");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify({ table_key: "public.cases" }));
  });
});

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

function queryResponse() {
  return {
    trace_id: "trace-1",
    answer: "Done",
    sources: [],
    artifacts: [],
    artifact_job: null,
    conflict_flag: false,
    conflict_detail: null,
    faithfulness_score: 1,
    faithfulness_status: "checked",
    unfounded_claims: [],
    intent: "aggregation",
    session_id: "session-1",
    latency_ms: 1,
    node_timings: [],
    degraded: false,
    degraded_reason: null,
    source_mode: "db_only",
    source_decision_reason: "composer_selected_database",
    source_expansion: null,
  };
}
