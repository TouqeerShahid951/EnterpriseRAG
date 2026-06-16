import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, Cpu, Info, Laptop, Network, RefreshCw, Save, ServerCog, Wifi } from "lucide-react";

import { adminApi, type IngestConfigRequest, type RagConfigRequest, type VllmDeploymentConfigRequest } from "../api/contracts";
import { isPlatformAdmin } from "../authz";
import { useToast } from "../components/feedback/ToastProvider";
import { Fact, InlineMessage } from "../components/layout/Common";
import { FahamBasicPage } from "../components/layout/FahamWorkspace";
import type { RouteId } from "../routes";
import type {
  IngestConfig,
  RagConfig,
  RagConfigTestResult,
  RagModelDiscoveryResult,
  User as AuthUser,
  VllmDeploymentConfig,
  VllmServiceDeploymentLimits,
} from "../types/api";
import { errorMessage, formatDateTime } from "../utils/format";

export function FahamSettingsPage({ currentUser, onLogout, onNavigate }: Props) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const isAdmin = isPlatformAdmin(currentUser);
  const [activeConfigPanel, setActiveConfigPanel] = useState<ConfigPanel>("runtime");
  const [ragDraft, setRagDraft] = useState<RagConfigFormState>(DEFAULT_RAG_FORM);
  const [ragModelLookup, setRagModelLookup] = useState<RagModelLookupTarget | null>(null);
  const [vllmDraft, setVllmDraft] = useState<VllmDeploymentFormState>(DEFAULT_VLLM_DEPLOYMENT_FORM);
  const [vllmRestartConfirmed, setVllmRestartConfirmed] = useState(false);
  const [workerConcurrency, setWorkerConcurrency] = useState(1);
  const [highConcurrencyConfirmed, setHighConcurrencyConfirmed] = useState(false);
  const ragEndpoints = endpointsFromForm(ragDraft);
  const canFetchRagModels = isAdmin && Object.values(ragEndpoints).every(canFetchModelsForEndpoint);
  const ragConfigQuery = useQuery({
    queryKey: ["admin", "rag-config"],
    queryFn: adminApi.getRagConfig,
    enabled: isAdmin,
    retry: false,
  });
  const ingestConfigQuery = useQuery({
    queryKey: ["admin", "ingest-config"],
    queryFn: adminApi.getIngestConfig,
    enabled: isAdmin,
    retry: false,
  });
  const vllmDeploymentQuery = useQuery({
    queryKey: ["admin", "vllm-deployment-config"],
    queryFn: adminApi.getVllmDeploymentConfig,
    enabled: isAdmin,
    retry: false,
  });
  const rerankerModelsQuery = useQuery({
    queryKey: ["admin", "rag-config", "rerankers"],
    queryFn: adminApi.listRerankerModels,
    enabled: isAdmin,
    retry: false,
  });
  const ragModelsQuery = useQuery({
    queryKey: ["admin", "rag-config", "models", ragModelLookup],
    queryFn: () => {
      if (!ragModelLookup) {
        throw new Error("Missing inference endpoint.");
      }
      return adminApi.listRagModels(ragModelLookup);
    },
    enabled: isAdmin && ragModelLookup !== null,
    retry: false,
  });
  const testRagConfigMutation = useMutation<RagConfigTestResult, Error, RagConfigRequest>({
    mutationFn: adminApi.testRagConfig,
    onSuccess: (result, request) => {
      const modelOptions = modelOptionsFromDiscovery(result);
      queryClient.setQueryData(["admin", "rag-config", "models", discoveryTarget(request)], {
        provider: result.provider,
        base_url: result.base_url,
        embedding_base_url: result.embedding_base_url,
        reasoning_base_url: result.reasoning_base_url,
        routing_base_url: result.routing_base_url,
        faithfulness_base_url: result.faithfulness_base_url,
        ingestion_base_url: result.ingestion_base_url,
        chat_models: modelOptions.chat,
        embedding_models: modelOptions.embedding,
        reasoning_models: modelOptions.reasoning,
        routing_models: modelOptions.routing,
        faithfulness_models: modelOptions.faithfulness,
        ingestion_models: modelOptions.ingestion,
        vision_models: modelOptions.vision,
      });
      notify({
        title: "Draft validated",
        description: `${providerName(result.provider)} responded. Chat ${formatLatency(result.health.chat_latency_ms)}, embeddings ${formatLatency(result.health.embed_latency_ms)}.`,
        tone: "success",
      });
    },
    onError: (error) => notify({
      title: "Model config test failed",
      description: errorMessage(error, "Model config test failed."),
      tone: "error",
    }),
  });
  const saveRagConfigMutation = useMutation<RagConfig, Error, RagConfigRequest>({
    mutationFn: adminApi.updateRagConfig,
    onSuccess: (config) => {
      setRagDraft(formFromConfig(config));
      queryClient.setQueryData(["admin", "rag-config"], config);
      notify({ title: "Model config saved", description: "The runtime configuration is now active.", tone: "success" });
    },
    onError: (error) => notify({
      title: "Model config save failed",
      description: errorMessage(error, "Model config save failed."),
      tone: "error",
    }),
  });
  const saveIngestConfigMutation = useMutation<IngestConfig, Error, IngestConfigRequest>({
    mutationFn: adminApi.updateIngestConfig,
    onSuccess: (config) => {
      setWorkerConcurrency(safeWorkerConcurrency(config.worker_concurrency));
      setHighConcurrencyConfirmed(false);
      queryClient.setQueryData(["admin", "ingest-config"], config);
      notify({
        title: config.apply_status === "applied" ? "Worker capacity applied" : "Worker capacity saved",
        description: config.apply_status === "applied"
          ? "The online worker picked up the new concurrency."
          : "The value will apply when a worker is online.",
        tone: config.apply_status === "applied" ? "success" : "warning",
      });
    },
    onError: (error) => notify({
      title: "Worker capacity update failed",
      description: errorMessage(error, "Unable to apply worker capacity."),
      tone: "error",
    }),
  });
  const saveVllmDeploymentMutation = useMutation<VllmDeploymentConfig, Error, VllmDeploymentConfigRequest>({
    mutationFn: adminApi.updateVllmDeploymentConfig,
    onSuccess: (config) => {
      setVllmDraft(vllmFormFromConfig(config));
      setVllmRestartConfirmed(false);
      queryClient.setQueryData(["admin", "vllm-deployment-config"], config);
      notify({
        title: "vLLM limits saved",
        description: config.message ?? "Restart is required before the containers use the saved limits.",
        tone: "warning",
      });
    },
    onError: (error) => notify({
      title: "vLLM limit save failed",
      description: errorMessage(error, "Unable to save vLLM deployment limits."),
      tone: "error",
    }),
  });
  const applyVllmDeploymentMutation = useMutation<VllmDeploymentConfig, Error, VllmDeploymentConfigRequest>({
    mutationFn: adminApi.applyVllmDeploymentConfig,
    onSuccess: (config) => {
      setVllmDraft(vllmFormFromConfig(config));
      setVllmRestartConfirmed(false);
      queryClient.setQueryData(["admin", "vllm-deployment-config"], config);
      notify({
        title: "vLLM restart launched",
        description: config.message ?? "The vLLM containers were recreated with the saved limits.",
        tone: "success",
      });
    },
    onError: (error) => notify({
      title: "vLLM restart failed",
      description: errorMessage(error, "Unable to apply vLLM deployment limits."),
      tone: "error",
    }),
  });
  useEffect(() => {
    if (ragConfigQuery.data) {
      setRagDraft(formFromConfig(ragConfigQuery.data));
    }
  }, [ragConfigQuery.data]);
  useEffect(() => {
    if (ingestConfigQuery.data) {
      setWorkerConcurrency(safeWorkerConcurrency(ingestConfigQuery.data.worker_concurrency));
    }
  }, [ingestConfigQuery.data]);
  useEffect(() => {
    if (vllmDeploymentQuery.data) {
      setVllmDraft(vllmFormFromConfig(vllmDeploymentQuery.data));
      setVllmRestartConfirmed(false);
    }
  }, [vllmDeploymentQuery.data]);

  useEffect(() => {
    if (!canFetchRagModels) {
      setRagModelLookup(null);
      return;
    }

    const timer = window.setTimeout(() => setRagModelLookup(discoveryTarget(requestFromForm(ragDraft))), 400);
    return () => window.clearTimeout(timer);
  }, [
    canFetchRagModels,
    ragDraft.provider,
    ragEndpoints.chat.host,
    ragEndpoints.chat.port,
    ragEndpoints.embedding.host,
    ragEndpoints.embedding.port,
    ragEndpoints.reasoning.host,
    ragEndpoints.reasoning.port,
    ragEndpoints.routing.host,
    ragEndpoints.routing.port,
    ragEndpoints.faithfulness.host,
    ragEndpoints.faithfulness.port,
    ragEndpoints.ingestion.host,
    ragEndpoints.ingestion.port,
  ]);

  const ragRequest = requestFromForm(ragDraft);
  const ragRequestSignature = JSON.stringify(ragRequest);
  const activeRagRequest = ragConfigQuery.data ? requestFromForm(formFromConfig(ragConfigQuery.data)) : null;
  const ragDraftIsDirty = activeRagRequest !== null && JSON.stringify(activeRagRequest) !== ragRequestSignature;
  const ragModelsMatchDraft =
    ragModelLookup !== null && JSON.stringify(ragModelLookup) === JSON.stringify(discoveryTarget(ragRequest));
  const ragModelOptions = modelOptionsFromDiscovery(ragModelsMatchDraft ? ragModelsQuery.data : undefined);
  const rerankerModelOptions = rerankerOptionsFromCatalog(rerankerModelsQuery.data);
  const ragModelsAreLoading = canFetchRagModels && (!ragModelsMatchDraft || ragModelsQuery.isPending || ragModelsQuery.isFetching);
  const ragModelSelectDisabled = !canFetchRagModels || ragModelsAreLoading;
  const ragModelPlaceholder = !canFetchRagModels ? "Enter host and port" : ragModelsAreLoading ? "Loading models" : "Choose model";
  const vllmRequest = requestFromVllmForm(vllmDraft);
  const activeVllmRequest = vllmDeploymentQuery.data ? requestFromVllmForm(vllmFormFromConfig(vllmDeploymentQuery.data)) : null;
  const vllmDraftIsDirty = activeVllmRequest !== null && JSON.stringify(activeVllmRequest) !== JSON.stringify(vllmRequest);
  const vllmFormIsValid = canSubmitVllmDeploymentConfig(vllmDraft);

  return (
    <FahamBasicPage
      activeRoute="settings"
      onLogout={onLogout}
      onNavigate={onNavigate}
      title="System Configuration"
      subtitle="Configure the active inference runtime separately from vLLM container resource limits and ingestion worker capacity."
      user={currentUser}
    >
      <div className="grid gap-6">
        {isAdmin ? <ConfigPanelTabs value={activeConfigPanel} onChange={setActiveConfigPanel} /> : null}
        {isAdmin && activeConfigPanel === "runtime" ? (
          <section className="sv-card p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <ServerCog size={18} className="text-primary" />
                <div>
                  <h2 className="text-headline-sm">Inference Runtime</h2>
                  <p className="mt-1 text-body-md text-secondary">
                    Choose the active provider, endpoints, model roles, budgets, and timeouts. Test validates this draft without
                    changing the active runtime; Save validates and activates it.
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {ragDraftIsDirty ? (
                  <span className="rounded border border-warning-amber/50 bg-warning-amber/10 px-2 py-1 text-label-sm text-warning-amber">
                    Unsaved draft
                  </span>
                ) : null}
                <span className="rounded border border-surface-border px-2 py-1 text-label-sm text-secondary">
                  Active source: {ragConfigQuery.data?.source === "workspace" ? "Workspace" : "Environment"}
                </span>
              </div>
            </div>

            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <ProviderSelector
                value={ragDraft.provider}
                onChange={(provider) => setRagDraft(providerDefaults({ ...ragDraft, provider }))}
              />
              <InferenceLocationSelector
                value={ragDraft.inference_location}
                onChange={(inference_location) => setRagDraft(inferenceLocationDefaults(ragDraft, inference_location))}
              />
              {ragDraft.provider === "vllm" ? (
                <div role="note" className="md:col-span-2 flex items-start gap-2 rounded border border-info-blue/40 bg-info-blue/10 p-3 text-body-md text-secondary">
                  <Info size={16} className="mt-0.5 shrink-0 text-info-blue" />
                  <span>
                    This panel selects the vLLM endpoints and model roles Faham uses. GPU memory, sequence, KV cache, and
                    restart settings stay under vLLM Container Resources.
                  </span>
                </div>
              ) : null}
              <div className="grid gap-4 md:col-span-2 md:grid-cols-[minmax(0,1fr)_14rem]">
                <label className="sv-field">
                  <span className="sv-label">{ragDraft.provider === "ollama" ? "Ollama host" : "vLLM chat host"}</span>
                  <input
                    aria-describedby="inference-host-help"
                    value={ragEndpoints.chat.host}
                    onChange={(event) => setRagDraft({ ...ragDraft, host: event.target.value })}
                    placeholder="192.168.1.50"
                    disabled={ragDraft.inference_location === "local"}
                    className="sv-input"
                  />
                  <span id="inference-host-help" className="text-body-md text-secondary">
                    {ragDraft.inference_location === "local"
                      ? `The backend and workers reach ${providerName(ragDraft.provider)} on this machine through host.docker.internal.`
                      : `Enter a private LAN IP or .local hostname for the ${providerName(ragDraft.provider)} server.`}
                  </span>
                </label>
                <label className="sv-field">
                  <span className="sv-label">Port</span>
                  <input
                    aria-describedby="inference-port-help"
                    type="number"
                    min={1}
                    max={65535}
                    value={ragDraft.port}
                    onChange={(event) => setRagDraft({ ...ragDraft, port: event.target.value })}
                    className="sv-input"
                  />
                  <span id="inference-port-help" className="text-body-md text-secondary">
                    Default {providerName(ragDraft.provider)} API port is{" "}
                    {ragDraft.provider === "ollama"
                      ? "11434"
                      : ragDraft.inference_location === "local"
                        ? VLLM_LOCAL_PORTS.chat
                        : VLLM_NETWORK_PORTS.chat}
                    .
                  </span>
                </label>
              </div>
              {ragDraft.provider === "vllm" ? (
                <>
                  <div className="md:col-span-2 rounded border border-surface-border bg-surface-container-low p-3 text-body-md text-secondary">
                    Each endpoint must expose an OpenAI-compatible API. Reasoning, routing, faithfulness, and ingestion use the
                    chat endpoint unless overridden. Embeddings default to a separate server because they usually use a different model.
                    {ragDraft.inference_location === "local"
                      ? " Local defaults use ports 8100 and 8101 because Faham already uses host port 8000."
                      : ""}
                  </div>
                  <div className="grid gap-4 md:col-span-2 md:grid-cols-2">
                    <RoleEndpointFields form={ragDraft} role="reasoning" label="Reasoning" onChange={setRagDraft} />
                    <RoleEndpointFields form={ragDraft} role="routing" label="Routing" onChange={setRagDraft} />
                    <RoleEndpointFields form={ragDraft} role="faithfulness" label="Faithfulness" onChange={setRagDraft} />
                    <RoleEndpointFields form={ragDraft} role="ingestion" label="Ingestion metadata" onChange={setRagDraft} />
                    <RoleEndpointFields form={ragDraft} role="embedding" label="Embeddings" onChange={setRagDraft} />
                  </div>
                </>
              ) : null}
              <label className="sv-field">
                <span className="sv-label">Answer synthesis model</span>
                <ModelSelect
                  value={ragDraft.chat_model}
                  onChange={(chat_model) => setRagDraft({ ...ragDraft, chat_model })}
                  models={ragModelOptions.chat}
                  placeholder={ragModelPlaceholder}
                  disabled={ragModelSelectDisabled}
                />
                <span className="text-body-md text-secondary">Generates the final grounded answer shown in Query Intelligence.</span>
              </label>
              <label className="sv-field">
                <span className="sv-label">Routing model</span>
                <ModelSelect
                  value={ragDraft.routing_model}
                  onChange={(routing_model) => setRagDraft({ ...ragDraft, routing_model })}
                  models={ragModelOptions.routing}
                  placeholder={ragModelPlaceholder}
                  emptyLabel="Use reasoning model"
                  disabled={ragModelSelectDisabled}
                />
                <span className="text-body-md text-secondary">Verifies ambiguous query routing decisions.</span>
              </label>
              <label className="sv-field">
                <span className="sv-label">Embedding model</span>
                <ModelSelect
                  value={ragDraft.embed_model}
                  onChange={(embed_model) => setRagDraft({ ...ragDraft, embed_model })}
                  models={ragModelOptions.embedding}
                  placeholder={ragModelPlaceholder}
                  disabled={ragModelSelectDisabled}
                />
                <span className="text-body-md text-secondary">Creates vectors for document chunks and user queries.</span>
              </label>
              <label className="sv-field">
                <span className="sv-label">Reranker model</span>
                <ModelSelect
                  value={ragDraft.reranker_model}
                  onChange={(reranker_model) => setRagDraft({ ...ragDraft, reranker_model })}
                  models={rerankerModelOptions}
                  placeholder={rerankerModelsQuery.isPending ? "Loading rerankers" : "Choose reranker"}
                  disabled={rerankerModelsQuery.isPending}
                />
                <span className="text-body-md text-secondary">Reorders retrieved chunks before source selection and answer synthesis.</span>
              </label>
              <label className="sv-field">
                <span className="sv-label">Agent reasoning model</span>
                <ModelSelect
                  value={ragDraft.reasoning_model}
                  onChange={(reasoning_model) => setRagDraft({ ...ragDraft, reasoning_model })}
                  models={ragModelOptions.reasoning}
                  placeholder={ragModelPlaceholder}
                  emptyLabel="Use answer synthesis model"
                  disabled={ragModelSelectDisabled}
                />
                <span className="text-body-md text-secondary">Assists planning, retrieval rewrites, ambiguous dates, and routing when rules are not confident.</span>
              </label>
              <label className="sv-field">
                <span className="sv-label">Faithfulness model</span>
                <ModelSelect
                  value={ragDraft.faithfulness_model}
                  onChange={(faithfulness_model) => setRagDraft({ ...ragDraft, faithfulness_model })}
                  models={ragModelOptions.faithfulness}
                  placeholder={ragModelPlaceholder}
                  emptyLabel="Use answer synthesis model"
                  disabled={ragModelSelectDisabled}
                />
                <span className="text-body-md text-secondary">Checks whether the generated answer is supported by retrieved evidence.</span>
              </label>
              <label className="sv-field">
                <span className="sv-label">Ingestion metadata model</span>
                <ModelSelect
                  value={ragDraft.ingestion_model}
                  onChange={(ingestion_model) => setRagDraft({ ...ragDraft, ingestion_model })}
                  models={ragModelOptions.ingestion}
                  placeholder={ragModelPlaceholder}
                  emptyLabel="Use answer synthesis model"
                  disabled={ragModelSelectDisabled}
                />
                <span className="text-body-md text-secondary">Extracts summaries, topics, document types, and claims during ingestion.</span>
              </label>
              {ragDraft.provider === "ollama" ? (
                <label className="sv-field">
                  <span className="sv-label">Vision OCR model</span>
                  <ModelSelect
                    value={ragDraft.vision_model}
                    onChange={(vision_model) => setRagDraft({ ...ragDraft, vision_model })}
                    models={ragModelOptions.vision}
                    placeholder={ragModelPlaceholder}
                    emptyLabel="Use ingestion model"
                    disabled={ragModelSelectDisabled}
                  />
                  <span className="text-body-md text-secondary">Extracts text and captions from uploaded images and embedded document images.</span>
                </label>
              ) : null}
              {ragDraft.provider === "ollama" ? <label className="flex items-start justify-between gap-4 rounded-lg border border-surface-border bg-surface-container-low p-4 md:col-span-2">
                <span>
                  <span className="block text-body-md font-bold text-on-surface">Model thinking</span>
                  <span className="mt-1 block text-body-md text-secondary">
                    Keep this off for direct model output. Enable only to compare a thinking-capable Ollama model during Test or after Save.
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-3">
                  <span className="text-label-md text-secondary">{ragDraft.thinking_enabled ? "Enabled" : "Disabled"}</span>
                  <input
                    type="checkbox"
                    role="switch"
                    aria-label="Enable model thinking for testing"
                    checked={ragDraft.thinking_enabled}
                    onChange={(event) => setRagDraft({ ...ragDraft, thinking_enabled: event.target.checked })}
                    className="h-5 w-5 accent-primary"
                  />
                </span>
              </label> : null}
              <div className="grid gap-4 md:col-span-2 sm:grid-cols-2 lg:grid-cols-4">
                <label className="sv-field">
                  <span className="sv-label">JSON/Layout output budget</span>
                  <input
                    aria-describedby="json-output-budget-help"
                    type="number"
                    min={256}
                    max={32768}
                    value={ragDraft.json_num_predict}
                    onChange={(event) => setRagDraft({ ...ragDraft, json_num_predict: event.target.value })}
                    className="sv-input"
                  />
                  <span id="json-output-budget-help" className="text-body-md text-secondary">
                    Used by planning, composition, and artifact layout contracts.
                  </span>
                </label>
                <label className="sv-field">
                  <span className="sv-label">Evidence token budget</span>
                  <input
                    aria-describedby="evidence-token-budget-help"
                    type="number"
                    min={1000}
                    max={200000}
                    value={ragDraft.retrieval_token_budget}
                    onChange={(event) => setRagDraft({ ...ragDraft, retrieval_token_budget: event.target.value })}
                    className="sv-input"
                  />
                  <span id="evidence-token-budget-help" className="text-body-md text-secondary">
                    Caps retrieved evidence passed into synthesis.
                  </span>
                </label>
                <label className="sv-field">
                  <span className="sv-label">Chat timeout</span>
                  <input
                    type="number"
                    min={1}
                    value={ragDraft.chat_timeout_seconds}
                    onChange={(event) => setRagDraft({ ...ragDraft, chat_timeout_seconds: event.target.value })}
                    className="sv-input"
                  />
                </label>
                <label className="sv-field">
                  <span className="sv-label">Embed timeout</span>
                  <input
                    type="number"
                    min={1}
                    value={ragDraft.embed_timeout_seconds}
                    onChange={(event) => setRagDraft({ ...ragDraft, embed_timeout_seconds: event.target.value })}
                    className="sv-input"
                  />
                </label>
              </div>
            </div>

            {ragModelsAreLoading ? (
              <p aria-live="polite" className="mt-3 text-body-md text-secondary">
                Loading inference models...
              </p>
            ) : null}

            <div className="mt-5 flex flex-wrap gap-3">
              <button
                type="button"
                disabled={!canSubmitRagConfig(ragDraft) || testRagConfigMutation.isPending}
                onClick={() => testRagConfigMutation.mutate(ragRequest)}
                className="sv-action-secondary"
              >
                <Wifi size={16} />
                {testRagConfigMutation.isPending ? "Testing draft" : "Test draft"}
              </button>
              <button
                type="button"
                disabled={!canSubmitRagConfig(ragDraft) || saveRagConfigMutation.isPending}
                onClick={() => saveRagConfigMutation.mutate(ragRequest)}
                className="sv-action-primary"
              >
                <Save size={16} />
                {saveRagConfigMutation.isPending ? "Saving" : "Save & activate"}
              </button>
            </div>

            {ragConfigQuery.isError ? <InlineMessage tone="error">{errorMessage(ragConfigQuery.error, "Unable to load model config.")}</InlineMessage> : null}
            {ragModelsQuery.isError && ragModelsMatchDraft ? <InlineMessage tone="error">{errorMessage(ragModelsQuery.error, "Unable to fetch inference models.")}</InlineMessage> : null}
            {rerankerModelsQuery.isError ? <InlineMessage tone="error">{errorMessage(rerankerModelsQuery.error, "Unable to load reranker models.")}</InlineMessage> : null}
            {ragModelsQuery.isSuccess && ragModelsMatchDraft && (ragModelOptions.chat.length === 0 || ragModelOptions.embedding.length === 0) ? (
              <InlineMessage tone="warning">One or more inference endpoints returned no models.</InlineMessage>
            ) : null}
            {ragConfigQuery.data ? <CurrentRagStatus config={ragConfigQuery.data} /> : null}
          </section>
        ) : null}
        {isAdmin && activeConfigPanel === "vllm" ? (
          <section className="sv-card p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <Boxes size={18} className="text-primary" />
                <div>
                  <h2 className="text-headline-sm">vLLM Container Resources</h2>
                  <p className="mt-1 text-body-md text-secondary">
                    Tune launch-time GPU memory, model length, sequence, batched-token, and KV-cache limits for the bundled
                    vLLM containers. These settings do not choose the active inference provider.
                  </p>
                </div>
              </div>
              {vllmDraftIsDirty ? (
                <span className="rounded border border-warning-amber/50 bg-warning-amber/10 px-2 py-1 text-label-sm text-warning-amber">
                  Unsaved draft
                </span>
              ) : null}
            </div>
            {vllmDeploymentQuery.data ? (
              <div className="mt-4 grid gap-4 lg:grid-cols-3">
                <VllmLimitsEditor
                  title="Text generation"
                  limits={vllmDraft.text}
                  includeKvCache
                  onChange={(limits) => {
                    setVllmDraft({ ...vllmDraft, text: limits });
                    setVllmRestartConfirmed(false);
                  }}
                />
                <VllmLimitsEditor
                  title="Embeddings"
                  limits={vllmDraft.embeddings}
                  onChange={(limits) => {
                    setVllmDraft({ ...vllmDraft, embeddings: limits });
                    setVllmRestartConfirmed(false);
                  }}
                />
                <VllmLimitsEditor
                  title="Vision"
                  limits={vllmDraft.vision}
                  includeKvCache
                  onChange={(limits) => {
                    setVllmDraft({ ...vllmDraft, vision: limits });
                    setVllmRestartConfirmed(false);
                  }}
                />
              </div>
            ) : (
              <p aria-live="polite" className="mt-3 text-body-md text-secondary">Loading vLLM deployment limits...</p>
            )}
            {vllmDeploymentQuery.data ? (
              <dl className="mt-4 grid gap-3 sm:grid-cols-3">
                <Fact label="Source" value={labelize(vllmDeploymentQuery.data.source)} />
                <Fact label="Apply status" value={labelize(vllmDeploymentQuery.data.apply_status)} />
                <Fact label="Restart scope" value="vLLM containers only" />
              </dl>
            ) : null}
            {vllmDeploymentQuery.data?.message ? (
              <InlineMessage tone={vllmDeploymentQuery.data.apply_status === "failed" ? "error" : "warning"}>
                {vllmDeploymentQuery.data.message}
              </InlineMessage>
            ) : null}
            <label className="mt-4 flex items-start gap-2 text-body-md">
              <input
                type="checkbox"
                checked={vllmRestartConfirmed}
                onChange={(event) => setVllmRestartConfirmed(event.target.checked)}
              />
              Applying these resource limits recreates text, embedding, and vision vLLM containers and interrupts active generation.
            </label>
            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="button"
                className="sv-action-secondary"
                disabled={!vllmFormIsValid || saveVllmDeploymentMutation.isPending || applyVllmDeploymentMutation.isPending}
                onClick={() => saveVllmDeploymentMutation.mutate(vllmRequest)}
              >
                <Save size={16} />
                {saveVllmDeploymentMutation.isPending ? "Saving" : "Save draft"}
              </button>
              <button
                type="button"
                className="sv-action-primary"
                disabled={
                  !vllmFormIsValid ||
                  !vllmRestartConfirmed ||
                  saveVllmDeploymentMutation.isPending ||
                  applyVllmDeploymentMutation.isPending
                }
                onClick={() => applyVllmDeploymentMutation.mutate(vllmRequest)}
              >
                <RefreshCw size={16} />
                {applyVllmDeploymentMutation.isPending ? "Applying restart" : "Apply & restart vLLM"}
              </button>
            </div>
            {!vllmFormIsValid ? <InlineMessage tone="error">vLLM launch limits contain an invalid value.</InlineMessage> : null}
            {vllmDeploymentQuery.isError ? <InlineMessage tone="error">{errorMessage(vllmDeploymentQuery.error, "Unable to load vLLM deployment limits.")}</InlineMessage> : null}
          </section>
        ) : null}
        {isAdmin && activeConfigPanel === "workers" ? (
          <section className="sv-card p-5">
            <div className="flex items-center gap-2">
              <Cpu size={18} className="text-primary" />
              <h2 className="text-headline-sm">Ingestion Worker</h2>
            </div>
            <p className="mt-2 text-body-md text-secondary">
              Capacity is per worker replica. One is recommended for this 8 GB Docker environment.
            </p>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <label className="sv-field">
                <span className="sv-label">Worker concurrency</span>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={workerConcurrency}
                  onChange={(event) => {
                    setWorkerConcurrency(Number(event.target.value));
                    setHighConcurrencyConfirmed(false);
                  }}
                  className="sv-input"
                />
                <span className="text-body-md text-secondary">Allowed range: 1-10. Recommended: 1.</span>
              </label>
              {ingestConfigQuery.data ? (
                <dl className="grid grid-cols-2 gap-3">
                  <Fact label="Worker" value={ingestConfigQuery.data.worker_online ? "Online" : "Offline"} />
                  <Fact label="Apply status" value={labelize(ingestConfigQuery.data.apply_status)} />
                  <Fact label="Observed pool" value={String(ingestConfigQuery.data.observed_pool_size)} />
                  <Fact label="Active jobs" value={String(ingestConfigQuery.data.active_jobs)} />
                </dl>
              ) : null}
            </div>
            {workerConcurrency > 2 ? (
              <InlineMessage tone="warning">
                Concurrency above 2 can exhaust memory when Docling parses multiple documents.
              </InlineMessage>
            ) : null}
            {workerConcurrency > 4 ? (
              <label className="mt-3 flex items-start gap-2 text-body-md">
                <input
                  type="checkbox"
                  checked={highConcurrencyConfirmed}
                  onChange={(event) => setHighConcurrencyConfirmed(event.target.checked)}
                />
                I understand that this setting is hazardous for the current 8 GB Docker allocation.
              </label>
            ) : null}
            <div className="mt-4">
              <button
                type="button"
                className="sv-action-primary"
                disabled={
                  workerConcurrency < 1 ||
                  workerConcurrency > 10 ||
                  (workerConcurrency > 4 && !highConcurrencyConfirmed) ||
                  saveIngestConfigMutation.isPending
                }
                onClick={() => saveIngestConfigMutation.mutate({ worker_concurrency: workerConcurrency })}
              >
                <Save size={16} />
                {saveIngestConfigMutation.isPending ? "Applying" : "Save capacity"}
              </button>
            </div>
            {ingestConfigQuery.isError ? <InlineMessage tone="error">{errorMessage(ingestConfigQuery.error, "Unable to load worker config.")}</InlineMessage> : null}
          </section>
        ) : null}
      </div>
    </FahamBasicPage>
  );
}

