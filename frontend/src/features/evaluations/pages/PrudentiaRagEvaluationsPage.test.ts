import { describe, expect, it } from "vitest";

import type { EvaluationDatasetSummary } from "@/types/api";
import { resolveEvaluationDatasetId } from "./PrudentiaRagEvaluationsPage";

const datasets: EvaluationDatasetSummary[] = [
  {
    id: "dataset-a",
    name: "Baseline",
    description: null,
    source_format: "jsonl",
    case_count: 12,
    created_by: "user-1",
    created_at: "2026-07-10T00:00:00Z",
    updated_at: "2026-07-10T00:00:00Z",
  },
  {
    id: "dataset-b",
    name: "Policy regression",
    description: null,
    source_format: "json",
    case_count: 8,
    created_by: "user-1",
    created_at: "2026-07-10T00:00:00Z",
    updated_at: "2026-07-10T00:00:00Z",
  },
];

describe("evaluation dataset launcher selection", () => {
  it("selects the dataset whose Use dataset action was clicked", () => {
    expect(resolveEvaluationDatasetId(datasets, "dataset-b", "")).toBe("dataset-b");
  });

  it("preserves a valid selection made in the launcher", () => {
    expect(resolveEvaluationDatasetId(datasets, "dataset-b", "dataset-a")).toBe("dataset-a");
  });

  it("falls back safely when a requested dataset is no longer available", () => {
    expect(resolveEvaluationDatasetId(datasets, "dataset-missing", "")).toBe("dataset-a");
    expect(resolveEvaluationDatasetId([], "dataset-b", "")).toBe("");
  });
});
