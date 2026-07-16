import {
  LANGUAGE_ROLES,
  LOCAL_INFERENCE_HOST,
  type EndpointRole,
  type RagConfigFormState,
  type RuntimeProvider,
  defaultPortForRole,
  endpointsFromForm,
  languageRoleProvider,
} from "@/features/settings/models/ragConfigForm";

export function EndpointEditor({ form, provider, role, onChange }: EndpointFieldsProps) {
  return <EndpointFields form={form} provider={provider} role={role} onChange={onChange} />;
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
        <span className="sv-label">Host</span>
        <input
          aria-label={`${role} endpoint host`}
          value={hostValue}
          onChange={(event) => updateHost(event.target.value)}
          placeholder={hostPlaceholder}
          className="sv-input"
        />
      </label>
      <label className="sv-field">
        <span className="sv-label">Port</span>
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

export type EndpointFieldsProps = {
  form: RagConfigFormState;
  provider: RuntimeProvider;
  role: EndpointRole;
  onChange: (value: RagConfigFormState) => void;
};

export function RuntimeAdvancedSettings({ form, onChange }: { form: RagConfigFormState; onChange: (value: RagConfigFormState) => void }) {
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
