import { describe, expect, it } from "vitest";

import { summarizeRepeatedValues } from "./RagEvaluationDiagnostics";

describe("RAG evaluation diagnostics helpers", () => {
  it("groups repeated evidence values and reports hidden distinct values", () => {
    const summary = summarizeRepeatedValues(["policy.pdf", "guide.pdf", "policy.pdf", "appendix.pdf", "notes.pdf", "guide.pdf"], 3);

    expect(summary.items).toEqual([
      { value: "guide.pdf", count: 2 },
      { value: "policy.pdf", count: 2 },
      { value: "appendix.pdf", count: 1 },
    ]);
    expect(summary.hiddenCount).toBe(1);
  });
});
