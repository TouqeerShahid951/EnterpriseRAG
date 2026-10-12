import { describe, expect, it } from "vitest";

import { readableForeground } from "@/lib/utils/themeContrast";

describe("theme primary foreground", () => {
  it("resolves a readable foreground in light mode too", () => {
    expect(readableForeground("#A3C2FF")).toBe("#000000");
  });

  it("keeps an adaptive foreground override for dark-theme brand colors", () => {
    expect(readableForeground("#1B1B20")).toBe("#FFFFFF");
  });
});
