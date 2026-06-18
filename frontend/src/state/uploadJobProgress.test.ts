import { describe, expect, it } from "vitest";

import { formatStageProgress, formatUploadWarning, isUploadCancellableStatus, isUploadTerminalStatus } from "./uploadJobProgress";

describe("upload job progress formatting", () => {
  it("formats metadata stage progress labels", () => {
    expect(formatStageProgress({ unit: "metadata", current: 1, total: 13, label: null })).toBe("Metadata step 1 of 13");
    expect(formatStageProgress({ unit: "metadata", current: 0, total: 1, label: "Waiting on metadata model for 15s" })).toBe("Waiting on metadata model for 15s");
  });

  it("maps metadata warning codes to readable labels", () => {
    expect(formatUploadWarning("ollama_metadata_timeout")).toBe("Metadata model timed out; fallback metadata was used");
    expect(formatUploadWarning("unknown_warning")).toBe("Unknown Warning");
  });

  it("treats cancelled jobs as terminal but not cancellable", () => {
    expect(isUploadTerminalStatus("cancelled")).toBe(true);
    expect(isUploadCancellableStatus("cancelled")).toBe(false);
    expect(isUploadCancellableStatus("processing")).toBe(true);
    expect(isUploadCancellableStatus("human_review")).toBe(true);
  });
});
