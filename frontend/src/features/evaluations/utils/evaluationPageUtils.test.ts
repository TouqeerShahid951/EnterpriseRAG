import { describe, expect, it } from "vitest";

import { faithfulnessResultLabel, optionalPercent } from "./evaluationPageUtils";

describe("evaluation faithfulness display", () => {
  it("does not render unmeasured faithfulness as a pass", () => {
    expect(optionalPercent({ faithfulness_pass_rate: null }, ["faithfulness_pass_rate"])).toBeNull();
    expect(faithfulnessResultLabel("skipped", 1)).toBe("Not evaluated");
    expect(faithfulnessResultLabel("failed", 0)).toBe("Error");
    expect(faithfulnessResultLabel("checked", 0.92)).toBe("92%");
  });
});
