import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { adminApi, type IngestConfigRequest, type RagConfigRequest, type VllmDeploymentConfigRequest } from "@/lib/api/contracts";
import { isPlatformAdmin } from "@/lib/auth/authz";
import { useToast } from "@/components/feedback/ToastProvider";
import { PrudentiaBasicPage } from "@/components/layout/PrudentiaWorkspace";
import {
  ConfigPanelTabs,
  RuntimeStatusStrip,
  type ConfigPanel,
} from "@/features/settings/components/SettingsRuntimeHeader";
import type { RouteId } from "@/routes/routes";
import type {
  IngestConfig,
  RagConfig,
  RagConfigTestResult,
  User as AuthUser,
  VllmDeploymentConfig,
  VllmDeploymentService,
} from "@/types/api";
import { errorMessage } from "@/lib/utils/format";
import {
  DEFAULT_RAG_FORM,
  type RagConfigFormState,
  type RagModelLookupTarget,
  canFetchModelsForEndpoint,
  discoveryTarget,
  endpointsFromForm,
  formFromConfig,
  modelOptionsFromDiscovery,
  rerankerOptionsFromCatalog,
  requestFromForm,
} from "@/features/settings/models/ragConfigForm";
import {
  DEFAULT_VLLM_DEPLOYMENT_FORM,
  DEFAULT_VLLM_RESTART_CONFIRMATIONS,
  type VllmDeploymentFormState,
  type VllmRestartConfirmations,
  canSubmitVllmDeploymentConfig,
  requestFromVllmForm,
  vllmFormFromConfig,
} from "@/features/settings/models/vllmDeploymentForm";
import {
  activeStackLabel,
  discoveryHealthLabel,
  embeddingProviderName,
  formatLatency,
  isValidPdfImageReviewThreshold,
  isValidThresholdPercent,
  isValidWorkerConcurrency,
  labelize,
  providerName,
  ragConfigActionsLocked,
  ragConfigSourceLabel,
  safePdfImageReviewThreshold,
  safeWorkerConcurrency,
  thresholdFromPercent,
  thresholdPercentFromConfig,
} from "@/features/settings/models/settingsLabels";
import { IngestionControlsPanel } from "@/features/settings/components/IngestionControlsPanel";
import { RagConfigResetDialog } from "@/features/settings/components/RagConfigResetDialog";
import { ModelsAndRolesPanel } from "@/features/settings/components/ModelsAndRolesPanel";
import { InferenceServicesPanel } from "@/features/settings/components/VllmDeploymentPanels";

export type { RagConfigFormState } from "@/features/settings/models/ragConfigForm";
export {
  SUPPORTED_RERANKER_MODELS,
  endpointsFromForm,
  modelOptionsFromDiscovery,
  providerDefaults,
  rerankerOptionsFromCatalog,
  requestFromForm,
} from "@/features/settings/models/ragConfigForm";
export type { VllmDeploymentFormState } from "@/features/settings/models/vllmDeploymentForm";
export { requestFromVllmForm } from "@/features/settings/models/vllmDeploymentForm";
export {
  activeStackLabel,
  activeVisionStatus,
  discoveryHealthLabel,
  modelPlaceholderForStatus,
  pdfImageReviewThresholdLabel,
  ragConfigActionsLocked,
  ragConfigSourceLabel,
  stackTemplateFromForm,
  thresholdFromPercent,
  thresholdPercentFromConfig,
} from "@/features/settings/models/settingsLabels";


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
  const discoveryState = discoveryHealthLabel(
    ragDiscoveryResult,
    ragModelsAreLoading,
    ragModelsQuery.isError && ragModelsMatchDraft ? ragModelsQuery.error : null,
  );
  const restartRequirement = vllmDraftIsDirty
    ? "vLLM limits unsaved"
    : vllmDeploymentQuery.data?.apply_status
      ? labelize(vllmDeploymentQuery.data.apply_status)
      : "Loading";

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
            activeStack={ragConfigQuery.data ? activeStackLabel(ragConfigQuery.data) : "Loading"}
            configurationSource={ragConfigQuery.data ? ragConfigSourceLabel(ragConfigQuery.data.source) : "Loading"}
            discoveryState={discoveryState}
            draftState={ragDraftIsDirty ? "Unsaved changes" : "Matches active routing"}
            restartRequirement={restartRequirement}
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
          <IngestionControlsPanel
            config={ingestConfigQuery.data}
            configError={ingestConfigQuery.error}
            configFailed={ingestConfigQuery.isError}
            graphEnrichmentEnabled={graphEnrichmentEnabled}
            highConcurrencyConfirmed={highConcurrencyConfirmed}
            isValid={ingestConfigIsValid}
            ocrReviewThresholdPercent={ocrReviewThresholdPercent}
            pdfImageReviewThreshold={pdfImageReviewThreshold}
            savePending={saveIngestConfigMutation.isPending}
            visionLayoutRepairEnabled={visionLayoutRepairEnabled}
            workerConcurrency={workerConcurrency}
            onGraphEnrichmentChange={setGraphEnrichmentEnabled}
            onHighConcurrencyConfirmedChange={setHighConcurrencyConfirmed}
            onOcrReviewThresholdChange={setOcrReviewThresholdPercent}
            onPdfImageReviewThresholdChange={setPdfImageReviewThreshold}
            onSave={() => saveIngestConfigMutation.mutate({
              worker_concurrency: workerConcurrency,
              quality_preset: ingestConfigQuery.data?.quality_preset ?? "fast",
              ocr_review_confidence_threshold: thresholdFromPercent(ocrReviewThresholdPercent),
              pdf_image_review_threshold: pdfImageReviewThreshold,
              vision_layout_repair_enabled: visionLayoutRepairEnabled,
              graph_enrichment_enabled: graphEnrichmentEnabled,
            })}
            onVisionLayoutRepairChange={setVisionLayoutRepairEnabled}
            onWorkerConcurrencyChange={(value) => {
              setWorkerConcurrency(value);
              setHighConcurrencyConfirmed(false);
            }}
          />
        ) : null}
      </div>
      <RagConfigResetDialog
        draftIsDirty={ragDraftIsDirty}
        error={resetRagConfigMutation.error}
        isError={resetRagConfigMutation.isError}
        isPending={resetRagConfigMutation.isPending}
        onCancel={() => {
          if (!resetRagConfigMutation.isPending) {
            setRagResetDialogOpen(false);
            resetRagConfigMutation.reset();
          }
        }}
        onConfirm={() => resetRagConfigMutation.mutate()}
        open={ragResetDialogOpen}
      />
    </PrudentiaBasicPage>
  );
}

type Props = {
  currentUser: AuthUser;
  onLogout: () => void;
  onNavigate: (route: RouteId) => void;
};
