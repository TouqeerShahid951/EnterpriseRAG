import { ChevronDown } from "lucide-react";

import type { RagModelDiscoveryStatus } from "@/types/api";
import {
  type EmbeddingProvider,
  type LanguageRole,
  type RagConfigFormState,
  type RuntimeProvider,
  embeddingRuntimeProvider,
  languageRoleModel,
  languageRoleProvider,
  modelOptionsFromDiscovery,
  withEmbeddingProvider,
  withLanguageRoleModel,
  withLanguageRoleProvider,
} from "@/features/settings/models/ragConfigForm";
import {
  endpointLabel,
  modelPlaceholderForStatus,
  roleModelInheritance,
  statusTone,
} from "@/features/settings/models/settingsLabels";
import { EndpointEditor } from "@/features/settings/components/RuntimeSettingsFields";

function ModelSelect({ ariaLabel, disabled, emptyLabel, models, onChange, placeholder, value }: ModelSelectProps) {
  const hasValue = value.trim().length > 0;
  const hasFetchedValue = models.includes(value);

  return (
    <select aria-label={ariaLabel} value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} className="sv-select">
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
  ariaLabel: string;
  value: string;
  models: string[];
  placeholder: string;
  disabled: boolean;
  emptyLabel?: string;
  onChange: (value: string) => void;
};

export function InferenceRoleMatrix({
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
    <section aria-labelledby="inference-role-matrix-title">
      <div className="mb-3 max-w-3xl">
        <h3 id="inference-role-matrix-title" className="text-title-md">Inference role assignments</h3>
        <p className="mt-1 text-body-md text-secondary">
          Set the provider and model for each role. Open an endpoint only when that role needs a different service.
        </p>
      </div>
      <div className="overflow-hidden rounded border border-surface-border">
        <div className="border-b border-surface-border bg-surface-container-low px-4 py-2 text-label-md font-bold uppercase tracking-wide text-secondary">
          Language roles
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
        </div>
        <div className="border-y border-surface-border bg-surface-container-low px-4 py-2 text-label-md font-bold uppercase tracking-wide text-secondary">
          Retrieval pipeline
        </div>
        <div className="divide-y divide-surface-border">
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
      </div>
    </section>
  );
}