type Props = {
  currentUser: AuthUser;
  onLogout: () => void;
  onNavigate: (route: RouteId) => void;
};

type ConfigPanel = "runtime" | "vllm" | "workers";

function ConfigPanelTabs({ onChange, value }: { value: ConfigPanel; onChange: (value: ConfigPanel) => void }) {
  const items: Array<{
    id: ConfigPanel;
    label: string;
    description: string;
    icon: React.ReactNode;
  }> = [
    {
      id: "runtime",
      label: "Inference Runtime",
      description: "Active provider, endpoints, models, budgets, and timeouts.",
      icon: <ServerCog size={18} />,
    },
    {
      id: "vllm",
      label: "vLLM Container Resources",
      description: "Launch limits, GPU memory, KV cache, and restart scope.",
      icon: <Boxes size={18} />,
    },
    {
      id: "workers",
      label: "Ingestion Worker Capacity",
      description: "Ingestion worker capacity and observed processing state.",
      icon: <Cpu size={18} />,
    },
  ];

  return (
    <nav aria-label="Configuration sections" className="grid gap-3 md:grid-cols-3">
      {items.map((item) => {
        const active = value === item.id;
        return (
          <button
            key={item.id}
            type="button"
            aria-current={active ? "page" : undefined}
            onClick={() => onChange(item.id)}
            className={`min-h-24 rounded border p-4 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary ${
              active
                ? "border-primary bg-primary/10 text-on-surface"
                : "border-surface-border bg-surface-container-low text-on-surface hover:bg-surface-container-high"
            }`}
          >
            <span className={`flex items-center gap-2 text-label-md font-bold ${active ? "text-primary" : "text-on-surface"}`}>
              {item.icon}
              {item.label}
            </span>
            <span className="mt-2 block text-body-md text-secondary">{item.description}</span>
          </button>
        );
      })}
    </nav>
  );
}

