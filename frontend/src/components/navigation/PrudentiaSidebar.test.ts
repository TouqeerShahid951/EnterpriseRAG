import { describe, expect, it } from "vitest";

import { getPrudentiaSidebarDefaultWidth, reviewQueueBadgeCount } from "./PrudentiaSidebar";

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

describe("PrudentiaSidebar responsive defaults", () => {
  it("steps up the default width without making laptop navigation oversized", () => {
    expect(getPrudentiaSidebarDefaultWidth(1366)).toBe(224);
    expect(getPrudentiaSidebarDefaultWidth(1440)).toBe(240);
    expect(getPrudentiaSidebarDefaultWidth(1920)).toBe(256);
    expect(getPrudentiaSidebarDefaultWidth(2560)).toBe(272);
  });
});
