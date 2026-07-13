import { describe, expect, it } from "vitest";

import {
  pdfImageReviewThresholdLabel,
  requestFromVllmForm,
  thresholdFromPercent,
  thresholdPercentFromConfig,
} from "./PrudentiaSettingsPage";

describe("inference settings helpers", () => {
  it("converts OCR review threshold between config fraction and UI percent", () => {
    expect(thresholdPercentFromConfig(0.9)).toBe(90);
    expect(thresholdFromPercent(90)).toBe(0.9);
    expect(thresholdFromPercent(89)).toBe(0.89);
  });

  it("labels the PDF image review threshold, including disabled review", () => {
    expect(pdfImageReviewThresholdLabel(64)).toBe("Above 64 images");
    expect(pdfImageReviewThresholdLabel(0)).toBe("Off");
  });

  it("targets one vLLM service when applying launch limits", () => {
    const request = requestFromVllmForm({
      text: {
        max_model_len: "4096",
        gpu_memory_utilization: "0.12",
        max_num_seqs: "1",
        max_num_batched_tokens: "4096",
        kv_cache_memory_bytes: "2G",
      },
      embeddings: {
        max_model_len: "2048",
        gpu_memory_utilization: "0.05",
        max_num_seqs: "2",
        max_num_batched_tokens: "2048",
        kv_cache_memory_bytes: "",
      },
      vision: {
        max_model_len: "2048",
        gpu_memory_utilization: "0.1",
        max_num_seqs: "1",
        max_num_batched_tokens: "2048",
        kv_cache_memory_bytes: "2G",
      },
    }, ["text"]);

    expect(request.services).toEqual(["text"]);
    expect(request.text.kv_cache_memory_bytes).toBe("2G");
    expect(request.embeddings.kv_cache_memory_bytes).toBeNull();
  });
});