export type RagConfigFormState = {
  provider: "ollama" | "vllm";
  inference_location: InferenceLocation;
  host: string;
  port: string;
  embedding_host: string;
  embedding_port: string;
  reasoning_host: string;
  reasoning_port: string;
  routing_host: string;
  routing_port: string;
  faithfulness_host: string;
  faithfulness_port: string;
  ingestion_host: string;
  ingestion_port: string;
  chat_model: string;
  embed_model: string;
  reasoning_model: string;
  routing_model: string;
  faithfulness_model: string;
  ingestion_model: string;
  vision_model: string;
  reranker_model: string;
  thinking_enabled: boolean;
  json_num_predict: string;
  retrieval_token_budget: string;
  chat_timeout_seconds: string;
  embed_timeout_seconds: string;
};

type EndpointTarget = {
  host: string;
  port: number;
};

type RagModelLookupTarget = {
  provider: "ollama" | "vllm";
  host: string;
  port: number;
  embedding_host: string | null;
  embedding_port: number | null;
  reasoning_host: string | null;
  reasoning_port: number | null;
  routing_host: string | null;
  routing_port: number | null;
  faithfulness_host: string | null;
  faithfulness_port: number | null;
  ingestion_host: string | null;
  ingestion_port: number | null;
};

type InferenceLocation = "local" | "network";

