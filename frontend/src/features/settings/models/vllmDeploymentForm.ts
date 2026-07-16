import type { VllmDeploymentConfigRequest } from "@/lib/api/contracts";
import type { VllmDeploymentConfig, VllmDeploymentService, VllmServiceDeploymentLimits } from "@/types/api";

export type VllmDeploymentFormState = {
  text: VllmServiceDeploymentFormState;
  embeddings: VllmServiceDeploymentFormState;
  vision: VllmServiceDeploymentFormState;
};

export type VllmRestartConfirmations = Record<VllmDeploymentService, boolean>;

export type VllmServiceDeploymentFormState = {
  max_model_len: string;
  gpu_memory_utilization: string;
  max_num_seqs: string;
  max_num_batched_tokens: string;
  kv_cache_memory_bytes: string;
};

export const VLLM_DEPLOYMENT_SERVICES: Array<{
  key: VllmDeploymentService;
  title: string;
  composeService: string;
  description: string;
  includeKvCache?: boolean;
}> = [
  {
    key: "text",
    title: "Text generation",
    composeService: "vllm-text",
    description: "Synthesis, reasoning, routing, faithfulness, and ingestion metadata when those roles use vLLM.",
    includeKvCache: true,
  },
  {
    key: "embeddings",
    title: "Embeddings",
    composeService: "vllm-embeddings",
    description: "OpenAI-compatible embedding service. FastEmbed runs separately and does not require this container.",
  },
  {
    key: "vision",
    title: "Vision",
    composeService: "vllm-vision",
    description: "Image OCR, captions, and layout repair when vision is assigned to vLLM.",
    includeKvCache: true,
  },
];

const VLLM_KV_CACHE_PATTERN = /^[1-9][0-9]*(B|K|M|G|T|KB|MB|GB|TB|KiB|MiB|GiB|TiB)?$/;

export const DEFAULT_VLLM_DEPLOYMENT_FORM: VllmDeploymentFormState = {
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
    gpu_memory_utilization: "0.10",
    max_num_seqs: "1",
    max_num_batched_tokens: "2048",
    kv_cache_memory_bytes: "2G",
  },
};

export const DEFAULT_VLLM_RESTART_CONFIRMATIONS: VllmRestartConfirmations = {
  text: false,
  embeddings: false,
  vision: false,
};

export function vllmFormFromConfig(config: VllmDeploymentConfig): VllmDeploymentFormState {
  return {
    text: vllmServiceFormFromLimits(config.text),
    embeddings: vllmServiceFormFromLimits(config.embeddings),
    vision: vllmServiceFormFromLimits(config.vision),
  };
}

function vllmServiceFormFromLimits(limits: VllmServiceDeploymentLimits): VllmServiceDeploymentFormState {
  return {
    max_model_len: String(limits.max_model_len),
    gpu_memory_utilization: String(limits.gpu_memory_utilization),
    max_num_seqs: String(limits.max_num_seqs),
    max_num_batched_tokens: String(limits.max_num_batched_tokens),
    kv_cache_memory_bytes: limits.kv_cache_memory_bytes ?? "",
  };
}

export function requestFromVllmForm(
  form: VllmDeploymentFormState,
  services?: VllmDeploymentService[],
): VllmDeploymentConfigRequest {
  const request: VllmDeploymentConfigRequest = {
    text: vllmLimitsRequestFromForm(form.text),
    embeddings: vllmLimitsRequestFromForm(form.embeddings),
    vision: vllmLimitsRequestFromForm(form.vision),
  };
  if (services?.length) {
    request.services = services;
  }
  return request;
}

function vllmLimitsRequestFromForm(form: VllmServiceDeploymentFormState): VllmServiceDeploymentLimits {
  return {
    max_model_len: Number(form.max_model_len),
    gpu_memory_utilization: Number(form.gpu_memory_utilization),
    max_num_seqs: Number(form.max_num_seqs),
    max_num_batched_tokens: Number(form.max_num_batched_tokens),
    kv_cache_memory_bytes: form.kv_cache_memory_bytes.trim() || null,
  };
}

export function canSubmitVllmDeploymentConfig(form: VllmDeploymentFormState): boolean {
  return [form.text, form.embeddings, form.vision].every(canSubmitVllmServiceLimits);
}

function canSubmitVllmServiceLimits(form: VllmServiceDeploymentFormState): boolean {
  const request = vllmLimitsRequestFromForm(form);
  return Boolean(
    Number.isFinite(request.max_model_len) &&
      request.max_model_len >= 256 &&
      request.max_model_len <= 262144 &&
      Number.isFinite(request.gpu_memory_utilization) &&
      request.gpu_memory_utilization > 0 &&
      request.gpu_memory_utilization <= 1 &&
      Number.isFinite(request.max_num_seqs) &&
      request.max_num_seqs >= 1 &&
      request.max_num_seqs <= 1024 &&
      Number.isFinite(request.max_num_batched_tokens) &&
      request.max_num_batched_tokens >= 256 &&
      request.max_num_batched_tokens <= 262144 &&
      (!request.kv_cache_memory_bytes || VLLM_KV_CACHE_PATTERN.test(request.kv_cache_memory_bytes)),
  );
}
