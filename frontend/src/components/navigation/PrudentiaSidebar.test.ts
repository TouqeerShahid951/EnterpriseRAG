import { describe, expect, it } from "vitest";

import { reviewQueueBadgeCount } from "./PrudentiaSidebar";

describe("PrudentiaSidebar badge helpers", () => {
  it("hides the review badge until a queue count is available", () => {
    expect(reviewQueueBadgeCount(undefined, undefined)).toBeNull();
    expect(reviewQueueBadgeCount(null, null)).toBeNull();
  });

  it("adds OCR review rows and image review candidates", () => {
    expect(reviewQueueBadgeCount(3, 7)).toBe(10);
  });

  it("uses whichever review source has loaded", () => {
    expect(reviewQueueBadgeCount(4, undefined)).toBe(4);
    expect(reviewQueueBadgeCount(undefined, 6)).toBe(6);
  });
});
