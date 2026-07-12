import { describe, expect, it } from "vitest";

import { passwordChangeValidation } from "./PrudentiaAccountPage";

describe("account password validation", () => {
  it("requires a current password, eight characters, and matching confirmation", () => {
    expect(passwordChangeValidation("", "new-password", "new-password").canSubmit).toBe(false);
    expect(passwordChangeValidation("current", "short", "short").canSubmit).toBe(false);
    expect(passwordChangeValidation("current", "new-password", "different")).toEqual({
      canSubmit: false,
      showMismatch: true,
    });
    expect(passwordChangeValidation("current", "new-password", "new-password")).toEqual({
      canSubmit: true,
      showMismatch: false,
    });
  });

  it("waits until confirmation has content before announcing a mismatch", () => {
    expect(passwordChangeValidation("current", "new-password", "").showMismatch).toBe(false);
  });
});
