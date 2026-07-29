import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { RuntimeAdvancedSettings } from "../components/RuntimeSettingsFields";
import { InferenceRoleMatrix } from "../components/InferenceRoleMatrix";
import { modelOptionsFromDiscovery } from "../models/ragModelCatalog";
import {
  pdfImageReviewThresholdLabel,
  thresholdFromPercent,
  thresholdPercentFromConfig,
} from "../models/settingsLabels";
import { requestFromVllmForm } from "../models/vllmDeploymentForm";
import { ollamaForm } from "./settingsTestFixtures";

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

  it("renders an accessible adaptive faithfulness policy", () => {
    const markup = renderToStaticMarkup(
      <RuntimeAdvancedSettings form={ollamaForm} onChange={() => undefined} />,
    );

    expect(markup).toContain("Faithfulness checker");
    expect(markup).toContain('aria-label="Faithfulness checker policy"');
    expect(markup).toContain("local reranker");
  });

  it("renders an accessible adaptive Evidence Gate policy", () => {
    const markup = renderToStaticMarkup(
      <RuntimeAdvancedSettings form={ollamaForm} onChange={() => undefined} />,
    );

    expect(markup).toContain("Evidence Gate");
    expect(markup).toContain('aria-label="Evidence Gate policy"');
    expect(markup).toContain("low-risk factual lookups");
  });

  it("renders dedicated language-role timeout controls", () => {
    const markup = renderToStaticMarkup(
      <RuntimeAdvancedSettings form={ollamaForm} onChange={() => undefined} />,
    );

    expect(markup).toContain("Router timeout");
    expect(markup).toContain("Reasoning timeout");
    expect(markup).toContain("Faithfulness timeout");
    expect(markup).toContain('max="30"');
    expect(markup).toContain('max="300"');
  });

  it("renders an accessible SQL generation model choice", () => {
    const modelOptions = modelOptionsFromDiscovery({
      provider: "ollama",
      embedding_provider: "ollama",
      base_url: "http://ollama:11434",
      embedding_base_url: "http://ollama:11434",
      chat_models: ["answer-model", "sql-model"],
      embedding_models: ["embedding-model"],
    });
    const markup = renderToStaticMarkup(
      <InferenceRoleMatrix
        canFetchModels
        form={ollamaForm}
        modelOptions={modelOptions}
        modelsLoading={false}
        modelSelectDisabled={false}
        modelStatuses={{}}
        rerankerModelOptions={["jinaai/jina-reranker-v1-turbo-en"]}
        rerankerPlaceholder="Choose reranker"
        rerankerSelectDisabled={false}
        onChange={() => undefined}
      />,
    );

    expect(markup).toContain('aria-label="SQL generation model"');
    expect(markup).toContain("Use reasoning model");
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
