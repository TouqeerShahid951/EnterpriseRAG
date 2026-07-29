import { describe, expect, it } from "vitest";

import { getPrudentiaSidebarDefaultWidth } from "./PrudentiaSidebar";

describe("PrudentiaSidebar responsive defaults", () => {
  it("steps up the default width without making laptop navigation oversized", () => {
    expect(getPrudentiaSidebarDefaultWidth(1366)).toBe(224);
    expect(getPrudentiaSidebarDefaultWidth(1440)).toBe(240);
    expect(getPrudentiaSidebarDefaultWidth(1920)).toBe(256);
    expect(getPrudentiaSidebarDefaultWidth(2560)).toBe(272);
  });
});
