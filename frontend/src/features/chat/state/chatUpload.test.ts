import { describe, expect, it } from "vitest";

import { buildChatUploadRequest } from "./chatUpload";

describe("chat document uploads", () => {
  it("does not assign an effective date when none was provided", () => {
    const file = new File(["%PDF-1.7"], "reference.pdf", { type: "application/pdf" });

    const request = buildChatUploadRequest(file, "/finance");

    expect(request).toEqual({
      file,
      group_path: "/finance",
    });
    expect(request.effective_date).toBeUndefined();
  });
});
