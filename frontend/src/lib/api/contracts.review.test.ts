import { afterEach, describe, expect, it, vi } from "vitest";

import { reviewApi } from "./contracts";
import { jsonResponse } from "./contractsTestSupport";

describe("reviewApi", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("loads the distinct pending-document summary", async () => {
    const fetchMock = vi.fn(async (_url: string) =>
      jsonResponse({ pending_document_count: 3 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await reviewApi.summary();

    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/v1/review-queue/summary");
    expect(response.pending_document_count).toBe(3);
  });
});
