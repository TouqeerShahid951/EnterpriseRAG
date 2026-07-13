import { describe, expect, it } from "vitest";

import { toApiError } from "./response";

describe("toApiError", () => {
  it("does not expose HTML error bodies as user-facing messages", async () => {
    const error = await toApiError(new Response("<html><body><h1>502 Bad Gateway</h1></body></html>", {
      status: 502,
      statusText: "Bad Gateway",
      headers: { "Content-Type": "text/html" },
    }));

    expect(error).toMatchObject({
      status: 502,
      code: "Bad Gateway",
      message: "Bad Gateway",
    });
  });

  it("keeps plain text error bodies", async () => {
    const error = await toApiError(new Response("Upload size limit exceeded.", {
      status: 413,
      statusText: "Payload Too Large",
      headers: { "Content-Type": "text/plain" },
    }));

    expect(error.message).toBe("Upload size limit exceeded.");
  });
});
