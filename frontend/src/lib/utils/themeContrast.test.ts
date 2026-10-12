import { describe, expect, it } from "vitest";

import { contrastRatio, readableForeground, readableThemeColor, themeCanvasColor } from "./themeContrast";

describe("theme contrast", () => {
  it("chooses a readable foreground for customized primary backgrounds in either mode", () => {
    expect(readableForeground("#A3C2FF")).toBe("#000000");
    expect(readableForeground("#123456")).toBe("#FFFFFF");
    expect(contrastRatio("#A3C2FF", readableForeground("#A3C2FF"))).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio("#123456", readableForeground("#123456"))).toBeGreaterThanOrEqual(4.5);
  });

  it("falls back to the theme foreground when a custom text color is not readable", () => {
    expect(readableThemeColor("#6F6F6F", "dark")).toBe("#FFFFFF");
    expect(readableThemeColor("#b8a77a", "light")).toBe("#000000");
    expect(readableThemeColor("#005FCC", "light")).toBe("#005FCC");
  });

  it("applies the configured background as a controlled tint in both themes", () => {
    expect(themeCanvasColor("#AABBCC", "light")).toBe("color-mix(in srgb, #AABBCC 8%, #F7F6F8)");
    expect(themeCanvasColor("#AABBCC", "dark")).toBe("color-mix(in srgb, #AABBCC 16%, #1B1B20)");
  });

  it("uses the theme canvas when the background draft is invalid", () => {
    expect(themeCanvasColor("not-a-color", "light")).toBe("#F7F6F8");
    expect(themeCanvasColor(null, "dark")).toBe("#1B1B20");
  });
});