type VllmDeploymentFormState = {
  text: VllmServiceDeploymentFormState;
  embeddings: VllmServiceDeploymentFormState;
  vision: VllmServiceDeploymentFormState;
};

type VllmServiceDeploymentFormState = {
  max_model_len: string;
  gpu_memory_utilization: string;
  max_num_seqs: string;
  max_num_batched_tokens: string;
  kv_cache_memory_bytes: string;
};

const LOCAL_INFERENCE_HOST = "host.docker.internal";
const VLLM_LOCAL_PORTS = { chat: "8100", embedding: "8101" } as const;
const VLLM_NETWORK_PORTS = { chat: "8000", embedding: "8001" } as const;
export const SUPPORTED_RERANKER_MODELS = [
  "jinaai/jina-reranker-v1-turbo-en",
  "jinaai/jina-reranker-v1-tiny-en",
  "BAAI/bge-reranker-base",
  "Xenova/ms-marco-MiniLM-L-12-v2",
  "Xenova/ms-marco-MiniLM-L-6-v2",
] as const;
const DEFAULT_RERANKER_MODEL = SUPPORTED_RERANKER_MODELS[0];
const VLLM_KV_CACHE_PATTERN = /^[1-9][0-9]*(B|K|M|G|T|KB|MB|GB|TB|KiB|MiB|GiB|TiB)?$/;

