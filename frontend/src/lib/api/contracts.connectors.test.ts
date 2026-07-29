import { afterEach, describe, expect, it, vi } from "vitest";

import { connectorApi } from "./contracts";
import { jsonResponse } from "./contractsTestSupport";

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

  it("returns failed connection tests from HTTP 200 responses", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      status: "failed",
      message: "Connection refused.",
      detail: {},
      profile: null,
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    const result = await connectorApi.testProfile("profile/1");

    expect(result.status).toBe("failed");
    expect(result.message).toBe("Connection refused.");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/connectors/profiles/profile%2F1/test");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify(null));
  });

  it("returns successful schema introspection snapshots from HTTP 200 responses", async () => {
    const snapshot = {
      id: "snapshot-1",
      profile_id: "profile/1",
      connector_type: "postgres",
      schema_json: { tables: [{ key: "public.cases", columns: [] }] },
      status: "ok",
      error_message: null,
      created_at: "2026-07-19T10:00:00Z",
    };
    const fetchMock = vi.fn(async () => jsonResponse(snapshot));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    const result = await connectorApi.introspectProfile("profile/1");

    expect(result).toEqual(snapshot);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/connectors/profiles/profile%2F1/introspect");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify(null));
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

  it("approves schema catalogs through encoded connector paths", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      id: "catalog/1",
      profile_id: "profile/1",
      connector_type: "postgres",
      status: "approved",
      group_path: "/ops",
      clearance_level: "NATO_SECRET",
      catalog_json: { tables: [{ key: "public.cases", allowed: true }] },
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });
    const request = {
      catalog_json: { tables: [{ key: "public.cases", allowed: true }] },
      status: "approved" as const,
      group_path: "/ops",
      group_paths: ["/ops"],
      clearance_level: "NATO_SECRET" as const,
    };

    const result = await connectorApi.updateSchemaCatalog("profile/1", "catalog/1", request);

    expect(result.status).toBe("approved");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/connectors/profiles/profile%2F1/schema-catalogs/catalog%2F1");
    expect(init.method).toBe("PUT");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
    expect(init.body).toBe(JSON.stringify(request));
  });
});
