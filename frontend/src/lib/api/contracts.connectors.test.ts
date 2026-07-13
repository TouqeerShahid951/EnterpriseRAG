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
