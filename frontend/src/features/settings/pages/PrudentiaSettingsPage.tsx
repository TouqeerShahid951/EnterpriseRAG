import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Boxes, CheckCircle2, ChevronDown, Cpu, RefreshCw, Save, ServerCog, SlidersHorizontal, Wifi } from "lucide-react";

import { adminApi, type IngestConfigRequest, type RagConfigRequest, type VllmDeploymentConfigRequest } from "@/lib/api/contracts";
import { isPlatformAdmin } from "@/lib/auth/authz";
import { useToast } from "@/components/feedback/ToastProvider";
import { Fact, InlineMessage } from "@/components/layout/Common";
import { Modal } from "@/components/layout/Modal";
import { PrudentiaBasicPage } from "@/components/layout/PrudentiaWorkspace";
import type { RouteId } from "@/routes/routes";
import type {
  IngestConfig,
  RagConfig,
  RagConfigTestResult,
  RagModelDiscoveryResult,
  RagModelDiscoveryStatus,
  User as AuthUser,
  VllmDeploymentConfig,
  VllmDeploymentService,
  VllmServiceDeploymentLimits,
} from "@/types/api";
import { errorMessage, formatDateTime } from "@/lib/utils/format";

export function PrudentiaSettingsPage({ currentUser, onLogout, onNavigate }: Props) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const isAdmin = isPlatformAdmin(currentUser);
  const [activeConfigPanel, setActiveConfigPanel] = useState<ConfigPanel>("models");
  const [ragDraft, setRagDraft] = useState<RagConfigFormState>(DEFAULT_RAG_FORM);
  const [ragResetDialogOpen, setRagResetDialogOpen] = useState(false);
  const [ragModelLookup, setRagModelLookup] = useState<RagModelLookupTarget | null>(null);
  const [vllmDraft, setVllmDraft] = useState<VllmDeploymentFormState>(DEFAULT_VLLM_DEPLOYMENT_FORM);
  const [vllmRestartConfirmed, setVllmRestartConfirmed] = useState<VllmRestartConfirmations>(DEFAULT_VLLM_RESTART_CONFIRMATIONS);
  const [activeVllmApplyService, setActiveVllmApplyService] = useState<VllmDeploymentService | null>(null);
  const [workerConcurrency, setWorkerConcurrency] = useState(1);
  const [ocrReviewThresholdPercent, setOcrReviewThresholdPercent] = useState(90);
  const [pdfImageReviewThreshold, setPdfImageReviewThreshold] = useState(64);
  const [visionLayoutRepairEnabled, setVisionLayoutRepairEnabled] = useState(false);
  const [graphEnrichmentEnabled, setGraphEnrichmentEnabled] = useState(false);
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
        embedding_provider: result.embedding_provider,
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
        description: `${providerName(result.provider)} responded. ${embeddingProviderName(result.embedding_provider)} embeddings ${formatLatency(result.health.embed_latency_ms)}.`,
        tone: "success",
      });
    },
    onError: (error) => notify({
      title: "Model routing test failed",
      description: errorMessage(error, "Model routing test failed."),
      tone: "error",
    }),
  });
  const saveRagConfigMutation = useMutation<RagConfig, Error, RagConfigRequest>({
    mutationFn: adminApi.updateRagConfig,
    onSuccess: (config) => {
      setRagDraft(formFromConfig(config));
      queryClient.setQueryData(["admin", "rag-config"], config);
      notify({ title: "Model routing saved", description: "The model routing is now active.", tone: "success" });
    },
    onError: (error) => notify({
      title: "Model routing save failed",
      description: errorMessage(error, "Model routing save failed."),
      tone: "error",
    }),
  });
  const resetRagConfigMutation = useMutation<RagConfig, Error, void>({
    mutationFn: adminApi.resetRagConfig,
    onSuccess: (config) => {
      setRagDraft(formFromConfig(config));
      queryClient.setQueryData(["admin", "rag-config"], config);
      setRagResetDialogOpen(false);
      notify({
        title: "Deployment defaults restored",
        description: "Queries and ingestion now use the environment-backed model routing configuration.",
        tone: "success",
      });
    },
    onError: (error) => notify({
      title: "Deployment defaults could not be restored",
      description: errorMessage(error, "Unable to remove the workspace model routing override."),
      tone: "error",
    }),
  });
  const saveIngestConfigMutation = useMutation<IngestConfig, Error, IngestConfigRequest>({
    mutationFn: adminApi.updateIngestConfig,
    onSuccess: (config) => {
      setWorkerConcurrency(safeWorkerConcurrency(config.worker_concurrency));
      setOcrReviewThresholdPercent(thresholdPercentFromConfig(config.ocr_review_confidence_threshold));
      setPdfImageReviewThreshold(safePdfImageReviewThreshold(config.pdf_image_review_threshold));
      setVisionLayoutRepairEnabled(config.vision_layout_repair_enabled);
      setGraphEnrichmentEnabled(config.graph_enrichment_enabled);
      setHighConcurrencyConfirmed(false);
      queryClient.setQueryData(["admin", "ingest-config"], config);
      notify({
        title: config.apply_status === "applied" ? "Ingestion controls applied" : "Ingestion controls saved",
        description: config.apply_status === "applied"
          ? "The online worker picked up the saved capacity. New jobs will use the selected OCR, vision, and graph settings."
          : "The capacity value will apply when a worker is online. New jobs will use the selected OCR, vision, and graph settings.",
        tone: config.apply_status === "applied" ? "success" : "warning",
      });
    },
    onError: (error) => notify({
      title: "Ingestion controls update failed",
      description: errorMessage(error, "Unable to apply ingestion controls."),
      tone: "error",
    }),
  });
  const saveVllmDeploymentMutation = useMutation<VllmDeploymentConfig, Error, VllmDeploymentConfigRequest>({
    mutationFn: adminApi.updateVllmDeploymentConfig,
    onSuccess: (config) => {
      setVllmDraft(vllmFormFromConfig(config));
      setVllmRestartConfirmed(DEFAULT_VLLM_RESTART_CONFIRMATIONS);
      queryClient.setQueryData(["admin", "vllm-deployment-config"], config);
      notify({
        title: "vLLM service limits saved",
        description: config.message ?? "Restart is required before the containers use the saved limits.",
        tone: "warning",
      });
    },
    onError: (error) => notify({
      title: "vLLM service limit save failed",
      description: errorMessage(error, "Unable to save vLLM service limits."),
      tone: "error",
    }),
  });
  const applyVllmDeploymentMutation = useMutation<VllmDeploymentConfig, Error, VllmDeploymentConfigRequest>({
    mutationFn: adminApi.applyVllmDeploymentConfig,
    onMutate: (request) => {
      setActiveVllmApplyService(request.services?.[0] ?? null);
    },
    onSuccess: (config) => {
      setVllmDraft(vllmFormFromConfig(config));
      setVllmRestartConfirmed(DEFAULT_VLLM_RESTART_CONFIRMATIONS);
      queryClient.setQueryData(["admin", "vllm-deployment-config"], config);
      notify({
        title: "vLLM service restart launched",
        description: config.message ?? "The vLLM containers were recreated with the saved limits.",
        tone: "success",
      });
    },
    onError: (error) => notify({
      title: "vLLM service restart failed",
      description: errorMessage(error, "Unable to apply vLLM service limits."),
      tone: "error",
    }),
    onSettled: () => setActiveVllmApplyService(null),
  });
  useEffect(() => {
    if (ragConfigQuery.data) {
      setRagDraft(formFromConfig(ragConfigQuery.data));
    }
  }, [ragConfigQuery.data]);
  useEffect(() => {
    if (ingestConfigQuery.data) {
      setWorkerConcurrency(safeWorkerConcurrency(ingestConfigQuery.data.worker_concurrency));
      setOcrReviewThresholdPercent(thresholdPercentFromConfig(ingestConfigQuery.data.ocr_review_confidence_threshold));
      setPdfImageReviewThreshold(safePdfImageReviewThreshold(ingestConfigQuery.data.pdf_image_review_threshold));
      setVisionLayoutRepairEnabled(ingestConfigQuery.data.vision_layout_repair_enabled);
      setGraphEnrichmentEnabled(ingestConfigQuery.data.graph_enrichment_enabled);
    }
  }, [ingestConfigQuery.data]);
  useEffect(() => {
    if (vllmDeploymentQuery.data) {
      setVllmDraft(vllmFormFromConfig(vllmDeploymentQuery.data));
      setVllmRestartConfirmed(DEFAULT_VLLM_RESTART_CONFIRMATIONS);
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
    ragDraft.embedding_provider,
    ragDraft.reasoning_provider,
    ragDraft.routing_provider,
    ragDraft.faithfulness_provider,
    ragDraft.ingestion_provider,
    ragDraft.vision_provider,
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
    ragEndpoints.vision.host,
    ragEndpoints.vision.port,
  ]);

  const ragRequest = requestFromForm(ragDraft);
  const ragRequestSignature = JSON.stringify(ragRequest);
  const activeRagRequest = ragConfigQuery.data ? requestFromForm(formFromConfig(ragConfigQuery.data)) : null;
  const ragDraftIsDirty = activeRagRequest !== null && JSON.stringify(activeRagRequest) !== ragRequestSignature;
  const ragModelsMatchDraft =
    ragModelLookup !== null && JSON.stringify(ragModelLookup) === JSON.stringify(discoveryTarget(ragRequest));
  const ragDiscoveryResult = ragModelsMatchDraft ? ragModelsQuery.data : undefined;
  const ragModelOptions = modelOptionsFromDiscovery(ragDiscoveryResult);
  const ragModelStatuses = ragDiscoveryResult?.model_statuses ?? {};
  const rerankerModelOptions = rerankerOptionsFromCatalog(rerankerModelsQuery.data);
  const ragModelsAreLoading = canFetchRagModels && (!ragModelsMatchDraft || ragModelsQuery.isPending || ragModelsQuery.isFetching);
  const ragModelSelectDisabled = !canFetchRagModels || ragModelsAreLoading;
  const vllmRequest = requestFromVllmForm(vllmDraft);
  const activeVllmRequest = vllmDeploymentQuery.data ? requestFromVllmForm(vllmFormFromConfig(vllmDeploymentQuery.data)) : null;
  const vllmDraftIsDirty = activeVllmRequest !== null && JSON.stringify(activeVllmRequest) !== JSON.stringify(vllmRequest);
  const vllmFormIsValid = canSubmitVllmDeploymentConfig(vllmDraft);
  const ingestConfigIsValid = isValidWorkerConcurrency(workerConcurrency) && isValidThresholdPercent(ocrReviewThresholdPercent) && isValidPdfImageReviewThreshold(pdfImageReviewThreshold);

  return (
    <PrudentiaBasicPage
      activeRoute="settings"
      onLogout={onLogout}
      onNavigate={onNavigate}
      title="Runtime Settings"
      subtitle="Configure model routing, inference services, and ingestion behavior for this deployment."
      user={currentUser}
    >
      <div className="grid gap-4">
        {isAdmin ? <ConfigPanelTabs value={activeConfigPanel} onChange={setActiveConfigPanel} /> : null}
        {isAdmin ? (
          <RuntimeStatusStrip
            config={ragConfigQuery.data}
            discoveryLoading={ragModelsAreLoading}
            discoveryResult={ragDiscoveryResult}
            discoveryError={ragModelsQuery.isError && ragModelsMatchDraft ? ragModelsQuery.error : null}
            draftIsDirty={ragDraftIsDirty}
            vllmConfig={vllmDeploymentQuery.data}
            vllmDraftIsDirty={vllmDraftIsDirty}
          />
        ) : null}
        {isAdmin && activeConfigPanel === "models" ? (
          <ModelsAndRolesPanel
            canFetchModels={canFetchRagModels}
            config={ragConfigQuery.data}
            configError={ragConfigQuery.error}
            configFailed={ragConfigQuery.isError}
            discoveryError={ragModelsQuery.error}
            discoveryFailed={ragModelsQuery.isError && ragModelsMatchDraft}
            discoveryLoading={ragModelsAreLoading}
            draft={ragDraft}
            draftIsDirty={ragDraftIsDirty}
            modelOptions={ragModelOptions}
            modelSelectDisabled={ragModelSelectDisabled}
            modelStatuses={ragModelStatuses}
            rerankerError={rerankerModelsQuery.error}
            rerankerFailed={rerankerModelsQuery.isError}
            rerankerModelOptions={rerankerModelOptions}
            rerankerPlaceholder={rerankerModelsQuery.isPending ? "Loading rerankers" : "Choose reranker"}
            rerankerSelectDisabled={rerankerModelsQuery.isPending}
            actionsDisabled={ragConfigActionsLocked({
              dialogOpen: ragResetDialogOpen,
              resetPending: resetRagConfigMutation.isPending,
              savePending: saveRagConfigMutation.isPending,
              testPending: testRagConfigMutation.isPending,
            })}
            savePending={saveRagConfigMutation.isPending}
            testPending={testRagConfigMutation.isPending}
            onChange={setRagDraft}
            onReset={() => {
              resetRagConfigMutation.reset();
              setRagResetDialogOpen(true);
            }}
            onSave={() => saveRagConfigMutation.mutate(ragRequest)}
            onTest={() => testRagConfigMutation.mutate(ragRequest)}
          />
        ) : null}
        {isAdmin && activeConfigPanel === "services" ? (
          <InferenceServicesPanel
            applyPending={applyVllmDeploymentMutation.isPending}
            applyingService={activeVllmApplyService}
            canFetchModels={canFetchRagModels}
            config={vllmDeploymentQuery.data}
            discoveryLoading={ragModelsAreLoading}
            discoveryResult={ragDiscoveryResult}
            draft={vllmDraft}
            draftIsDirty={vllmDraftIsDirty}
            formIsValid={vllmFormIsValid}
            loadError={vllmDeploymentQuery.error}
            loadFailed={vllmDeploymentQuery.isError}
            restartConfirmed={vllmRestartConfirmed}
            savePending={saveVllmDeploymentMutation.isPending}
            onApply={(service) => applyVllmDeploymentMutation.mutate(requestFromVllmForm(vllmDraft, [service]))}
            onDraftChange={setVllmDraft}
            onRestartConfirmedChange={setVllmRestartConfirmed}
            onSave={() => saveVllmDeploymentMutation.mutate(vllmRequest)}
          />
        ) : null}
        {isAdmin && activeConfigPanel === "workers" ? (
          <section className="sv-card p-4">
            <div className="flex items-center gap-2">
              <Cpu size={18} className="text-primary" />
              <h2 className="text-headline-sm">Ingestion Controls</h2>
            </div>
            <p className="mt-2 text-body-md text-secondary">
              Capacity is per worker replica. One is recommended for this 8 GB Docker environment.
            </p>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
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
              <label className="sv-field">
                <span className="sv-label">OCR review threshold</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  value={ocrReviewThresholdPercent}
                  onChange={(event) => setOcrReviewThresholdPercent(Number(event.target.value))}
                  className="sv-input"
                />
                <span className="text-body-md text-secondary">
                  OCR blocks below this confidence percentage pause for review. Current target: below {ocrReviewThresholdPercent || 0}%.
                </span>
              </label>
              <label className="sv-field">
                <span className="sv-label">PDF image review threshold</span>
                <input
                  type="number"
                  min={0}
                  max={10000}
                  step={1}
                  value={pdfImageReviewThreshold}
                  onChange={(event) => setPdfImageReviewThreshold(Number(event.target.value))}
                  className="sv-input"
                />
                <span className="text-body-md text-secondary">
                  Pause for review when selected PDF image candidates exceed this count. Set 0 to skip this review gate.
                </span>
              </label>
              <label className="flex items-start gap-3 rounded border border-subtle bg-surface-muted/40 p-3 text-body-md">
                <input
                  type="checkbox"
                  checked={visionLayoutRepairEnabled}
                  onChange={(event) => setVisionLayoutRepairEnabled(event.target.checked)}
                  className="mt-1"
                />
                <span>
                  <span className="block text-label-md">Vision layout repair</span>
                  <span className="block text-secondary">
                    Use the vision model to re-read complex PDF pages after Docling. Keep off for faster bulk ingestion.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-3 rounded border border-subtle bg-surface-muted/40 p-3 text-body-md">
                <input
                  type="checkbox"
                  checked={graphEnrichmentEnabled}
                  onChange={(event) => setGraphEnrichmentEnabled(event.target.checked)}
                  className="mt-1"
                />
                <span>
                  <span className="block text-label-md">Graph enrichment</span>
                  <span className="block text-secondary">
                    Show the Enrich graph action for completed documents. Keep off for faster bulk ingestion.
                  </span>
                </span>
              </label>
              {ingestConfigQuery.data ? (
                <dl className="grid grid-cols-2 gap-3">
                  <Fact label="Worker" value={ingestConfigQuery.data.worker_online ? "Online" : "Offline"} />
                  <Fact label="Apply status" value={labelize(ingestConfigQuery.data.apply_status)} />
                  <Fact label="Observed pool" value={String(ingestConfigQuery.data.observed_pool_size)} />
                  <Fact label="Active jobs" value={String(ingestConfigQuery.data.active_jobs)} />
                  <Fact label="OCR review" value={`Below ${thresholdPercentFromConfig(ingestConfigQuery.data.ocr_review_confidence_threshold)}%`} />
                  <Fact label="PDF image review" value={pdfImageReviewThresholdLabel(ingestConfigQuery.data.pdf_image_review_threshold)} />
                  <Fact label="Vision repair" value={ingestConfigQuery.data.vision_layout_repair_enabled ? "On" : "Off"} />
                  <Fact label="Graph enrichment" value={ingestConfigQuery.data.graph_enrichment_enabled ? "On" : "Off"} />
                </dl>
              ) : null}
            </div>
            {!ingestConfigIsValid ? (
              <InlineMessage tone="error">
                Worker concurrency must be 1-10, OCR review threshold must be 0-100%, and PDF image review threshold must be 0-10000.
              </InlineMessage>
            ) : null}
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
                  !ingestConfigIsValid ||
                  (workerConcurrency > 4 && !highConcurrencyConfirmed) ||
                  saveIngestConfigMutation.isPending
                }
                onClick={() => saveIngestConfigMutation.mutate({
                  worker_concurrency: workerConcurrency,
                  quality_preset: ingestConfigQuery.data?.quality_preset ?? "fast",
                  ocr_review_confidence_threshold: thresholdFromPercent(ocrReviewThresholdPercent),
                  pdf_image_review_threshold: pdfImageReviewThreshold,
                  vision_layout_repair_enabled: visionLayoutRepairEnabled,
                  graph_enrichment_enabled: graphEnrichmentEnabled,
                })}
              >
                <Save size={16} />
                {saveIngestConfigMutation.isPending ? "Applying" : "Save ingestion controls"}
              </button>
            </div>
            {ingestConfigQuery.isError ? <InlineMessage tone="error">{errorMessage(ingestConfigQuery.error, "Unable to load ingestion controls.")}</InlineMessage> : null}
          </section>
        ) : null}
      </div>
      <Modal
        description="Remove the saved workspace model routing override and immediately return queries and ingestion to the deployment's environment-backed configuration."
        icon={<AlertTriangle size={18} />}
        onClose={() => {
          if (!resetRagConfigMutation.isPending) {
            setRagResetDialogOpen(false);
            resetRagConfigMutation.reset();
          }
        }}
        open={ragResetDialogOpen}
        size="sm"
        title="Restore deployment defaults"
      >
        <div className="space-y-4">
          <InlineMessage tone="warning">
            This discards the workspace override{ragDraftIsDirty ? " and your unsaved draft" : ""}. The deployment configuration will become active as soon as the reset completes.
          </InlineMessage>
          {resetRagConfigMutation.isError ? (
            <InlineMessage tone="error">
              {errorMessage(resetRagConfigMutation.error, "Unable to remove the workspace model routing override.")}
            </InlineMessage>
          ) : null}
          <div className="flex flex-wrap justify-end gap-2 border-t border-surface-border pt-4">
            <button
              type="button"
              className="sv-action-secondary"
              disabled={resetRagConfigMutation.isPending}
              onClick={() => {
                setRagResetDialogOpen(false);
                resetRagConfigMutation.reset();
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              className="sv-action-danger disabled:cursor-not-allowed disabled:opacity-60"
              disabled={resetRagConfigMutation.isPending}
              onClick={() => resetRagConfigMutation.mutate()}
            >
              <RefreshCw size={16} />
              {resetRagConfigMutation.isPending ? "Restoring" : "Restore defaults"}
            </button>
          </div>
        </div>
      </Modal>
    </PrudentiaBasicPage>
  );
}

type Props = {
  currentUser: AuthUser;
  onLogout: () => void;
  onNavigate: (route: RouteId) => void;
};

type ConfigPanel = "models" | "services" | "workers";

function ConfigPanelTabs({ onChange, value }: { value: ConfigPanel; onChange: (value: ConfigPanel) => void }) {
  const items: Array<{
    id: ConfigPanel;
    label: string;
    description: string;
    icon: React.ReactNode;
  }> = [
    {
      id: "models",
      label: "Model Routing",
      description: "Choose the stack, assign role models, test the draft, and activate it.",
      icon: <ServerCog size={18} />,
    },
    {
      id: "services",
      label: "vLLM Services",
      description: "Check provider availability, tune vLLM limits, and restart one service at a time.",
      icon: <Boxes size={18} />,
    },
    {
      id: "workers",
      label: "Ingestion Controls",
      description: "Tune ingestion capacity, OCR review gates, and enrichment behavior.",
      icon: <Cpu size={18} />,
    },
  ];

  return (
    <nav aria-label="Runtime Settings sections" className="grid gap-2 lg:grid-cols-3">
      {items.map((item) => {
        const active = value === item.id;
        return (
          <button
            key={item.id}
            type="button"
            aria-current={active ? "page" : undefined}
            onClick={() => onChange(item.id)}
            className={`min-h-20 rounded border p-3 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary ${
              active
                ? "border-primary bg-primary/10 text-on-surface"
                : "border-surface-border bg-surface-container-low text-on-surface hover:bg-surface-container-high"
            }`}
          >
            <span className={`flex items-center gap-2 text-label-md font-bold ${active ? "text-primary" : "text-on-surface"}`}>
              {item.icon}
              {item.label}
            </span>
            <span className="mt-1 block text-body-md text-secondary">{item.description}</span>
          </button>
        );
      })}
    </nav>
  );
}

function RuntimeStatusStrip({
  config,
  discoveryError,
  discoveryLoading,
  discoveryResult,
  draftIsDirty,
  vllmConfig,
  vllmDraftIsDirty,
}: RuntimeStatusStripProps) {
  const discoveryState = discoveryHealthLabel(discoveryResult, discoveryLoading, discoveryError);
  return (
    <section className="rounded border border-surface-border bg-surface-container-low p-3" aria-label="Runtime Settings status">
      <dl className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        <Fact label="Active stack" value={config ? activeStackLabel(config) : "Loading"} />
        <Fact label="Configuration source" value={config ? ragConfigSourceLabel(config.source) : "Loading"} />
        <Fact label="Draft state" value={draftIsDirty ? "Unsaved changes" : "Matches active routing"} />
        <Fact label="Model discovery" value={discoveryState} />
        <Fact
          label="Restart requirement"
          value={vllmDraftIsDirty ? "vLLM limits unsaved" : vllmConfig?.apply_status ? labelize(vllmConfig.apply_status) : "Loading"}
        />
      </dl>
    </section>
  );
}

type RuntimeStatusStripProps = {
  config?: RagConfig;
  discoveryError: Error | null;
  discoveryLoading: boolean;
  discoveryResult?: RagModelDiscoveryResult;
  draftIsDirty: boolean;
  vllmConfig?: VllmDeploymentConfig;
  vllmDraftIsDirty: boolean;
};

function ModelsAndRolesPanel({
  actionsDisabled,
  canFetchModels,
  config,
  configError,
  configFailed,
  discoveryError,
  discoveryFailed,
  discoveryLoading,
  draft,
  draftIsDirty,
  modelOptions,
  modelSelectDisabled,
  modelStatuses,
  rerankerError,
  rerankerFailed,
  rerankerModelOptions,
  rerankerPlaceholder,
  rerankerSelectDisabled,
  savePending,
  testPending,
  onChange,
  onReset,
  onSave,
  onTest,
}: ModelsAndRolesPanelProps) {
  const canSubmit = canSubmitRagConfig(draft);
  const stackSummary = stackTemplateLabel(stackTemplateFromForm(draft));
  const servicesSummary = discoveryHealthLabel({ model_statuses: modelStatuses } as RagModelDiscoveryResult, discoveryLoading, discoveryFailed ? discoveryError : null);
  const rolesSummary = roleAssignmentSummary(draft);
  const behaviorSummary = behaviorSummaryFromForm(draft);
  const activationSummary = canSubmit ? (draftIsDirty ? "Ready to test or save" : "Active model routing is current") : "Needs models or endpoints";
  return (
    <section className="sv-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <ServerCog size={18} className="text-primary" />
          <div>
            <h2 className="text-headline-sm">Model Routing</h2>
            <p className="mt-1 text-body-md text-secondary">
              Build draft model routing, check the services it depends on, then activate it after validation.
            </p>
          </div>
        </div>
        <StatusBadge tone={draftIsDirty ? "warning" : "neutral"}>{draftIsDirty ? "Unsaved draft" : "Draft matches active"}</StatusBadge>
      </div>

      <div className="mt-4 grid gap-3">
        <GuidedStep
          defaultOpen
          number={1}
          title="Choose stack"
          controls="Select a starting stack. Fine tune provider, host, port, and model per role below."
          impact="Changing the stack resets affected model picks and fills practical local defaults for role endpoints."
          summary={stackSummary}
        >
          <StackTemplateSelector form={draft} onChange={onChange} />
        </GuidedStep>

        <GuidedStep
          number={2}
          title="Check services"
          controls="Reads model catalogs from the selected providers before you assign models."
          impact="A failed service only blocks roles that use that service. Healthy services can still be selected."
          summary={servicesSummary}
        >
          <ServiceDiscoveryStatus
            canFetchModels={canFetchModels}
            discoveryError={discoveryFailed ? discoveryError : null}
            loading={discoveryLoading}
            statuses={modelStatuses}
          />
        </GuidedStep>

        <GuidedStep
          number={3}
          title="Assign roles"
          controls="Choose the provider, endpoint, and model for each RAG role."
          impact="Queries and ingestion use these assignments after Save & activate. Embedding changes require reindexing documents."
          summary={rolesSummary}
        >
          <InferenceRoleMatrix
            canFetchModels={canFetchModels}
            form={draft}
            modelOptions={modelOptions}
            modelsLoading={discoveryLoading}
            modelSelectDisabled={modelSelectDisabled}
            modelStatuses={modelStatuses}
            rerankerModelOptions={rerankerModelOptions}
            rerankerPlaceholder={rerankerPlaceholder}
            rerankerSelectDisabled={rerankerSelectDisabled}
            onChange={onChange}
          />
        </GuidedStep>

        <GuidedStep
          number={4}
          title="Tune behavior"
          controls="Set shared budgets, timeouts, and runtime switches."
          impact="These values affect all saved roles that participate in query planning, evidence retrieval, and generation."
          summary={behaviorSummary}
        >
          <RuntimeAdvancedSettings form={draft} onChange={onChange} />
        </GuidedStep>

        <GuidedStep
          number={5}
          title="Test and activate"
          controls="Test validates the draft. Save validates again and makes it active."
          impact="No container restarts happen here. vLLM restarts live in vLLM Services."
          summary={activationSummary}
        >
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              disabled={!canSubmit || actionsDisabled}
              onClick={onTest}
              className="sv-action-secondary"
            >
              <Wifi size={16} />
              {testPending ? "Testing draft" : "Test draft"}
            </button>
            <button
              type="button"
              disabled={!canSubmit || actionsDisabled}
              onClick={onSave}
              className="sv-action-primary"
            >
              <Save size={16} />
              {savePending ? "Saving" : "Save & activate"}
            </button>
          </div>
          {!canSubmit ? (
            <InlineMessage tone="warning">Choose models and reachable endpoints before testing or saving this draft.</InlineMessage>
          ) : null}
        </GuidedStep>
      </div>

      {configFailed ? <InlineMessage tone="error">{errorMessage(configError, "Unable to load model routing.")}</InlineMessage> : null}
      {discoveryFailed ? <InlineMessage tone="error">{errorMessage(discoveryError, "Unable to fetch inference models.")}</InlineMessage> : null}
      {rerankerFailed ? <InlineMessage tone="error">{errorMessage(rerankerError, "Unable to load reranker models.")}</InlineMessage> : null}
      {config ? <CurrentRagStatus actionsDisabled={actionsDisabled} config={config} onReset={onReset} /> : null}
    </section>
  );
}

type ModelsAndRolesPanelProps = {
  actionsDisabled: boolean;
  canFetchModels: boolean;
  config?: RagConfig;
  configError: Error | null;
  configFailed: boolean;
  discoveryError: Error | null;
  discoveryFailed: boolean;
  discoveryLoading: boolean;
  draft: RagConfigFormState;
  draftIsDirty: boolean;
  modelOptions: ReturnType<typeof modelOptionsFromDiscovery>;
  modelSelectDisabled: boolean;
  modelStatuses: Record<string, RagModelDiscoveryStatus>;
  rerankerError: Error | null;
  rerankerFailed: boolean;
  rerankerModelOptions: string[];
  rerankerPlaceholder: string;
  rerankerSelectDisabled: boolean;
  savePending: boolean;
  testPending: boolean;
  onChange: (value: RagConfigFormState) => void;
  onReset: () => void;
  onSave: () => void;
  onTest: () => void;
};

function GuidedStep({ children, controls, defaultOpen = false, impact, number, summary, title }: GuidedStepProps) {
  const titleId = `config-step-${number}`;
  const contentId = `${titleId}-content`;
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="overflow-hidden rounded border border-surface-border" aria-labelledby={titleId}>
      <button
        type="button"
        aria-label={`${number}. ${title}. ${summary}`}
        aria-controls={contentId}
        aria-expanded={open}
        className={`flex w-full items-start gap-3 bg-surface-container-low px-3 py-2 text-left transition-colors hover:bg-surface-container-high focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary ${
          open ? "border-b border-surface-border" : ""
        }`}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-primary/50 bg-primary/10 text-label-sm font-bold text-primary">
          {number}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span id={titleId} className="text-title-md">{title}</span>
            <span className="rounded border border-surface-border px-2 py-0.5 text-label-sm text-secondary">{summary}</span>
          </span>
          {open ? (
            <span className="mt-1 grid gap-0.5 text-body-md text-secondary">
              <span>Controls: {controls}</span>
              <span>Impact: {impact}</span>
            </span>
          ) : null}
        </span>
        <ChevronDown
          size={16}
          className={`mt-1 shrink-0 text-secondary transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>
      {open ? <div id={contentId} className="p-3">{children}</div> : null}
    </section>
  );
}

type GuidedStepProps = {
  children: React.ReactNode;
  controls: string;
  defaultOpen?: boolean;
  impact: string;
  number: number;
  summary: string;
  title: string;
};

function StackTemplateSelector({ form, onChange }: { form: RagConfigFormState; onChange: (value: RagConfigFormState) => void }) {
  const activeTemplate = stackTemplateFromForm(form);
  const templates: Array<{
    id: StackTemplate;
    label: string;
    description: string;
    icon: React.ReactNode;
  }> = [
    {
      id: "ollama",
      label: "Ollama local",
      description: "Language and vision roles use Ollama. Embeddings can stay local with FastEmbed.",
      icon: <Cpu size={16} />,
    },
    {
      id: "vllm",
      label: "vLLM text stack",
      description: "Language roles use vLLM, embeddings use FastEmbed, vision uses Ollama.",
      icon: <Boxes size={16} />,
    },
    {
      id: "custom",
      label: "Custom",
      description: "Use mixed providers or role-specific endpoints.",
      icon: <SlidersHorizontal size={16} />,
    },
  ];
  return (
    <fieldset>
      <legend className="sv-label">Stack template</legend>
      <div className="mt-2 grid gap-2 md:grid-cols-3">
        {templates.map((template) => {
          const active = activeTemplate === template.id;
          const disabled = template.id === "custom";
          return (
            <button
              key={template.id}
              type="button"
              disabled={disabled}
              onClick={() => {
                if (template.id !== "custom") {
                  onChange(providerDefaults({ ...form, provider: template.id }));
                }
              }}
              className={`min-h-20 rounded border p-2.5 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default ${
                active
                  ? "border-primary bg-primary/10 text-on-surface"
                  : "border-surface-border bg-surface-container-low text-on-surface hover:bg-surface-container-high disabled:hover:bg-surface-container-low"
              }`}
            >
              <span className={`flex items-center gap-2 text-label-md font-bold ${active ? "text-primary" : "text-on-surface"}`}>
                {template.icon}
                {template.label}
              </span>
              <span className="mt-1 block text-body-md text-secondary">{template.description}</span>
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

type StackTemplate = "ollama" | "vllm" | "custom";

function ServiceDiscoveryStatus({ canFetchModels, discoveryError, loading, statuses }: ServiceDiscoveryStatusProps) {
  const entries = MODEL_STATUS_ROLES.map((role) => ({
    role,
    status: statuses[role.key],
  }));
  if (!canFetchModels) {
    return <InlineMessage tone="warning">Enter a host and valid port for every selected provider to check services.</InlineMessage>;
  }
  if (loading) {
    return <p aria-live="polite" className="text-body-md text-secondary">Checking selected model services...</p>;
  }
  if (discoveryError) {
    return <InlineMessage tone="error">{errorMessage(discoveryError, "Unable to check model services.")}</InlineMessage>;
  }
  return (
    <div className="grid gap-2 lg:grid-cols-2">
      {entries.map(({ role, status }) => (
        <DiscoveryStatusCard key={role.key} label={role.label} status={status} />
      ))}
    </div>
  );
}

type ServiceDiscoveryStatusProps = {
  canFetchModels: boolean;
  discoveryError: Error | null;
  loading: boolean;
  statuses: Record<string, RagModelDiscoveryStatus>;
};

function DiscoveryStatusCard({ label, status }: { label: string; status?: RagModelDiscoveryStatus }) {
  const tone = statusTone(status);
  return (
    <div className="rounded border border-surface-border bg-surface-container-low p-2.5">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-label-md font-bold text-on-surface">{label}</div>
          <div className="mt-1 break-all text-body-md text-secondary">{status?.message ?? "Waiting for service check."}</div>
        </div>
        <DiscoveryIcon tone={tone} />
      </div>
      {status?.base_url ? <div className="mt-1 break-all text-label-sm text-secondary">{status.base_url}</div> : null}
    </div>
  );
}

function DiscoveryIcon({ tone }: { tone: "ok" | "warning" | "error" | "neutral" }) {
  if (tone === "ok") return <CheckCircle2 size={18} className="text-success" />;
  if (tone === "error") return <AlertTriangle size={18} className="text-warning-amber" />;
  if (tone === "warning") return <AlertTriangle size={18} className="text-warning-amber" />;
  return <Wifi size={18} className="text-secondary" />;
}

function InferenceServicesPanel({
  applyPending,
  applyingService,
  canFetchModels,
  config,
  discoveryLoading,
  discoveryResult,
  draft,
  draftIsDirty,
  formIsValid,
  loadError,
  loadFailed,
  restartConfirmed,
  savePending,
  onApply,
  onDraftChange,
  onRestartConfirmedChange,
  onSave,
}: InferenceServicesPanelProps) {
  return (
    <div className="grid gap-4">
      <section className="sv-card p-4">
        <div className="flex items-center gap-2">
          <Boxes size={18} className="text-primary" />
          <div>
            <h2 className="text-headline-sm">vLLM Services</h2>
            <p className="mt-1 text-body-md text-secondary">
              Inspect service availability, tune bundled vLLM limits, and restart one vLLM container at a time.
            </p>
          </div>
        </div>
        <div className="mt-3">
          <ServiceDiscoveryStatus
            canFetchModels={canFetchModels}
            discoveryError={null}
            loading={discoveryLoading}
            statuses={discoveryResult?.model_statuses ?? {}}
          />
        </div>
      </section>
      <VllmLaunchLimitsSection
        config={config}
        draft={draft}
        draftIsDirty={draftIsDirty}
        formIsValid={formIsValid}
        loadError={loadError}
        loadFailed={loadFailed}
        savePending={savePending}
        onDraftChange={onDraftChange}
        onRestartConfirmedChange={onRestartConfirmedChange}
        onSave={onSave}
      />
      <VllmRestartControlsSection
        applyPending={applyPending}
        applyingService={applyingService}
        config={config}
        deploymentBusy={applyPending}
        formIsValid={formIsValid}
        restartConfirmed={restartConfirmed}
        onApply={onApply}
        onRestartConfirmedChange={onRestartConfirmedChange}
      />
    </div>
  );
}

type InferenceServicesPanelProps = VllmDeploymentSectionProps & {
  canFetchModels: boolean;
  discoveryLoading: boolean;
  discoveryResult?: RagModelDiscoveryResult;
};

function VllmLaunchLimitsSection({
  config,
  draft,
  draftIsDirty,
  formIsValid,
  loadError,
  loadFailed,
  savePending,
  onDraftChange,
  onRestartConfirmedChange,
  onSave,
}: Pick<
  VllmDeploymentSectionProps,
  "config" | "draft" | "draftIsDirty" | "formIsValid" | "loadError" | "loadFailed" | "savePending" | "onDraftChange" | "onRestartConfirmedChange" | "onSave"
>) {
  const updateServiceDraft = (service: VllmDeploymentService, limits: VllmServiceDeploymentFormState) => {
    onDraftChange({ ...draft, [service]: limits });
    onRestartConfirmedChange(DEFAULT_VLLM_RESTART_CONFIRMATIONS);
  };
  return (
    <section className="sv-card p-4" aria-labelledby="vllm-launch-limits-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <SlidersHorizontal size={18} className="text-primary" />
          <div>
            <h2 id="vllm-launch-limits-title" className="text-headline-sm">vLLM Launch Limits</h2>
            <p className="mt-1 text-body-md text-secondary">
              Controls: edit context, GPU memory, sequence, batch, and KV cache limits for each bundled vLLM service.
            </p>
            <p className="mt-1 text-body-md text-secondary">
              Impact: saving stores limits only. Restart the affected service below when you want the container to use them.
            </p>
          </div>
        </div>
        {draftIsDirty ? <StatusBadge tone="warning">Unsaved limit draft</StatusBadge> : null}
      </div>
      {config ? (
        <div className="mt-3 grid gap-3 lg:grid-cols-3">
          {VLLM_DEPLOYMENT_SERVICES.map((service) => (
            <VllmLimitFields
              key={service.key}
              description={service.description}
              includeKvCache={service.includeKvCache}
              limits={draft[service.key]}
              title={service.title}
              onChange={(limits) => updateServiceDraft(service.key, limits)}
            />
          ))}
        </div>
      ) : (
        <p aria-live="polite" className="mt-3 text-body-md text-secondary">Loading vLLM deployment limits...</p>
      )}
      {config ? (
        <dl className="mt-4 grid gap-3 sm:grid-cols-3">
          <Fact label="Source" value={labelize(config.source)} />
          <Fact label="Apply status" value={labelize(config.apply_status)} />
          <Fact label="Save effect" value="Restart required" />
        </dl>
      ) : null}
      {config?.message ? (
        <InlineMessage tone={config.apply_status === "failed" ? "error" : "warning"}>{config.message}</InlineMessage>
      ) : null}
      <div className="mt-4 flex flex-wrap gap-3">
        <button
          type="button"
          className="sv-action-secondary"
          disabled={!formIsValid || savePending}
          onClick={onSave}
        >
          <Save size={16} />
          {savePending ? "Saving" : "Save launch limits"}
        </button>
      </div>
      {!formIsValid ? <InlineMessage tone="error">vLLM launch limits contain an invalid value.</InlineMessage> : null}
      {loadFailed ? (
        <InlineMessage tone="error">{errorMessage(loadError, "Unable to load vLLM deployment limits.")}</InlineMessage>
      ) : null}
    </section>
  );
}

function VllmLimitFields({ description, includeKvCache, limits, onChange, title }: VllmLimitFieldsProps) {
  return (
    <section className="rounded border border-surface-border bg-surface-container-low p-3" aria-label={`${title} launch limits`}>
      <h3 className="text-title-md">{title}</h3>
      <p className="mt-1 text-body-md text-secondary">{description}</p>
      <div className="mt-3 grid gap-3">
        <VllmNumberField
          label="Max model length"
          value={limits.max_model_len}
          description="Context length exposed by this service."
          onChange={(max_model_len) => onChange({ ...limits, max_model_len })}
        />
        <VllmNumberField
          label="GPU memory utilization"
          value={limits.gpu_memory_utilization}
          description="Fraction of GPU memory vLLM may reserve."
          onChange={(gpu_memory_utilization) => onChange({ ...limits, gpu_memory_utilization })}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <VllmNumberField
            label="Max sequences"
            value={limits.max_num_seqs}
            description="Concurrent sequences accepted by this service."
            onChange={(max_num_seqs) => onChange({ ...limits, max_num_seqs })}
          />
          <VllmNumberField
            label="Batched tokens"
            value={limits.max_num_batched_tokens}
            description="Token budget available to each scheduler batch."
            onChange={(max_num_batched_tokens) => onChange({ ...limits, max_num_batched_tokens })}
          />
        </div>
        {includeKvCache ? (
          <label className="sv-field">
            <span className="sv-label">KV cache memory</span>
            <input
              value={limits.kv_cache_memory_bytes}
              onChange={(event) => onChange({ ...limits, kv_cache_memory_bytes: event.target.value })}
              placeholder="2G"
              className="sv-input"
            />
            <span className="text-body-md text-secondary">Optional explicit KV cache size.</span>
          </label>
        ) : null}
      </div>
    </section>
  );
}

function VllmNumberField({ description, label, onChange, value }: VllmNumberFieldProps) {
  return (
    <label className="sv-field">
      <span className="sv-label">{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} className="sv-input" />
      <span className="text-body-md text-secondary">{description}</span>
    </label>
  );
}

type VllmNumberFieldProps = {
  description: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
};

type VllmLimitFieldsProps = {
  description: string;
  includeKvCache?: boolean;
  limits: VllmServiceDeploymentFormState;
  title: string;
  onChange: (limits: VllmServiceDeploymentFormState) => void;
};

function VllmRestartControlsSection({
  applyPending,
  applyingService,
  config,
  deploymentBusy,
  formIsValid,
  restartConfirmed,
  onApply,
  onRestartConfirmedChange,
}: Pick<
  VllmDeploymentSectionProps,
  "applyPending" | "applyingService" | "config" | "formIsValid" | "restartConfirmed" | "onApply" | "onRestartConfirmedChange"
> & { deploymentBusy: boolean }) {
  const updateRestartConfirmed = (service: VllmDeploymentService, confirmed: boolean) => {
    onRestartConfirmedChange({ ...restartConfirmed, [service]: confirmed });
  };
  return (
    <section className="sv-card p-4" aria-labelledby="vllm-restart-title">
      <div className="flex items-center gap-2">
        <RefreshCw size={18} className="text-primary" />
        <div>
          <h2 id="vllm-restart-title" className="text-headline-sm">vLLM Restarts</h2>
          <p className="mt-1 text-body-md text-secondary">
            Controls: restart one bundled vLLM service after launch limits or model IDs change.
          </p>
          <p className="mt-1 text-body-md text-secondary">
            Impact: active requests using that service can stop while its container is recreated.
          </p>
        </div>
      </div>
      {config ? (
        <div className="mt-3 grid gap-3 lg:grid-cols-3">
          {VLLM_DEPLOYMENT_SERVICES.map((service) => (
            <VllmRestartCard
              key={service.key}
              applyPending={applyPending && applyingService === service.key}
              canApply={formIsValid}
              deploymentBusy={deploymentBusy}
              description={service.description}
              restartConfirmed={restartConfirmed[service.key]}
              serviceName={service.composeService}
              title={service.title}
              onApply={() => onApply(service.key)}
              onRestartConfirmedChange={(confirmed) => updateRestartConfirmed(service.key, confirmed)}
            />
          ))}
        </div>
      ) : (
        <p aria-live="polite" className="mt-3 text-body-md text-secondary">Loading vLLM restart controls...</p>
      )}
    </section>
  );
}

function VllmRestartCard({
  applyPending,
  canApply,
  deploymentBusy,
  description,
  restartConfirmed,
  serviceName,
  title,
  onApply,
  onRestartConfirmedChange,
}: VllmRestartCardProps) {
  return (
    <section className="rounded border border-surface-border bg-surface-container-low p-3" aria-label={`${serviceName} restart`}>
      <h3 className="text-title-md">{title}</h3>
      <p className="mt-1 text-body-md text-secondary">{description}</p>
      <label className="mt-3 flex items-start gap-2 text-body-md">
        <input
          type="checkbox"
          checked={restartConfirmed}
          disabled={!canApply || deploymentBusy}
          onChange={(event) => onRestartConfirmedChange(event.target.checked)}
        />
        <span>
          Restart only <span className="font-semibold text-primary">{serviceName}</span>. Active requests using this service
          may stop while the container is recreated.
        </span>
      </label>
      <button
        type="button"
        className="sv-action-secondary mt-3 w-full justify-center"
        disabled={!canApply || !restartConfirmed || deploymentBusy}
        onClick={onApply}
      >
        <RefreshCw size={16} />
        {applyPending ? "Restarting" : `Restart ${serviceName}`}
      </button>
    </section>
  );
}

type VllmRestartCardProps = {
  applyPending: boolean;
  canApply: boolean;
  deploymentBusy: boolean;
  description: string;
  restartConfirmed: boolean;
  serviceName: string;
  title: string;
  onApply: () => void;
  onRestartConfirmedChange: (confirmed: boolean) => void;
};

function StatusBadge({ children, tone }: { children: React.ReactNode; tone: "neutral" | "warning" }) {
  return <span className={tone === "warning" ? "sv-pill sv-pill-warning" : "sv-pill"}>{children}</span>;
}

export type RagConfigFormState = {
  provider: "ollama" | "vllm";
  embedding_provider: EmbeddingProvider;
  reasoning_provider: RuntimeProvider;
  routing_provider: RuntimeProvider;
  faithfulness_provider: RuntimeProvider;
  ingestion_provider: RuntimeProvider;
  vision_provider: RuntimeProvider;
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
  vision_host: string;
  vision_port: string;
  chat_model: string;
  embed_model: string;
  reasoning_model: string;
  routing_model: string;
  faithfulness_model: string;
  ingestion_model: string;
  vision_model: string;
  reranker_model: string;
  thinking_enabled: boolean;
  query_planner_enabled: boolean;
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
  embedding_provider: EmbeddingProvider;
  reasoning_provider: RuntimeProvider | null;
  routing_provider: RuntimeProvider | null;
  faithfulness_provider: RuntimeProvider | null;
  ingestion_provider: RuntimeProvider | null;
  vision_provider: RuntimeProvider | null;
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
  vision_host: string | null;
  vision_port: number | null;
};

type InferenceLocation = "local" | "network";
type RuntimeProvider = "ollama" | "vllm";
type EmbeddingProvider = "ollama" | "openai_compatible" | "fastembed";
type LanguageRole = "chat" | "reasoning" | "routing" | "faithfulness" | "ingestion" | "vision";

export type VllmDeploymentFormState = {
  text: VllmServiceDeploymentFormState;
  embeddings: VllmServiceDeploymentFormState;
  vision: VllmServiceDeploymentFormState;
};

type VllmRestartConfirmations = Record<VllmDeploymentService, boolean>;

export type VllmServiceDeploymentFormState = {
  max_model_len: string;
  gpu_memory_utilization: string;
  max_num_seqs: string;
  max_num_batched_tokens: string;
  kv_cache_memory_bytes: string;
};

const LOCAL_INFERENCE_HOST = "host.docker.internal";
const VLLM_LOCAL_PORTS = { chat: "8010", embedding: "8011", vision: "8016" } as const;
const LANGUAGE_ROLES: LanguageRole[] = ["chat", "reasoning", "routing", "faithfulness", "ingestion", "vision"];
const MODEL_STATUS_ROLES: Array<{ key: EndpointRole; label: string }> = [
  { key: "chat", label: "Answer synthesis" },
  { key: "reasoning", label: "Reasoning" },
  { key: "routing", label: "Router" },
  { key: "faithfulness", label: "Faithfulness" },
  { key: "ingestion", label: "Ingestion metadata" },
  { key: "vision", label: "Vision" },
  { key: "embedding", label: "Embeddings" },
];
const VLLM_DEPLOYMENT_SERVICES: Array<{
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
const DEFAULT_FASTEMBED_MODEL = "nomic-ai/nomic-embed-text-v1.5-Q";
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
  return uniqueStrings(apiModels);
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values)];
}

const DEFAULT_RAG_FORM: RagConfigFormState = {
  provider: "ollama",
  embedding_provider: "fastembed",
  reasoning_provider: "ollama",
  routing_provider: "ollama",
  faithfulness_provider: "ollama",
  ingestion_provider: "ollama",
  vision_provider: "ollama",
  inference_location: "local",
  host: LOCAL_INFERENCE_HOST,
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
  vision_host: "",
  vision_port: "11434",
  chat_model: "llama3.1:8b",
  embed_model: DEFAULT_FASTEMBED_MODEL,
  reasoning_model: "",
  routing_model: "",
  faithfulness_model: "",
  ingestion_model: "",
  vision_model: "",
  reranker_model: DEFAULT_RERANKER_MODEL,
  thinking_enabled: false,
  query_planner_enabled: true,
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

const DEFAULT_VLLM_RESTART_CONFIRMATIONS: VllmRestartConfirmations = {
  text: false,
  embeddings: false,
  vision: false,
};

export function endpointsFromForm(form: RagConfigFormState): Record<EndpointRole, EndpointTarget> {
  const chatProvider = languageRoleProvider(form, "chat");
  const chat = {
    host: form.host.trim() || LOCAL_INFERENCE_HOST,
    port: Number(form.port) || Number(defaultPortForRole(chatProvider, "chat")),
  };
  const role = (
    name: Exclude<EndpointRole, "chat">,
    fallback: EndpointTarget,
    provider: RuntimeProvider,
    fallbackProvider: RuntimeProvider,
  ) => ({
    host: form[`${name}_host`].trim() || fallback.host,
    port:
      Number(form[`${name}_port`]) ||
      (provider === fallbackProvider ? fallback.port : Number(defaultPortForRole(provider, name))),
  });
  const reasoningProvider = languageRoleProvider(form, "reasoning");
  const routingProvider = languageRoleProvider(form, "routing");
  const faithfulnessProvider = languageRoleProvider(form, "faithfulness");
  const ingestionProvider = languageRoleProvider(form, "ingestion");
  const visionProvider = languageRoleProvider(form, "vision");
  const embeddingProvider = embeddingRuntimeProvider(form.embedding_provider);
  const reasoning = role("reasoning", chat, reasoningProvider, chatProvider);
  const ingestion = role("ingestion", chat, ingestionProvider, chatProvider);
  return {
    chat,
    reasoning,
    routing: role("routing", reasoning, routingProvider, reasoningProvider),
    faithfulness: role("faithfulness", chat, faithfulnessProvider, chatProvider),
    ingestion,
    vision: role("vision", ingestion, visionProvider, ingestionProvider),
    embedding: form.embedding_provider === "fastembed" ? chat : role("embedding", chat, embeddingProvider, chatProvider),
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
    host: host && host !== fallbackHost ? host : "",
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
  const visionEndpoint = roleOverride(
    config.vision_host ?? config.ingestion_host ?? config.host,
    config.vision_port ?? config.ingestion_port ?? config.port,
    config.ingestion_host ?? config.host,
    config.ingestion_port ?? config.port,
  );
  return {
    provider: config.provider ?? "ollama",
    embedding_provider: config.embedding_provider ?? (config.provider === "vllm" ? "openai_compatible" : "ollama"),
    reasoning_provider: config.reasoning_provider ?? config.provider ?? "ollama",
    routing_provider: config.routing_provider ?? config.reasoning_provider ?? config.provider ?? "ollama",
    faithfulness_provider: config.faithfulness_provider ?? config.provider ?? "ollama",
    ingestion_provider: config.ingestion_provider ?? config.provider ?? "ollama",
    vision_provider: config.vision_provider ?? config.ingestion_provider ?? config.provider ?? "ollama",
    inference_location,
    host: config.host || LOCAL_INFERENCE_HOST,
    port: String(config.port || (config.provider === "vllm" ? 8000 : 11434)),
    embedding_host: config.embedding_provider === "fastembed" ? "" : config.embedding_host || "",
    embedding_port: String(config.embedding_port || (config.provider === "vllm" ? 8001 : 11434)),
    reasoning_host: reasoningEndpoint.host,
    reasoning_port: reasoningEndpoint.port,
    routing_host: routingEndpoint.host,
    routing_port: routingEndpoint.port,
    faithfulness_host: faithfulnessEndpoint.host,
    faithfulness_port: faithfulnessEndpoint.port,
    ingestion_host: ingestionEndpoint.host,
    ingestion_port: ingestionEndpoint.port,
    vision_host: visionEndpoint.host,
    vision_port: visionEndpoint.port,
    chat_model: config.chat_model || DEFAULT_RAG_FORM.chat_model,
    embed_model: config.embed_model || DEFAULT_RAG_FORM.embed_model,
    reasoning_model: config.reasoning_model ?? config.routing_model ?? "",
    routing_model: config.routing_model ?? "",
    faithfulness_model: config.faithfulness_model ?? "",
    ingestion_model: config.ingestion_model ?? "",
    vision_model: config.vision_model ?? "",
    reranker_model: config.reranker_model || DEFAULT_RERANKER_MODEL,
    thinking_enabled: Boolean(config.thinking_enabled),
    query_planner_enabled: config.query_planner_enabled ?? true,
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
    embedding_provider: form.embedding_provider,
    reasoning_provider: form.reasoning_provider,
    routing_provider: form.routing_provider,
    faithfulness_provider: form.faithfulness_provider,
    ingestion_provider: form.ingestion_provider,
    vision_provider: form.vision_provider,
    host: endpoints.chat.host,
    port: endpoints.chat.port,
    embedding_host: form.embedding_provider === "fastembed" ? null : endpoints.embedding.host,
    embedding_port: form.embedding_provider === "fastembed" ? null : endpoints.embedding.port,
    reasoning_host: endpoints.reasoning.host,
    reasoning_port: endpoints.reasoning.port,
    routing_host: endpoints.routing.host,
    routing_port: endpoints.routing.port,
    faithfulness_host: endpoints.faithfulness.host,
    faithfulness_port: endpoints.faithfulness.port,
    ingestion_host: endpoints.ingestion.host,
    ingestion_port: endpoints.ingestion.port,
    vision_host: endpoints.vision.host,
    vision_port: endpoints.vision.port,
    chat_model: form.chat_model.trim(),
    embed_model: form.embed_model.trim(),
    reasoning_model: reasoningModel,
    routing_model: form.routing_model.trim() || reasoningModel,
    faithfulness_model: form.faithfulness_model.trim() || null,
    ingestion_model: form.ingestion_model.trim() || null,
    vision_model: form.vision_model.trim() || null,
    thinking_enabled: form.thinking_enabled,
    query_planner_enabled: form.query_planner_enabled,
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
      Object.entries(endpointsFromForm(form)).every(([role, endpoint]) =>
        role === "embedding" && form.embedding_provider === "fastembed" ? true : canFetchModelsForEndpoint(endpoint),
      ) &&
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

function CurrentRagStatus({ actionsDisabled, config, onReset }: CurrentRagStatusProps) {
  const vision = activeVisionStatus(config);
  const workspaceOverrideActive = ragConfigSourceLabel(config.source) === "workspace";
  return (
    <section className="mt-4 border-t border-surface-border pt-4" aria-labelledby="active-rag-config-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 id="active-rag-config-title" className="text-title-md">Active model routing</h3>
            <StatusBadge tone={workspaceOverrideActive ? "warning" : "neutral"}>
              Source: {ragConfigSourceLabel(config.source)}
            </StatusBadge>
          </div>
          <p className="mt-1 text-body-md text-secondary">This is the effective runtime currently used by queries and ingestion.</p>
        </div>
        <button
          type="button"
          className="sv-action-secondary disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!workspaceOverrideActive || actionsDisabled}
          onClick={onReset}
          title={workspaceOverrideActive ? "Remove the workspace override" : "Deployment defaults are already active"}
        >
          <RefreshCw size={16} />
          Restore deployment defaults
        </button>
      </div>
      <dl className="mt-3 grid gap-2 md:grid-cols-4">
        <Fact label="Synthesis" value={`${providerName(config.provider)}: ${config.chat_model}`} />
        <Fact label="Synthesis endpoint" value={config.base_url} />
        <Fact label="Reasoning" value={`${providerName(config.reasoning_provider ?? config.provider)}: ${config.reasoning_model ?? config.routing_model ?? config.chat_model}`} />
        <Fact label="Reasoning endpoint" value={config.reasoning_base_url ?? config.base_url} />
        <Fact label="Router" value={`${providerName(config.routing_provider ?? config.reasoning_provider ?? config.provider)}: ${config.routing_model ?? config.reasoning_model ?? config.chat_model}`} />
        <Fact label="Router endpoint" value={config.routing_base_url ?? config.reasoning_base_url ?? config.base_url} />
        <Fact label="Faithfulness" value={`${providerName(config.faithfulness_provider ?? config.provider)}: ${config.faithfulness_model ?? config.chat_model}`} />
        <Fact label="Faithfulness endpoint" value={config.faithfulness_base_url ?? config.base_url} />
        <Fact label="Ingestion metadata" value={`${providerName(config.ingestion_provider ?? config.provider)}: ${config.ingestion_model ?? config.chat_model}`} />
        <Fact label="Ingestion endpoint" value={config.ingestion_base_url ?? config.base_url} />
        <Fact label="Vision" value={vision.model} />
        {vision.endpoint ? <Fact label="Vision endpoint" value={vision.endpoint} /> : null}
        <Fact label="Embedding runtime" value={`${embeddingProviderName(config.embedding_provider)}: ${config.embed_model}`} />
        {config.embedding_provider !== "fastembed" ? <Fact label="Embedding endpoint" value={config.embedding_base_url} /> : null}
        <Fact label="Reranker model" value={config.reranker_model} />
        <Fact label="Model thinking" value={config.thinking_enabled ? "Enabled" : "Disabled"} />
        <Fact label="Query planner" value={config.query_planner_enabled ? "Enabled" : "Disabled"} />
        <Fact label="JSON/Layout budget" value={String(config.json_num_predict)} />
        <Fact label="Evidence budget" value={String(config.retrieval_token_budget)} />
        <Fact label="Health" value={`${config.health.status}: ${config.health.message}`} />
        <Fact label="Checked" value={formatDateTime(config.health.checked_at)} />
        <Fact label="Chat latency" value={formatLatency(config.health.chat_latency_ms)} />
        <Fact label="Embed latency" value={formatLatency(config.health.embed_latency_ms)} />
      </dl>
    </section>
  );
}

type CurrentRagStatusProps = {
  actionsDisabled: boolean;
  config: RagConfig;
  onReset: () => void;
};


type VllmDeploymentSectionProps = {
  applyPending: boolean;
  applyingService: VllmDeploymentService | null;
  config: VllmDeploymentConfig | undefined;
  draft: VllmDeploymentFormState;
  draftIsDirty: boolean;
  formIsValid: boolean;
  loadError: unknown;
  loadFailed: boolean;
  restartConfirmed: VllmRestartConfirmations;
  savePending: boolean;
  onApply: (service: VllmDeploymentService) => void;
  onDraftChange: (draft: VllmDeploymentFormState) => void;
  onRestartConfirmedChange: (confirmed: VllmRestartConfirmations) => void;
  onSave: () => void;
};




function InferenceRoleMatrix({
  canFetchModels,
  form,
  modelOptions,
  modelsLoading,
  modelSelectDisabled,
  modelStatuses,
  rerankerModelOptions,
  rerankerPlaceholder,
  rerankerSelectDisabled,
  onChange,
}: InferenceRoleMatrixProps) {
  return (
    <section className="rounded border border-surface-border" aria-labelledby="inference-role-matrix-title">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-surface-border p-3">
        <div>
          <h3 id="inference-role-matrix-title" className="text-title-md">Inference role assignments</h3>
          <p className="mt-1 text-body-md text-secondary">
            Choose the provider, endpoint, and model for each RAG role. Rows may share the same server or point to separate services.
          </p>
        </div>
        <span className="rounded border border-surface-border px-2 py-1 text-label-sm text-secondary">
          {providerName(form.provider)} synthesis
        </span>
      </div>
      <div className="hidden border-b border-surface-border bg-surface-container-low px-3 py-2 text-label-sm text-secondary lg:grid lg:grid-cols-[minmax(10rem,1fr)_6.5rem_minmax(13rem,1.2fr)_minmax(11rem,1fr)] lg:gap-2">
        <span>Role</span>
        <span>Provider</span>
        <span>Endpoint</span>
        <span>Model</span>
      </div>
      <div className="divide-y divide-surface-border">
        <LanguageRoleRow
          description="Final grounded response returned to the user."
          form={form}
          modelOptions={modelOptions.chat}
          modelPlaceholder={modelPlaceholderForStatus(modelStatuses.chat, {
            canFetch: canFetchModels,
            loading: modelsLoading,
          })}
          modelSelectDisabled={modelSelectDisabled}
          modelStatus={modelStatuses.chat}
          onChange={onChange}
          role="chat"
          title="Answer synthesis"
        />
        <LanguageRoleRow
          description="Planning, rewrites, date handling, and complex retrieval support."
          emptyLabel="Use synthesis model"
          form={form}
          modelOptions={modelOptions.reasoning}
          modelPlaceholder={modelPlaceholderForStatus(modelStatuses.reasoning, {
            canFetch: canFetchModels,
            loading: modelsLoading,
          })}
          modelSelectDisabled={modelSelectDisabled}
          modelStatus={modelStatuses.reasoning}
          onChange={onChange}
          role="reasoning"
          title="Reasoning"
        />
        <LanguageRoleRow
          description="Ambiguous route checks before retrieval or artifact generation."
          emptyLabel="Use reasoning model"
          form={form}
          modelOptions={modelOptions.routing}
          modelPlaceholder={modelPlaceholderForStatus(modelStatuses.routing, {
            canFetch: canFetchModels,
            loading: modelsLoading,
          })}
          modelSelectDisabled={modelSelectDisabled}
          modelStatus={modelStatuses.routing}
          onChange={onChange}
          role="routing"
          title="Router"
        />
        <LanguageRoleRow
          description="Grounding check for generated answers."
          emptyLabel="Use synthesis model"
          form={form}
          modelOptions={modelOptions.faithfulness}
          modelPlaceholder={modelPlaceholderForStatus(modelStatuses.faithfulness, {
            canFetch: canFetchModels,
            loading: modelsLoading,
          })}
          modelSelectDisabled={modelSelectDisabled}
          modelStatus={modelStatuses.faithfulness}
          onChange={onChange}
          role="faithfulness"
          title="Faithfulness"
        />
        <LanguageRoleRow
          description="Summaries, topics, document types, and claims during ingestion."
          emptyLabel="Use synthesis model"
          form={form}
          modelOptions={modelOptions.ingestion}
          modelPlaceholder={modelPlaceholderForStatus(modelStatuses.ingestion, {
            canFetch: canFetchModels,
            loading: modelsLoading,
          })}
          modelSelectDisabled={modelSelectDisabled}
          modelStatus={modelStatuses.ingestion}
          onChange={onChange}
          role="ingestion"
          title="Ingestion metadata"
        />
        <LanguageRoleRow
          description="Image OCR, captions, and PDF layout repair."
          emptyLabel="Use ingestion model"
          form={form}
          modelOptions={modelOptions.vision}
          modelPlaceholder={modelPlaceholderForStatus(modelStatuses.vision, {
            canFetch: canFetchModels,
            loading: modelsLoading,
          })}
          modelSelectDisabled={modelSelectDisabled}
          modelStatus={modelStatuses.vision}
          onChange={onChange}
          role="vision"
          title="Vision"
        />
        <EmbeddingRoleRow
          form={form}
          modelOptions={modelOptions.embedding}
          modelPlaceholder={modelPlaceholderForStatus(modelStatuses.embedding, {
            canFetch: canFetchModels,
            loading: modelsLoading,
          })}
          modelSelectDisabled={modelSelectDisabled}
          modelStatus={modelStatuses.embedding}
          onChange={onChange}
        />
        <RerankerRoleRow
          form={form}
          modelOptions={rerankerModelOptions}
          modelPlaceholder={rerankerPlaceholder}
          modelSelectDisabled={rerankerSelectDisabled}
          onChange={onChange}
        />
      </div>
    </section>
  );
}

type InferenceRoleMatrixProps = {
  canFetchModels: boolean;
  form: RagConfigFormState;
  modelOptions: ReturnType<typeof modelOptionsFromDiscovery>;
  modelsLoading: boolean;
  modelSelectDisabled: boolean;
  modelStatuses: Record<string, RagModelDiscoveryStatus>;
  rerankerModelOptions: string[];
  rerankerPlaceholder: string;
  rerankerSelectDisabled: boolean;
  onChange: (value: RagConfigFormState) => void;
};

function LanguageRoleRow({
  description,
  emptyLabel,
  form,
  modelOptions,
  modelPlaceholder,
  modelSelectDisabled,
  modelStatus,
  onChange,
  role,
  title,
}: LanguageRoleRowProps) {
  const provider = languageRoleProvider(form, role);
  const modelValue = languageRoleModel(form, role);
  const status = statusTone(modelStatus);
  return (
    <div className="grid gap-2 p-3 lg:grid-cols-[minmax(10rem,1fr)_6.5rem_minmax(13rem,1.2fr)_minmax(11rem,1fr)] lg:items-start">
      <div>
        <div className="text-body-md font-bold text-on-surface">{title}</div>
        <div className="mt-1 text-body-md text-secondary">{description}</div>
        <div className="mt-1 text-label-sm text-secondary">{roleModelInheritance(role, modelValue)}</div>
      </div>
      <RuntimeProviderSelect
        ariaLabel={`${title} provider`}
        value={provider}
        onChange={(nextProvider) => onChange(withLanguageRoleProvider(form, role, nextProvider))}
      />
      <EndpointEditor form={form} provider={provider} role={role} onChange={onChange} />
      <label className="sv-field">
        <span className="sv-label lg:hidden">{title} model</span>
        <ModelSelect
          value={modelValue}
          onChange={(model) => onChange(withLanguageRoleModel(form, role, model))}
          models={modelOptions}
          placeholder={modelPlaceholder}
          emptyLabel={emptyLabel}
          disabled={modelSelectDisabled}
        />
        {modelStatus ? (
          <span className={`text-body-md ${status === "ok" ? "text-secondary" : "text-warning-amber"}`}>
            {modelStatus.message}
          </span>
        ) : null}
      </label>
    </div>
  );
}

type LanguageRoleRowProps = {
  role: LanguageRole;
  title: string;
  description: string;
  emptyLabel?: string;
  form: RagConfigFormState;
  modelOptions: string[];
  modelPlaceholder: string;
  modelSelectDisabled: boolean;
  modelStatus?: RagModelDiscoveryStatus;
  onChange: (value: RagConfigFormState) => void;
};

function EmbeddingRoleRow({ form, modelOptions, modelPlaceholder, modelSelectDisabled, modelStatus, onChange }: EmbeddingRoleRowProps) {
  const provider = embeddingRuntimeProvider(form.embedding_provider);
  const status = statusTone(modelStatus);
  return (
    <div className="grid gap-2 p-3 lg:grid-cols-[minmax(10rem,1fr)_6.5rem_minmax(13rem,1.2fr)_minmax(11rem,1fr)] lg:items-start">
      <div>
        <div className="text-body-md font-bold text-on-surface">Embeddings</div>
        <div className="mt-1 text-body-md text-secondary">Vectors for chunks and queries. Changing this requires reindexing documents.</div>
      </div>
      <EmbeddingProviderSelect
        value={form.embedding_provider}
        onChange={(embeddingProvider) => onChange(withEmbeddingProvider(form, embeddingProvider))}
      />
      {form.embedding_provider === "fastembed" ? (
        <div className="rounded border border-surface-border bg-surface-container-low px-2.5 py-2 text-body-md text-secondary">
          Runs inside API and ingestion workers using the local model cache.
        </div>
      ) : (
        <EndpointEditor form={form} provider={provider} role="embedding" onChange={onChange} />
      )}
      <label className="sv-field">
        <span className="sv-label lg:hidden">Embedding model</span>
        <ModelSelect
          value={form.embed_model}
          onChange={(embed_model) => onChange({ ...form, embed_model })}
          models={modelOptions}
          placeholder={modelPlaceholder}
          disabled={modelSelectDisabled}
        />
        {modelStatus ? (
          <span className={`text-body-md ${status === "ok" ? "text-secondary" : "text-warning-amber"}`}>
            {modelStatus.message}
          </span>
        ) : null}
      </label>
    </div>
  );
}

type EmbeddingRoleRowProps = {
  form: RagConfigFormState;
  modelOptions: string[];
  modelPlaceholder: string;
  modelSelectDisabled: boolean;
  modelStatus?: RagModelDiscoveryStatus;
  onChange: (value: RagConfigFormState) => void;
};

function RerankerRoleRow({ form, modelOptions, modelPlaceholder, modelSelectDisabled, onChange }: RerankerRoleRowProps) {
  return (
    <div className="grid gap-2 p-3 lg:grid-cols-[minmax(10rem,1fr)_6.5rem_minmax(13rem,1.2fr)_minmax(11rem,1fr)] lg:items-start">
      <div>
        <div className="text-body-md font-bold text-on-surface">Reranker</div>
        <div className="mt-1 text-body-md text-secondary">Reorders retrieved chunks before source selection and synthesis.</div>
      </div>
      <div className="rounded border border-surface-border bg-surface-container-low px-2.5 py-2 text-body-md text-secondary">
        Local catalog
      </div>
      <div className="rounded border border-surface-border bg-surface-container-low px-2.5 py-2 text-body-md text-secondary">
        No inference endpoint
      </div>
      <label className="sv-field">
        <span className="sv-label lg:hidden">Reranker model</span>
        <ModelSelect
          value={form.reranker_model}
          onChange={(reranker_model) => onChange({ ...form, reranker_model })}
          models={modelOptions}
          placeholder={modelPlaceholder}
          disabled={modelSelectDisabled}
        />
      </label>
    </div>
  );
}

type RerankerRoleRowProps = {
  form: RagConfigFormState;
  modelOptions: string[];
  modelPlaceholder: string;
  modelSelectDisabled: boolean;
  onChange: (value: RagConfigFormState) => void;
};

function RuntimeProviderSelect({ ariaLabel, onChange, value }: RuntimeProviderSelectProps) {
  return (
    <label className="sv-field">
      <span className="sv-label lg:hidden">Provider</span>
      <select aria-label={ariaLabel} value={value} onChange={(event) => onChange(event.target.value as RuntimeProvider)} className="sv-select">
        <option value="ollama">Ollama</option>
        <option value="vllm">vLLM</option>
      </select>
    </label>
  );
}

type RuntimeProviderSelectProps = {
  ariaLabel: string;
  value: RuntimeProvider;
  onChange: (value: RuntimeProvider) => void;
};

function EmbeddingProviderSelect({ onChange, value }: EmbeddingProviderSelectProps) {
  return (
    <label className="sv-field">
      <span className="sv-label lg:hidden">Provider</span>
      <select value={value} onChange={(event) => onChange(event.target.value as EmbeddingProvider)} className="sv-select">
        <option value="fastembed">FastEmbed</option>
        <option value="ollama">Ollama</option>
        <option value="openai_compatible">vLLM</option>
      </select>
    </label>
  );
}

type EmbeddingProviderSelectProps = {
  value: EmbeddingProvider;
  onChange: (value: EmbeddingProvider) => void;
};

function EndpointEditor({ form, provider, role, onChange }: EndpointFieldsProps) {
  const label = endpointLabel(form, role, provider);
  return (
    <div className="rounded border border-surface-border bg-surface-container-low px-2.5 py-2">
      <EndpointFields form={form} provider={provider} role={role} onChange={onChange} />
      <p className="mt-1 break-all text-label-sm text-secondary">{label}</p>
    </div>
  );
}

function EndpointFields({ form, provider, role, onChange }: EndpointFieldsProps) {
  const hostValue = role === "chat" ? form.host : form[`${role}_host`];
  const portValue = role === "chat" ? form.port : form[`${role}_port`];
  const endpoint = endpointsFromForm(form)[role];
  const defaultPort = defaultPortForRole(provider, role);
  const hostPlaceholder = role === "chat" ? LOCAL_INFERENCE_HOST : `Same host, currently ${endpoint.host || LOCAL_INFERENCE_HOST}`;

  const updateHost = (host: string) => {
    if (role === "chat") {
      onChange({ ...form, host });
      return;
    }
    onChange({ ...form, [`${role}_host`]: host });
  };
  const updatePort = (port: string) => {
    if (role === "chat") {
      onChange({ ...form, port });
      return;
    }
    onChange({ ...form, [`${role}_port`]: port });
  };

  return (
    <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_7rem]">
      <label className="sv-field">
        <input
          aria-label={`${role} endpoint host`}
          value={hostValue}
          onChange={(event) => updateHost(event.target.value)}
          placeholder={hostPlaceholder}
          className="sv-input"
        />
      </label>
      <label className="sv-field">
        <input
          aria-label={`${role} endpoint port`}
          type="number"
          min={1}
          max={65535}
          value={portValue}
          onChange={(event) => updatePort(event.target.value)}
          placeholder={defaultPort}
          className="sv-input"
        />
      </label>
    </div>
  );
}

type EndpointFieldsProps = {
  form: RagConfigFormState;
  provider: RuntimeProvider;
  role: EndpointRole;
  onChange: (value: RagConfigFormState) => void;
};

function languageRoleProvider(form: RagConfigFormState, role: LanguageRole): RuntimeProvider {
  if (role === "chat") return form.provider;
  return form[`${role}_provider`];
}

function languageRoleModel(form: RagConfigFormState, role: LanguageRole): string {
  if (role === "chat") return form.chat_model;
  return form[`${role}_model`];
}

function withLanguageRoleProvider(
  form: RagConfigFormState,
  role: LanguageRole,
  provider: RuntimeProvider,
): RagConfigFormState {
  const next = {
    ...form,
    thinking_enabled: provider === "vllm" && role === "chat" ? false : form.thinking_enabled,
  };
  if (role === "chat") {
    return {
      ...next,
      provider,
      port: defaultPortForRole(provider, role),
      chat_model: "",
    };
  }
  return {
    ...next,
    [`${role}_provider`]: provider,
    [`${role}_host`]: "",
    [`${role}_port`]: role === "vision" && provider === "vllm" ? defaultPortForRole(provider, role) : "",
    [`${role}_model`]: "",
  };
}

function withLanguageRoleModel(form: RagConfigFormState, role: LanguageRole, model: string): RagConfigFormState {
  if (role === "chat") return { ...form, chat_model: model };
  return { ...form, [`${role}_model`]: model };
}

function withEmbeddingProvider(form: RagConfigFormState, embedding_provider: EmbeddingProvider): RagConfigFormState {
  return embeddingProviderDefaults({ ...form, embedding_provider });
}

function embeddingRuntimeProvider(provider: EmbeddingProvider): RuntimeProvider {
  return provider === "openai_compatible" ? "vllm" : "ollama";
}

function defaultPortForRole(provider: RuntimeProvider, role: EndpointRole): string {
  if (provider === "ollama") return "11434";
  if (role === "embedding") return VLLM_LOCAL_PORTS.embedding;
  if (role === "vision") return VLLM_LOCAL_PORTS.vision;
  return VLLM_LOCAL_PORTS.chat;
}

function RuntimeAdvancedSettings({ form, onChange }: { form: RagConfigFormState; onChange: (value: RagConfigFormState) => void }) {
  const hasOllamaLanguageRole = LANGUAGE_ROLES.some((role) => languageRoleProvider(form, role) === "ollama");
  return (
    <section className="rounded border border-surface-border p-3" aria-labelledby="runtime-advanced-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="runtime-advanced-title" className="text-title-md">Runtime behavior</h3>
          <p className="mt-1 text-body-md text-secondary">Shared budgets and switches used by the selected role assignments.</p>
        </div>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="sv-field">
          <span className="sv-label">JSON/Layout output budget</span>
          <input
            type="number"
            min={256}
            max={32768}
            value={form.json_num_predict}
            onChange={(event) => onChange({ ...form, json_num_predict: event.target.value })}
            className="sv-input"
          />
          <span className="text-body-md text-secondary">Used by planning, composition, and layout contracts.</span>
        </label>
        <label className="sv-field">
          <span className="sv-label">Evidence token budget</span>
          <input
            type="number"
            min={1000}
            max={200000}
            value={form.retrieval_token_budget}
            onChange={(event) => onChange({ ...form, retrieval_token_budget: event.target.value })}
            className="sv-input"
          />
          <span className="text-body-md text-secondary">Caps retrieved evidence passed into synthesis.</span>
        </label>
        <label className="sv-field">
          <span className="sv-label">Chat timeout</span>
          <input
            type="number"
            min={1}
            value={form.chat_timeout_seconds}
            onChange={(event) => onChange({ ...form, chat_timeout_seconds: event.target.value })}
            className="sv-input"
          />
          <span className="text-body-md text-secondary">Maximum seconds to wait for language roles.</span>
        </label>
        <label className="sv-field">
          <span className="sv-label">Embed timeout</span>
          <input
            type="number"
            min={1}
            value={form.embed_timeout_seconds}
            onChange={(event) => onChange({ ...form, embed_timeout_seconds: event.target.value })}
            className="sv-input"
          />
          <span className="text-body-md text-secondary">Maximum seconds to wait for embedding requests.</span>
        </label>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {hasOllamaLanguageRole ? (
          <label className="flex items-start justify-between gap-3 rounded border border-surface-border bg-surface-container-low p-3">
            <span>
              <span className="block text-body-md font-bold text-on-surface">Model thinking</span>
              <span className="mt-1 block text-body-md text-secondary">
                Applies to Ollama language roles only. Keep off for direct model output.
              </span>
            </span>
            <span className="flex shrink-0 items-center gap-3">
              <span className="text-label-md text-secondary">{form.thinking_enabled ? "Enabled" : "Disabled"}</span>
              <input
                type="checkbox"
                role="switch"
                aria-label="Enable model thinking for Ollama language roles"
                checked={form.thinking_enabled}
                onChange={(event) => onChange({ ...form, thinking_enabled: event.target.checked })}
                className="h-5 w-5 accent-primary"
              />
            </span>
          </label>
        ) : null}
        <label className="flex items-start justify-between gap-3 rounded border border-surface-border bg-surface-container-low p-3">
          <span>
            <span className="block text-body-md font-bold text-on-surface">Query planner</span>
            <span className="mt-1 block text-body-md text-secondary">
              Route complex retrieval questions through focused sub-query planning before evidence search.
            </span>
          </span>
          <span className="flex shrink-0 items-center gap-3">
            <span className="text-label-md text-secondary">{form.query_planner_enabled ? "Enabled" : "Disabled"}</span>
            <input
              type="checkbox"
              role="switch"
              aria-label="Enable query planner for complex retrieval questions"
              checked={form.query_planner_enabled}
              onChange={(event) => onChange({ ...form, query_planner_enabled: event.target.checked })}
              className="h-5 w-5 accent-primary"
            />
          </span>
        </label>
      </div>
    </section>
  );
}

export function providerDefaults(form: RagConfigFormState): RagConfigFormState {
  const port = defaultPortForRole(form.provider, "chat");
  if (form.provider === "vllm") {
    return embeddingProviderDefaults({
      ...clearModelSelections({
        ...form,
        host: LOCAL_INFERENCE_HOST,
        reasoning_provider: "vllm",
        routing_provider: "vllm",
        faithfulness_provider: "vllm",
        ingestion_provider: "vllm",
        vision_provider: "ollama",
        embedding_provider: "fastembed",
      }),
      port,
      reasoning_port: "",
      routing_port: "",
      faithfulness_port: "",
      ingestion_port: "",
      vision_port: "",
      thinking_enabled: false,
    });
  }
  return embeddingProviderDefaults({
    ...clearModelSelections({
      ...form,
      host: LOCAL_INFERENCE_HOST,
      reasoning_provider: "ollama",
      routing_provider: "ollama",
      faithfulness_provider: "ollama",
      ingestion_provider: "ollama",
      vision_provider: "ollama",
    }),
    port,
    reasoning_port: "",
    routing_port: "",
    faithfulness_port: "",
    ingestion_port: "",
    vision_port: "",
  });
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

function embeddingProviderDefaults(form: RagConfigFormState): RagConfigFormState {
  if (form.embedding_provider === "fastembed") {
    return {
      ...form,
      embedding_host: "",
      embedding_port: "",
      embed_model: DEFAULT_FASTEMBED_MODEL,
    };
  }
  if (form.embedding_provider === "ollama") {
    return {
      ...form,
      embedding_host: "",
      embedding_port: defaultPortForRole("ollama", "embedding"),
      embed_model: "nomic-embed-text:latest",
    };
  }
  return {
    ...form,
    embedding_host: "",
    embedding_port: defaultPortForRole("vllm", "embedding"),
    embed_model: "",
  };
}

function discoveryTarget(request: RagConfigRequest): RagModelLookupTarget {
  return {
    provider: request.provider ?? "ollama",
    embedding_provider: request.embedding_provider ?? "fastembed",
    reasoning_provider: request.reasoning_provider ?? null,
    routing_provider: request.routing_provider ?? null,
    faithfulness_provider: request.faithfulness_provider ?? null,
    ingestion_provider: request.ingestion_provider ?? null,
    vision_provider: request.vision_provider ?? null,
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
    vision_host: request.vision_host ?? null,
    vision_port: request.vision_port ?? null,
  };
}

type EndpointRole = "chat" | "reasoning" | "routing" | "faithfulness" | "ingestion" | "vision" | "embedding";

function providerName(provider: string) {
  return provider === "vllm" ? "vLLM" : "Ollama";
}

export function activeStackLabel(config: RagConfig) {
  const provider = providerName(config.provider);
  const embedding = embeddingProviderName(config.embedding_provider);
  const vision = config.vision_model?.trim()
    ? `${providerName(config.vision_provider ?? config.ingestion_provider ?? config.provider)} vision`
    : "vision not configured";
  return `${provider} text, ${embedding} embeddings, ${vision}`;
}

export function ragConfigSourceLabel(source: RagConfig["source"]): string {
  const normalizedSource = source.trim().toLowerCase();
  if (normalizedSource === "workspace") return "workspace";
  if (normalizedSource === "env" || normalizedSource === "environment") return "environment";
  return normalizedSource || "environment";
}

export function ragConfigActionsLocked({
  dialogOpen,
  resetPending,
  savePending,
  testPending,
}: {
  dialogOpen: boolean;
  resetPending: boolean;
  savePending: boolean;
  testPending: boolean;
}): boolean {
  return dialogOpen || resetPending || savePending || testPending;
}

export function activeVisionStatus(config: RagConfig): { endpoint: string | null; model: string } {
  const visionModel = config.vision_model?.trim();
  if (!visionModel) return { endpoint: null, model: "Not configured" };
  return {
    endpoint: config.vision_base_url ?? config.ingestion_base_url ?? config.base_url,
    model: `${providerName(config.vision_provider ?? config.ingestion_provider ?? config.provider)}: ${visionModel}`,
  };
}

export function stackTemplateFromForm(form: RagConfigFormState): StackTemplate {
  const ollamaLanguage =
    form.provider === "ollama" &&
    form.reasoning_provider === "ollama" &&
    form.routing_provider === "ollama" &&
    form.faithfulness_provider === "ollama" &&
    form.ingestion_provider === "ollama" &&
    form.vision_provider === "ollama";
  if (ollamaLanguage) return "ollama";
  const vllmTextStack =
    form.provider === "vllm" &&
    form.reasoning_provider === "vllm" &&
    form.routing_provider === "vllm" &&
    form.faithfulness_provider === "vllm" &&
    form.ingestion_provider === "vllm" &&
    form.vision_provider === "ollama" &&
    form.embedding_provider === "fastembed";
  return vllmTextStack ? "vllm" : "custom";
}

function stackTemplateLabel(template: StackTemplate) {
  if (template === "vllm") return "vLLM text stack";
  if (template === "ollama") return "Ollama local";
  return "Custom role mix";
}

function roleAssignmentSummary(form: RagConfigFormState) {
  const vllmCount = LANGUAGE_ROLES.filter((role) => languageRoleProvider(form, role) === "vllm").length;
  const ollamaCount = LANGUAGE_ROLES.length - vllmCount;
  return `${vllmCount} vLLM, ${ollamaCount} Ollama, ${embeddingProviderName(form.embedding_provider)}`;
}

function behaviorSummaryFromForm(form: RagConfigFormState) {
  return `Planner ${form.query_planner_enabled ? "on" : "off"}, evidence ${form.retrieval_token_budget}`;
}

export function discoveryHealthLabel(
  result: RagModelDiscoveryResult | undefined,
  loading: boolean,
  error: Error | null,
) {
  if (loading) return "Checking services";
  if (error) return "Check failed";
  const statuses = Object.values(result?.model_statuses ?? {});
  if (statuses.length === 0) return "Not checked";
  const errors = statuses.filter((status) => status.status === "error").length;
  const empty = statuses.filter((status) => status.status === "empty").length;
  if (errors > 0) return `${errors} service${errors === 1 ? "" : "s"} need attention`;
  if (empty > 0) return `${empty} catalog${empty === 1 ? "" : "s"} empty`;
  return "All selected services responded";
}

function statusTone(status: RagModelDiscoveryStatus | undefined): "ok" | "warning" | "error" | "neutral" {
  if (!status) return "neutral";
  if (status.status === "ok") return "ok";
  if (status.status === "empty") return "warning";
  if (status.status === "error") return "error";
  return "neutral";
}

export function modelPlaceholderForStatus(
  status: RagModelDiscoveryStatus | undefined,
  options: { canFetch: boolean; loading: boolean },
) {
  const { canFetch, loading } = options;
  if (!canFetch) return "Enter host and port";
  if (loading) return "Loading models";
  if (status?.status === "error" || status?.status === "empty") return status.message;
  return "Choose model";
}

function endpointLabel(form: RagConfigFormState, role: EndpointRole, provider: RuntimeProvider) {
  if (role === "embedding" && form.embedding_provider === "fastembed") return "Local FastEmbed cache";
  const endpoint = endpointsFromForm(form)[role];
  const service = providerName(provider);
  return `${service} at ${endpoint.host}:${endpoint.port}`;
}

function roleModelInheritance(role: LanguageRole, modelValue: string) {
  if (modelValue.trim()) return "Explicit model";
  if (role === "reasoning") return "Uses synthesis model";
  if (role === "routing") return "Uses reasoning model";
  if (role === "vision") return "Uses ingestion model";
  return role === "chat" ? "Required model" : "Uses synthesis model";
}

function embeddingProviderName(provider: EmbeddingProvider) {
  if (provider === "fastembed") return "FastEmbed local";
  if (provider === "openai_compatible") return "OpenAI-compatible";
  return "Ollama";
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

function isValidWorkerConcurrency(value: number) {
  return Number.isFinite(value) && value >= 1 && value <= 10;
}

function isValidThresholdPercent(value: number) {
  return Number.isFinite(value) && value >= 0 && value <= 100;
}

function safePdfImageReviewThreshold(value: number | null | undefined) {
  return Number.isFinite(value) ? Number(value) : 64;
}

function isValidPdfImageReviewThreshold(value: number) {
  return Number.isInteger(value) && value >= 0 && value <= 10000;
}

export function pdfImageReviewThresholdLabel(value: number | null | undefined): string {
  const threshold = safePdfImageReviewThreshold(value);
  return threshold > 0 ? `Above ${threshold} images` : "Off";
}

export function thresholdPercentFromConfig(value: number | null | undefined): number {
  return Number.isFinite(value) ? Math.round(Number(value) * 100) : 90;
}

export function thresholdFromPercent(value: number): number {
  if (!Number.isFinite(value)) return 0.9;
  return Math.max(0, Math.min(1, Number((value / 100).toFixed(4))));
}
