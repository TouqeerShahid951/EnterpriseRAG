import { useState } from "react";
import { AlertTriangle, Boxes, CheckCircle2, ChevronDown, Cpu, RefreshCw, Save, ServerCog, SlidersHorizontal, Wifi } from "lucide-react";

import { Fact, InlineMessage } from "@/components/layout/Common";
import { InferenceRoleMatrix } from "@/features/settings/components/InferenceRoleMatrix";
import { RuntimeAdvancedSettings } from "@/features/settings/components/RuntimeSettingsFields";
import {
  MODEL_STATUS_ROLES,
  type RagConfigFormState,
  canSubmitRagConfig,
  modelOptionsFromDiscovery,
  providerDefaults,
} from "@/features/settings/models/ragConfigForm";
import {
  type StackTemplate,
  activeVisionStatus,
  behaviorSummaryFromForm,
  discoveryHealthLabel,
  embeddingProviderName,
  formatLatency,
  providerName,
  ragConfigSourceLabel,
  roleAssignmentSummary,
  stackTemplateFromForm,
  stackTemplateLabel,
  statusTone,
} from "@/features/settings/models/settingsLabels";
import type { RagConfig, RagModelDiscoveryResult, RagModelDiscoveryStatus } from "@/types/api";
import { errorMessage, formatDateTime } from "@/lib/utils/format";

export function ModelsAndRolesPanel({
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

export type ModelsAndRolesPanelProps = {
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

export function ServiceDiscoveryStatus({ canFetchModels, discoveryError, loading, statuses }: ServiceDiscoveryStatusProps) {
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

export type ServiceDiscoveryStatusProps = {
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

export function StatusBadge({ children, tone }: { children: React.ReactNode; tone: "neutral" | "warning" }) {
  return <span className={tone === "warning" ? "sv-pill sv-pill-warning" : "sv-pill"}>{children}</span>;
}

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
