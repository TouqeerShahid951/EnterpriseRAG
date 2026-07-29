import { afterEach, describe, expect, it, vi } from "vitest";

import { abbreviationsApi } from "./contracts";
import { jsonResponse } from "./contractsTestSupport";

const entry = {
  id: "entry/1",
  abbreviation: "AD",
  expansion: "Assistant Director",
  source_kind: "ui",
  source_document_id: null,
  source_document_title: null,
  source_page: null,
  source_count: 0,
  revision: 1,
  created_at: null,
  updated_at: null,
};

describe("abbreviationsApi", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("loads the single global glossary", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ glossary: null, sources: [], items: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await abbreviationsApi.get();

    const calls = fetchMock.mock.calls as unknown as Array<[unknown]>;
    expect(String(calls[0][0])).toContain("/api/v1/abbreviation-glossaries");
    expect(String(calls[0][0])).not.toContain("?");
  });

  it("creates and updates entries with CSRF protection", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(entry));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await abbreviationsApi.create({ abbreviation: "AD", expansion: "Assistant Director" });
    await abbreviationsApi.update("entry/1", { abbreviation: "AD", expansion: "Associate Director", expected_revision: 1 });

    const create = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const update = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect(create[1].method).toBe("POST");
    expect(new Headers(create[1].headers).get("X-CSRF-Token")).toBe("test-token");
    expect(update[0]).toContain("/entries/entry%2F1");
    expect(update[1].method).toBe("PATCH");
    expect(update[1].body).toBe(JSON.stringify({ abbreviation: "AD", expansion: "Associate Director", expected_revision: 1 }));
  });

  it("deletes the expected revision through an encoded path", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await abbreviationsApi.remove("entry/1", 3);

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/entries/entry%2F1?expected_revision=3");
    expect(init.method).toBe("DELETE");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("test-token");
  });

  it("removes a PDF source through an encoded path", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "csrf_token=test-token" });

    await abbreviationsApi.removeSource("document/1");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/sources/document%2F1");
    expect(init.method).toBe("DELETE");
  });
});
