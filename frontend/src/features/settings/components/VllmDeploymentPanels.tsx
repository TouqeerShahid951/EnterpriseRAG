import { Boxes, RefreshCw, Save, SlidersHorizontal } from "lucide-react";

import { Fact, InlineMessage } from "@/components/layout/Common";
import { ServiceDiscoveryStatus, StatusBadge } from "@/features/settings/components/ModelsAndRolesPanel";
import {
  DEFAULT_VLLM_RESTART_CONFIRMATIONS,
  VLLM_DEPLOYMENT_SERVICES,
  type VllmDeploymentFormState,
  type VllmRestartConfirmations,
  type VllmServiceDeploymentFormState,
} from "@/features/settings/models/vllmDeploymentForm";
import type { RagModelDiscoveryResult, VllmDeploymentConfig, VllmDeploymentService } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";
import { labelize } from "@/features/settings/models/settingsLabels";

export function InferenceServicesPanel({
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

export type InferenceServicesPanelProps = VllmDeploymentSectionProps & {
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