export type InferenceRoleMatrixProps = {
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
    <article className="grid gap-4 p-4 lg:grid-cols-[minmax(10rem,0.7fr)_minmax(0,1.7fr)] lg:items-start">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-body-md font-bold text-on-surface">{title}</h4>
          <span className="rounded-full bg-secondary-container px-2 py-0.5 text-label-sm font-bold text-on-secondary-container">
            {roleModelInheritance(role, modelValue)}
          </span>
        </div>
        <div className="mt-1 text-body-md text-secondary">{description}</div>
      </div>
      <div className="grid min-w-0 gap-3 sm:grid-cols-2">
        <RuntimeProviderSelect
          ariaLabel={`${title} provider`}
          value={provider}
          onChange={(nextProvider) => onChange(withLanguageRoleProvider(form, role, nextProvider))}
        />
        <label className="sv-field">
          <span className="sv-label">Model</span>
          <ModelSelect
            ariaLabel={`${title} model`}
            value={modelValue}
            onChange={(model) => onChange(withLanguageRoleModel(form, role, model))}
            models={modelOptions}
            placeholder={modelPlaceholder}
            emptyLabel={emptyLabel}
            disabled={modelSelectDisabled}
          />
          {modelStatus && status !== "ok" ? (
            <span className={`text-body-md ${status === "error" ? "text-error-red" : "text-warning-amber"}`}>
              {modelStatus.message}
            </span>
          ) : null}
        </label>
        <EndpointDisclosure form={form} provider={provider} role={role} onChange={onChange} />
      </div>
    </article>
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
    <article className="grid gap-4 p-4 lg:grid-cols-[minmax(10rem,0.7fr)_minmax(0,1.7fr)] lg:items-start">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-body-md font-bold text-on-surface">Embeddings</h4>
          <span className="rounded-full bg-secondary-container px-2 py-0.5 text-label-sm font-bold text-on-secondary-container">
            Required model
          </span>
        </div>
        <div className="mt-1 text-body-md text-secondary">Vectors for chunks and queries. Changing this requires reindexing documents.</div>
      </div>
      <div className="grid min-w-0 gap-3 sm:grid-cols-2">
        <EmbeddingProviderSelect
          value={form.embedding_provider}
          onChange={(embeddingProvider) => onChange(withEmbeddingProvider(form, embeddingProvider))}
        />
        <label className="sv-field">
          <span className="sv-label">Model</span>
          <ModelSelect
            ariaLabel="Embedding model"
            value={form.embed_model}
            onChange={(embed_model) => onChange({ ...form, embed_model })}
            models={modelOptions}
            placeholder={modelPlaceholder}
            disabled={modelSelectDisabled}
          />
          {modelStatus && status !== "ok" ? (
            <span className={`text-body-md ${status === "error" ? "text-error-red" : "text-warning-amber"}`}>
              {modelStatus.message}
            </span>
          ) : null}
        </label>
        {form.embedding_provider === "fastembed" ? (
          <StaticField label="Endpoint" wide>Local model cache, no network service</StaticField>
        ) : (
          <EndpointDisclosure form={form} provider={provider} role="embedding" onChange={onChange} />
        )}
      </div>
    </article>
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
    <article className="grid gap-4 p-4 lg:grid-cols-[minmax(10rem,0.7fr)_minmax(0,1.7fr)] lg:items-start">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-body-md font-bold text-on-surface">Reranker</h4>
          <span className="rounded-full bg-secondary-container px-2 py-0.5 text-label-sm font-bold text-on-secondary-container">
            Required model
          </span>
        </div>
        <div className="mt-1 text-body-md text-secondary">Reorders retrieved chunks before source selection and synthesis.</div>
      </div>
      <div className="grid min-w-0 gap-3 sm:grid-cols-2">
        <StaticField label="Provider">Local catalog</StaticField>
        <label className="sv-field">
          <span className="sv-label">Model</span>
          <ModelSelect
            ariaLabel="Reranker model"
            value={form.reranker_model}
            onChange={(reranker_model) => onChange({ ...form, reranker_model })}
            models={modelOptions}
            placeholder={modelPlaceholder}
            disabled={modelSelectDisabled}
          />
        </label>
        <StaticField label="Endpoint" wide>Runs locally, no inference endpoint</StaticField>
      </div>
    </article>
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
      <span className="sv-label">Provider</span>
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
      <span className="sv-label">Provider</span>
      <select aria-label="Embedding provider" value={value} onChange={(event) => onChange(event.target.value as EmbeddingProvider)} className="sv-select">
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

function EndpointDisclosure({ form, onChange, provider, role }: EndpointDisclosureProps) {
  return (
    <details className="group overflow-hidden rounded border border-surface-border bg-surface-container-low sm:col-span-2">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-3 px-3 py-2 text-left [&::-webkit-details-marker]:hidden">
        <span className="sv-label shrink-0">Endpoint</span>
        <span className="min-w-0 flex-1 truncate text-body-md text-on-surface">{endpointLabel(form, role, provider)}</span>
        <span className="text-label-sm font-bold text-primary">Configure</span>
        <ChevronDown aria-hidden="true" size={16} className="shrink-0 text-secondary transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-surface-border p-3">
        <EndpointEditor form={form} provider={provider} role={role} onChange={onChange} />
      </div>
    </details>
  );
}

type EndpointDisclosureProps = {
  form: RagConfigFormState;
  provider: RuntimeProvider;
  role: LanguageRole | "embedding";
  onChange: (value: RagConfigFormState) => void;
};

function StaticField({ children, label, wide = false }: { children: string; label: string; wide?: boolean }) {
  return (
    <div className={`sv-field ${wide ? "sm:col-span-2" : ""}`}>
      <span className="sv-label">{label}</span>
      <div className="flex min-h-11 items-center rounded border border-surface-border bg-surface-container-low px-3 py-2 text-body-md text-secondary">
        {children}
      </div>
    </div>
  );
}
