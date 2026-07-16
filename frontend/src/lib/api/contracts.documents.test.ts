import { afterEach, describe, expect, it, vi } from "vitest";

import { documentsApi } from "./contracts";
import { jsonResponse, legacyDocument } from "./contractsTestSupport";

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

  it("loads the lightweight document catalog summary", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      groups: [{ group_path: "/finance", count: 3 }],
      total: 3,
    }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await documentsApi.summary();

    const calls = fetchMock.mock.calls as unknown as Array<[unknown]>;
    expect(String(calls[0][0])).toContain("/api/v1/docs/summary");
    expect(response.total).toBe(3);
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