export function modelOptionsFromDiscovery(result: RagModelDiscoveryResult | undefined) {
  const chat = result?.chat_models ?? [];
  const reasoning = result?.reasoning_models ?? chat;

  return {
    chat,
    embedding: result?.embedding_models ?? [],
    reasoning,
    routing: result?.routing_models ?? reasoning,
    faithfulness: result?.faithfulness_models ?? chat,
    ingestion: result?.ingestion_models ?? chat,
    vision: result?.vision_models ?? chat,
  };
}

export function rerankerOptionsFromCatalog(
  catalog: { models?: Array<{ model?: string | null }> } | undefined,
): string[] {
  const apiModels = catalog?.models?.map((option) => option.model?.trim()).filter((model): model is string => Boolean(model)) ?? [];
  return uniqueStrings([...apiModels, ...SUPPORTED_RERANKER_MODELS]);
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values)];
}

const DEFAULT_RAG_FORM: RagConfigFormState = {
  provider: "ollama",
  inference_location: "local",
  host: "",
  port: "11434",
  embedding_host: "",
  embedding_port: "11434",
  reasoning_host: "",
  reasoning_port: "11434",
  routing_host: "",
  routing_port: "11434",
  faithfulness_host: "",
  faithfulness_port: "11434",
  ingestion_host: "",
  ingestion_port: "11434",
  chat_model: "llama3.1:8b",
  embed_model: "nomic-embed-text:latest",
  reasoning_model: "",
  routing_model: "",
  faithfulness_model: "",
  ingestion_model: "",
  vision_model: "",
  reranker_model: DEFAULT_RERANKER_MODEL,
  thinking_enabled: false,
  json_num_predict: "4096",
  retrieval_token_budget: "12000",
  chat_timeout_seconds: "180",
  embed_timeout_seconds: "45",
};

