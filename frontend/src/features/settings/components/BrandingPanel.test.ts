import { describe, expect, it } from "vitest";

import { validBrandingDraft } from "./BrandingPanel";

const validDraft = {
  app_name: "Acme",
  primary_color: "#123456",
  accent_color: "#654321",
  background_color: "#101112",
  login_message: "Welcome.",
  support_url: null,
  theme_mode: "user" as const,
  h1_size: "standard" as const,
  h1_weight: "bold" as const,
  h1_color: null,
  h2_size: "standard" as const,
  h2_weight: "bold" as const,
  h2_color: null,
  body_size: "standard" as const,
};

describe("validBrandingDraft", () => {
  it("requires branded text and valid colors", () => {
    expect(validBrandingDraft(validDraft)).toBe(true);
    expect(validBrandingDraft({ ...validDraft, accent_color: "blue" })).toBe(false);
    expect(validBrandingDraft({ ...validDraft, background_color: "blue" })).toBe(false);
    expect(validBrandingDraft({ ...validDraft, h1_color: "blue" })).toBe(false);
    expect(validBrandingDraft({ ...validDraft, login_message: " " })).toBe(false);
  });
});