const DEFAULT_VLLM_DEPLOYMENT_FORM: VllmDeploymentFormState = {
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

export function endpointsFromForm(form: RagConfigFormState): Record<EndpointRole, EndpointTarget> {
  const localHost = form.inference_location === "local" ? LOCAL_INFERENCE_HOST : null;
  const chat = { host: localHost ?? form.host.trim(), port: Number(form.port) };
  const role = (name: Exclude<EndpointRole, "chat">, fallback: EndpointTarget) => ({
    host: (localHost ?? form[`${name}_host`].trim()) || fallback.host,
    port: Number(form[`${name}_port`]) || fallback.port,
  });
  const reasoning = form.provider === "ollama" ? chat : role("reasoning", chat);
  return {
    chat,
    reasoning,
    routing: form.provider === "ollama" ? chat : role("routing", reasoning),
    faithfulness: form.provider === "ollama" ? chat : role("faithfulness", chat),
    ingestion: form.provider === "ollama" ? chat : role("ingestion", chat),
    embedding: form.provider === "ollama" ? chat : role("embedding", chat),
  };
}

function formFromConfig(config: RagConfig): RagConfigFormState {
  const inference_location = config.host.toLowerCase() === LOCAL_INFERENCE_HOST ? "local" : "network";
  const reasoningHost = config.reasoning_host ?? config.host;
  const reasoningPort = config.reasoning_port ?? config.port;
  const routingHost = config.routing_host ?? reasoningHost;
  const routingPort = config.routing_port ?? reasoningPort;
  const roleOverride = (
    host: string | null | undefined,
    port: number | null | undefined,
    fallbackHost: string,
    fallbackPort: number,
  ) => ({
    host: inference_location === "network" && host && host !== fallbackHost ? host : "",
    port: port && (host !== fallbackHost || port !== fallbackPort) ? String(port) : "",
  });
  const reasoningEndpoint = roleOverride(reasoningHost, reasoningPort, config.host, config.port);
  const routingEndpoint = roleOverride(routingHost, routingPort, reasoningHost, reasoningPort);
  const faithfulnessEndpoint = roleOverride(
    config.faithfulness_host ?? config.host,
    config.faithfulness_port ?? config.port,
    config.host,
    config.port,
  );
  const ingestionEndpoint = roleOverride(
    config.ingestion_host ?? config.host,
    config.ingestion_port ?? config.port,
    config.host,
    config.port,
  );
  return {
    provider: config.provider ?? "ollama",
    inference_location,
    host: inference_location === "network" ? config.host : "",
    port: String(config.port || (config.provider === "vllm" ? 8000 : 11434)),
    embedding_host: inference_location === "network" ? config.embedding_host : "",
    embedding_port: String(config.embedding_port || (config.provider === "vllm" ? 8001 : 11434)),
    reasoning_host: reasoningEndpoint.host,
    reasoning_port: reasoningEndpoint.port,
    routing_host: routingEndpoint.host,
    routing_port: routingEndpoint.port,
    faithfulness_host: faithfulnessEndpoint.host,
    faithfulness_port: faithfulnessEndpoint.port,
    ingestion_host: ingestionEndpoint.host,
    ingestion_port: ingestionEndpoint.port,
    chat_model: config.chat_model || DEFAULT_RAG_FORM.chat_model,
    embed_model: config.embed_model || DEFAULT_RAG_FORM.embed_model,
    reasoning_model: config.reasoning_model ?? config.routing_model ?? "",
    routing_model: config.routing_model ?? "",
    faithfulness_model: config.faithfulness_model ?? "",
    ingestion_model: config.ingestion_model ?? "",
    vision_model: config.vision_model ?? "",
    reranker_model: config.reranker_model || DEFAULT_RERANKER_MODEL,
    thinking_enabled: Boolean(config.thinking_enabled),
    json_num_predict: String(config.json_num_predict || DEFAULT_RAG_FORM.json_num_predict),
    retrieval_token_budget: String(config.retrieval_token_budget || DEFAULT_RAG_FORM.retrieval_token_budget),
    chat_timeout_seconds: String(config.chat_timeout_seconds || DEFAULT_RAG_FORM.chat_timeout_seconds),
    embed_timeout_seconds: String(config.embed_timeout_seconds || DEFAULT_RAG_FORM.embed_timeout_seconds),
  };
}

export function requestFromForm(form: RagConfigFormState): RagConfigRequest {
  const endpoints = endpointsFromForm(form);
  const reasoningModel = form.reasoning_model.trim() || null;
  return {
    provider: form.provider,
    host: endpoints.chat.host,
    port: endpoints.chat.port,
    embedding_host: form.provider === "vllm" ? endpoints.embedding.host : null,
    embedding_port: form.provider === "vllm" ? endpoints.embedding.port : null,
    reasoning_host: form.provider === "vllm" ? endpoints.reasoning.host : null,
    reasoning_port: form.provider === "vllm" ? endpoints.reasoning.port : null,
    routing_host: form.provider === "vllm" ? endpoints.routing.host : null,
    routing_port: form.provider === "vllm" ? endpoints.routing.port : null,
    faithfulness_host: form.provider === "vllm" ? endpoints.faithfulness.host : null,
    faithfulness_port: form.provider === "vllm" ? endpoints.faithfulness.port : null,
    ingestion_host: form.provider === "vllm" ? endpoints.ingestion.host : null,
    ingestion_port: form.provider === "vllm" ? endpoints.ingestion.port : null,
    chat_model: form.chat_model.trim(),
    embed_model: form.embed_model.trim(),
    reasoning_model: reasoningModel,
    routing_model: form.routing_model.trim() || reasoningModel,
    faithfulness_model: form.faithfulness_model.trim() || null,
    ingestion_model: form.ingestion_model.trim() || null,
    vision_model: form.provider === "ollama" ? form.vision_model.trim() || null : null,
    thinking_enabled: form.provider === "ollama" && form.thinking_enabled,
    json_num_predict: Number(form.json_num_predict),
    retrieval_token_budget: Number(form.retrieval_token_budget),
    reranker_model: form.reranker_model.trim(),
    chat_timeout_seconds: Number(form.chat_timeout_seconds),
    embed_timeout_seconds: Number(form.embed_timeout_seconds),
  };
}

function canFetchModelsForEndpoint(endpoint: EndpointTarget): boolean {
  return Boolean(
    endpoint.host &&
      Number.isFinite(endpoint.port) &&
      endpoint.port >= 1 &&
      endpoint.port <= 65535,
  );
}

function canSubmitRagConfig(form: RagConfigFormState): boolean {
  const request = requestFromForm(form);
  return Boolean(
    request.host &&
      request.chat_model &&
      request.embed_model &&
      request.reranker_model &&
      Number.isFinite(request.port) &&
      request.port >= 1 &&
      request.port <= 65535 &&
      (form.provider === "ollama" || Object.values(endpointsFromForm(form)).every(canFetchModelsForEndpoint)) &&
      Number.isFinite(request.json_num_predict) &&
      request.json_num_predict >= 256 &&
      request.json_num_predict <= 32768 &&
      Number.isFinite(request.retrieval_token_budget) &&
      request.retrieval_token_budget >= 1000 &&
      request.retrieval_token_budget <= 200000 &&
      Number.isFinite(request.chat_timeout_seconds) &&
      request.chat_timeout_seconds > 0 &&
      Number.isFinite(request.embed_timeout_seconds) &&
      request.embed_timeout_seconds > 0,
  );
}

function vllmFormFromConfig(config: VllmDeploymentConfig): VllmDeploymentFormState {
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

function requestFromVllmForm(form: VllmDeploymentFormState): VllmDeploymentConfigRequest {
  return {
    text: vllmLimitsRequestFromForm(form.text),
    embeddings: vllmLimitsRequestFromForm(form.embeddings),
    vision: vllmLimitsRequestFromForm(form.vision),
  };
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

function canSubmitVllmDeploymentConfig(form: VllmDeploymentFormState): boolean {
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

function InferenceLocationSelector({ onChange, value }: { value: InferenceLocation; onChange: (value: InferenceLocation) => void }) {
  return (
    <fieldset className="md:col-span-2">
      <legend className="sv-label">Inference location</legend>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        <InferenceLocationOption
          checked={value === "local"}
          description="Use inference services running on the same machine as this workspace."
          icon={<Laptop size={18} />}
          label="Local machine"
          onChange={() => onChange("local")}
          value="local"
        />
        <InferenceLocationOption
          checked={value === "network"}
          description="Use inference services on another machine on the private network."
          icon={<Network size={18} />}
          label="Network server"
          onChange={() => onChange("network")}
          value="network"
        />
      </div>
    </fieldset>
  );
}

function InferenceLocationOption({ checked, description, icon, label, onChange, value }: InferenceLocationOptionProps) {
  return (
    <label className="cursor-pointer">
      <input
        type="radio"
        name="inference-location"
        value={value}
        checked={checked}
        onChange={onChange}
        className="peer sr-only"
      />
      <span
        className={`flex h-full items-start gap-3 rounded-lg border p-3 transition-colors peer-focus-visible:outline peer-focus-visible:outline-3 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-primary ${
          checked
            ? "border-primary bg-primary/10 text-on-surface"
            : "border-surface-border bg-surface-container-low text-on-surface hover:bg-surface-container-high"
        }`}
      >
        <span className={`mt-0.5 ${checked ? "text-primary" : "text-secondary"}`}>{icon}</span>
        <span>
          <span className="block text-body-md font-bold">{label}</span>
          <span className="mt-1 block text-body-md text-secondary">{description}</span>
        </span>
      </span>
    </label>
  );
}

type InferenceLocationOptionProps = {
  checked: boolean;
  description: string;
  icon: React.ReactNode;
  label: string;
  onChange: () => void;
  value: InferenceLocation;
};

function ModelSelect({ disabled, emptyLabel, models, onChange, placeholder, value }: ModelSelectProps) {
  const hasValue = value.trim().length > 0;
  const hasFetchedValue = models.includes(value);

  return (
    <select value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} className="sv-select">
      {emptyLabel ? <option value="">{emptyLabel}</option> : !hasValue ? <option value="" disabled>{placeholder}</option> : null}
      {hasValue && !hasFetchedValue ? <option value={value}>{value}</option> : null}
      {models.map((model) => (
        <option key={model} value={model}>
          {model}
        </option>
      ))}
    </select>
  );
}

type ModelSelectProps = {
  value: string;
  models: string[];
  placeholder: string;
  disabled: boolean;
  emptyLabel?: string;
  onChange: (value: string) => void;
};

function CurrentRagStatus({ config }: { config: RagConfig }) {
  return (
    <section className="mt-6 border-t border-surface-border pt-5" aria-labelledby="active-rag-config-title">
      <div>
        <h3 id="active-rag-config-title" className="text-title-md">Active configuration</h3>
        <p className="mt-1 text-body-md text-secondary">This is the saved runtime currently used by queries and ingestion.</p>
      </div>
      <dl className="mt-4 grid gap-3 md:grid-cols-4">
        <Fact label="Location" value={config.host.toLowerCase() === LOCAL_INFERENCE_HOST ? "Local machine" : "Network server"} />
        <Fact label="Provider" value={providerName(config.provider)} />
        <Fact label="Endpoint" value={config.base_url} />
        <Fact label="Embedding endpoint" value={config.embedding_base_url} />
        {config.provider === "vllm" ? <Fact label="Reasoning endpoint" value={config.reasoning_base_url ?? config.base_url} /> : null}
        {config.provider === "vllm" ? <Fact label="Routing endpoint" value={config.routing_base_url ?? config.reasoning_base_url ?? config.base_url} /> : null}
        {config.provider === "vllm" ? <Fact label="Faithfulness endpoint" value={config.faithfulness_base_url ?? config.base_url} /> : null}
        {config.provider === "vllm" ? <Fact label="Ingestion endpoint" value={config.ingestion_base_url ?? config.base_url} /> : null}
        <Fact label="Answer model" value={config.chat_model} />
        <Fact label="Reasoning model" value={config.reasoning_model ?? config.routing_model ?? config.chat_model} />
        <Fact label="Faithfulness model" value={config.faithfulness_model ?? config.chat_model} />
        <Fact label="Ingestion model" value={config.ingestion_model ?? config.chat_model} />
        {config.provider === "ollama" ? <Fact label="Vision OCR model" value={config.vision_model ?? config.ingestion_model ?? config.chat_model} /> : null}
        <Fact label="Reranker model" value={config.reranker_model} />
        <Fact label="Model thinking" value={config.thinking_enabled ? "Enabled" : "Disabled"} />
        <Fact label="JSON/Layout budget" value={String(config.json_num_predict)} />
        <Fact label="Evidence budget" value={String(config.retrieval_token_budget)} />
        <Fact label="Embedding model" value={config.embed_model} />
        <Fact label="Health" value={`${config.health.status}: ${config.health.message}`} />
        <Fact label="Checked" value={formatDateTime(config.health.checked_at)} />
        <Fact label="Chat latency" value={formatLatency(config.health.chat_latency_ms)} />
        <Fact label="Embed latency" value={formatLatency(config.health.embed_latency_ms)} />
      </dl>
    </section>
  );
}

function VllmLimitsEditor({ includeKvCache = false, limits, onChange, title }: VllmLimitsEditorProps) {
  const update = (patch: Partial<VllmServiceDeploymentFormState>) => onChange({ ...limits, ...patch });
  return (
    <section className="rounded border border-surface-border bg-surface-container-low p-4">
      <h3 className="text-title-md">{title}</h3>
      <div className="mt-3 grid gap-3">
        <label className="sv-field">
          <span className="sv-label">Max model length</span>
          <input
            type="number"
            min={256}
            max={262144}
            value={limits.max_model_len}
            onChange={(event) => update({ max_model_len: event.target.value })}
            className="sv-input"
          />
        </label>
        <label className="sv-field">
          <span className="sv-label">GPU memory utilization</span>
          <input
            type="number"
            min={0.01}
            max={1}
            step={0.01}
            value={limits.gpu_memory_utilization}
            onChange={(event) => update({ gpu_memory_utilization: event.target.value })}
            className="sv-input"
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="sv-field">
            <span className="sv-label">Max sequences</span>
            <input
              type="number"
              min={1}
              max={1024}
              value={limits.max_num_seqs}
              onChange={(event) => update({ max_num_seqs: event.target.value })}
              className="sv-input"
            />
          </label>
          <label className="sv-field">
            <span className="sv-label">Batched tokens</span>
            <input
              type="number"
              min={256}
              max={262144}
              value={limits.max_num_batched_tokens}
              onChange={(event) => update({ max_num_batched_tokens: event.target.value })}
              className="sv-input"
            />
          </label>
        </div>
        {includeKvCache ? (
          <label className="sv-field">
            <span className="sv-label">KV cache memory</span>
            <input
              value={limits.kv_cache_memory_bytes}
              onChange={(event) => update({ kv_cache_memory_bytes: event.target.value })}
              placeholder="2G"
              className="sv-input"
            />
          </label>
        ) : null}
      </div>
    </section>
  );
}

type VllmLimitsEditorProps = {
  title: string;
  limits: VllmServiceDeploymentFormState;
  includeKvCache?: boolean;
  onChange: (limits: VllmServiceDeploymentFormState) => void;
};

function ProviderSelector({ onChange, value }: { value: "ollama" | "vllm"; onChange: (value: "ollama" | "vllm") => void }) {
  return (
    <fieldset className="md:col-span-2">
      <legend className="sv-label">Active inference provider</legend>
      <div className="mt-2 inline-flex rounded border border-surface-border bg-surface-container-low p-1">
        {(["ollama", "vllm"] as const).map((provider) => (
          <label key={provider} className="cursor-pointer">
            <input
              type="radio"
              name="inference-provider"
              value={provider}
              checked={value === provider}
              onChange={() => onChange(provider)}
              className="peer sr-only"
            />
            <span className="flex min-h-10 items-center gap-2 rounded px-4 text-label-md text-secondary peer-checked:bg-surface-container-high peer-checked:text-on-surface peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-primary">
              {provider === "ollama" ? <Cpu size={16} /> : <Boxes size={16} />}
              {providerName(provider)} runtime
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function providerDefaults(form: RagConfigFormState): RagConfigFormState {
  if (form.provider === "vllm") {
    const ports = form.inference_location === "local" ? VLLM_LOCAL_PORTS : VLLM_NETWORK_PORTS;
    return {
      ...clearModelSelections(form),
      port: ports.chat,
      reasoning_port: "",
      routing_port: "",
      faithfulness_port: "",
      ingestion_port: "",
      embedding_port: ports.embedding,
      thinking_enabled: false,
    };
  }
  return {
    ...clearModelSelections(form),
    port: "11434",
    reasoning_port: "11434",
    routing_port: "11434",
    faithfulness_port: "11434",
    ingestion_port: "11434",
    embedding_port: "11434",
  };
}

export function inferenceLocationDefaults(
  form: RagConfigFormState,
  inference_location: InferenceLocation,
): RagConfigFormState {
  const next = clearModelSelections({ ...form, inference_location });
  return form.provider === "vllm" ? providerDefaults(next) : next;
}

function clearModelSelections(form: RagConfigFormState): RagConfigFormState {
  return {
    ...form,
    chat_model: "",
    embed_model: "",
    reasoning_model: "",
    routing_model: "",
    faithfulness_model: "",
    ingestion_model: "",
    vision_model: "",
  };
}

function discoveryTarget(request: RagConfigRequest): RagModelLookupTarget {
  return {
    provider: request.provider ?? "ollama",
    host: request.host,
    port: request.port,
    embedding_host: request.embedding_host ?? null,
    embedding_port: request.embedding_port ?? null,
    reasoning_host: request.reasoning_host ?? null,
    reasoning_port: request.reasoning_port ?? null,
    routing_host: request.routing_host ?? null,
    routing_port: request.routing_port ?? null,
    faithfulness_host: request.faithfulness_host ?? null,
    faithfulness_port: request.faithfulness_port ?? null,
    ingestion_host: request.ingestion_host ?? null,
    ingestion_port: request.ingestion_port ?? null,
  };
}

type EndpointRole = "chat" | "reasoning" | "routing" | "faithfulness" | "ingestion" | "embedding";

function RoleEndpointFields({ form, label, onChange, role }: {
  form: RagConfigFormState;
  label: string;
  onChange: (value: RagConfigFormState) => void;
  role: Exclude<EndpointRole, "chat">;
}) {
  const fallbackRole: EndpointRole = role === "routing" ? "reasoning" : "chat";
  const fallbackEndpoint = endpointsFromForm(form)[fallbackRole];
  const fallbackLabel = fallbackRole === "reasoning" ? "reasoning" : "chat";
  return (
    <fieldset className="grid gap-3 rounded border border-surface-border bg-surface-container-low p-3">
      <legend className="sv-label px-1">{label} server</legend>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_8rem]">
        <label className="sv-field">
          <span className="sv-label">Host</span>
          <input
            value={form[`${role}_host`]}
            onChange={(event) => onChange({ ...form, [`${role}_host`]: event.target.value })}
            placeholder={`Same as ${fallbackLabel} host`}
            disabled={form.inference_location === "local"}
            className="sv-input"
          />
        </label>
        <label className="sv-field">
          <span className="sv-label">Port</span>
          <input
            type="number"
            min={1}
            max={65535}
            value={form[`${role}_port`]}
            onChange={(event) => onChange({ ...form, [`${role}_port`]: event.target.value })}
            placeholder={String(fallbackEndpoint.port)}
            className="sv-input"
          />
        </label>
      </div>
      <span className="text-body-md text-secondary">
        Leave blank to use the {fallbackLabel} endpoint.
      </span>
    </fieldset>
  );
}

function providerName(provider: "ollama" | "vllm") {
  return provider === "vllm" ? "vLLM" : "Ollama";
}

function formatLatency(value: number | null) {
  return value === null ? "Not measured" : `${value} ms`;
}

function labelize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function safeWorkerConcurrency(value: number | null | undefined) {
  return Number.isFinite(value) ? Number(value) : 1;
}
