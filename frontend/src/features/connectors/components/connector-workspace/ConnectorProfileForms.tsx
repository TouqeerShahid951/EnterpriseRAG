import { useId, useState, type FormEvent } from "react";
import { Eye, EyeOff, KeyRound, Loader2, Save } from "lucide-react";

import { InlineMessage } from "@/components/layout/Common";
import type { ConnectorProfile } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";
import {
  connectorTypeLabel,
  defaultProfileDraftForType,
  profileTestDetail,
  type ConnectorProfileDraft,
} from "@/features/connectors/utils/connectorPanelUtils";

export function ConnectorProfilePanel({
  draft,
  error,
  isCreating,
  isLoading,
  mutationError,
  onChange,
  onProfileAction,
  onSubmit,
  pendingActionId,
  pendingActionType,
  profiles,
  showExisting = true,
}: ConnectorProfilePanelProps) {
  const passwordInputId = useId();
  const [showPassword, setShowPassword] = useState(false);
  const passwordToggleLabel = showPassword ? "Hide password" : "Show password";

  return (
    <div className="mb-5 rounded-lg border border-surface-border bg-surface-container-low p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="sv-label">Database connection</p>
          <p className="mt-1 text-body-md text-on-surface-variant">SQL Server and PostgreSQL credentials are encrypted at rest and redacted after save.</p>
        </div>
        {showExisting ? <span className="sv-pill">{profiles.length} connection{profiles.length === 1 ? "" : "s"}</span> : null}
      </div>
      <form
        onSubmit={onSubmit}
        className={`connector-profile-form ${showExisting ? "connector-profile-form-overview" : "connector-profile-form-compact"}`}
      >
        <label className="sv-field">
          <span className="sv-label">Type <span className="font-normal text-secondary">(required)</span></span>
          <select
            value={draft.connectorType}
            onChange={(event) => onChange(defaultProfileDraftForType(event.target.value as ConnectorProfileDraft["connectorType"]))}
            className="sv-select"
          >
            <option value="sql_server">SQL Server</option>
            <option value="postgres">PostgreSQL</option>
          </select>
        </label>
        <label className="sv-field">
          <span className="sv-label">Connection Name <span className="font-normal text-secondary">(required)</span></span>
          <input value={draft.name} onChange={(event) => onChange({ name: event.target.value })} placeholder={draft.connectorType === "postgres" ? "Postgres case read replica" : "CaseDB read replica"} className="sv-input" />
        </label>
        <label className="sv-field">
          <span className="sv-label">{draft.connectorType === "postgres" ? "Host" : "Server"} <span className="font-normal text-secondary">(required)</span></span>
          <input value={draft.server} onChange={(event) => onChange({ server: event.target.value })} placeholder={draft.connectorType === "postgres" ? "postgres.internal" : "sql01.internal"} className="sv-input" />
        </label>
        <label className="sv-field">
          <span className="sv-label">Port</span>
          <input value={draft.port} onChange={(event) => onChange({ port: event.target.value })} placeholder={draft.connectorType === "postgres" ? "5432" : "1433"} className="sv-input" />
        </label>
        <label className="sv-field">
          <span className="sv-label">Database <span className="font-normal text-secondary">(required)</span></span>
          <input value={draft.database} onChange={(event) => onChange({ database: event.target.value })} placeholder="CaseDB" className="sv-input" />
        </label>
        <label className="sv-field">
          <span className="sv-label">User <span className="font-normal text-secondary">(required)</span></span>
          <input value={draft.username} onChange={(event) => onChange({ username: event.target.value })} placeholder="readonly_user" className="sv-input" />
        </label>
        <div className="sv-field">
          <label htmlFor={passwordInputId} className="sv-label">Password <span className="font-normal text-secondary">(required)</span></label>
          <div className="flex gap-2">
            <input id={passwordInputId} autoComplete="off" type={showPassword ? "text" : "password"} value={draft.password} onChange={(event) => onChange({ password: event.target.value })} className="sv-input min-w-0 flex-1" />
            <button type="button" onClick={() => setShowPassword((value) => !value)} className="sv-action-secondary min-h-11 shrink-0 px-3" aria-label={passwordToggleLabel} aria-pressed={showPassword} title={passwordToggleLabel}>
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>
        <button type="submit" disabled={isCreating} className="connector-profile-save sv-action-secondary">
          {isCreating ? <Loader2 className="animate-spin" size={16} /> : <KeyRound size={16} />}
          Save Connection
        </button>
        <details className="connector-profile-advanced rounded-md border border-surface-border bg-surface px-3 py-2">
          <summary className="cursor-pointer text-label-md font-bold text-on-surface">Advanced connection settings</summary>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {draft.connectorType === "sql_server" ? (
              <>
                <label className="sv-field">
                  <span className="sv-label">SQL Server Driver</span>
                  <select value={draft.driver} onChange={(event) => onChange({ driver: event.target.value })} className="sv-select">
                    <option value="ODBC Driver 18 for SQL Server">ODBC Driver 18 for SQL Server (recommended)</option>
                    <option value="ODBC Driver 17 for SQL Server">ODBC Driver 17 for SQL Server</option>
                    <option value="custom">Custom driver name</option>
                  </select>
                  <small className="text-secondary">The deployment image includes Driver 18 by default.</small>
                </label>
                {draft.driver === "custom" ? (
                  <label className="sv-field">
                    <span className="sv-label">Custom Driver Name</span>
                    <input value={draft.customDriver} onChange={(event) => onChange({ customDriver: event.target.value })} placeholder="ODBC Driver 18 for SQL Server" className="sv-input" />
                  </label>
                ) : null}
              </>
            ) : (
              <label className="sv-field">
                <span className="sv-label">Connection SSL</span>
                <select value={draft.sslMode} onChange={(event) => onChange({ sslMode: event.target.value })} className="sv-select">
                  <option value="prefer">Prefer SSL (default)</option>
                  <option value="require">Require SSL</option>
                  <option value="disable">Disable SSL</option>
                  <option value="verify-ca">Verify certificate authority</option>
                  <option value="verify-full">Verify certificate and host</option>
                </select>
              </label>
            )}
          </div>
        </details>
      </form>
      {error ? <InlineMessage tone="warning">{error}</InlineMessage> : null}
      {mutationError ? <InlineMessage tone="error">{errorMessage(mutationError, "Unable to save database connection.")}</InlineMessage> : null}
      {showExisting && isLoading ? <p className="mt-3 text-body-md text-secondary">Loading database connections.</p> : null}
      {showExisting && profiles.length > 0 ? (
        <div className="mt-3 grid gap-2">
          {profiles.slice(0, 4).map((profile) => (
            <div key={profile.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-surface-border bg-surface px-3 py-2">
              <span className="min-w-0">
                <strong className="block truncate text-body-md text-on-surface">{profile.name}</strong>
                <small className="text-secondary">{connectorTypeLabel(profile.connector_type)}</small>
                <small className={profile.last_test_status === "failed" ? "block text-error-red" : "block text-secondary"}>{profileTestDetail(profile)}</small>
              </span>
              <span className="flex gap-2">
                <button type="button" disabled={pendingActionId === profile.id} onClick={() => onProfileAction("test", profile.id)} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                  {pendingActionId === profile.id && pendingActionType === "test" ? "Testing" : "Test"}
                </button>
                <button type="button" disabled={pendingActionId === profile.id} onClick={() => onProfileAction("introspect", profile.id)} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                  {pendingActionId === profile.id && pendingActionType === "introspect" ? "Reading" : "Read Schema"}
                </button>
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function ConnectorProfileEditor({ draft, error, isSaving, mutationError, onCancel, onChange, onSubmit, profile }: ConnectorProfileEditorProps) {
  const passwordInputId = useId();
  const [showPassword, setShowPassword] = useState(false);
  const passwordToggleLabel = showPassword ? "Hide replacement password" : "Show replacement password";

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="sv-label">Edit connection</p>
          <p className="mt-1 text-body-md text-on-surface-variant">
            Updating the connection affects future schema introspection and Live DB queries for this source.
          </p>
        </div>
        <span className="sv-pill">{connectorTypeLabel(profile.connector_type)}</span>
      </div>
      <div className="grid items-start gap-3 lg:grid-cols-2 xl:grid-cols-[0.8fr_1fr_1fr_0.7fr_1fr]">
        <label className="sv-field">
          <span className="sv-label">Type</span>
          <select
            value={draft.connectorType}
            onChange={(event) => onChange(defaultProfileDraftForType(event.target.value as ConnectorProfileDraft["connectorType"]))}
            className="sv-select"
          >
            <option value="sql_server">SQL Server</option>
            <option value="postgres">PostgreSQL</option>
          </select>
        </label>
        <label className="sv-field">
          <span className="sv-label">Connection Name</span>
          <input value={draft.name} onChange={(event) => onChange({ name: event.target.value })} className="sv-input" />
        </label>
        <label className="sv-field">
          <span className="sv-label">{draft.connectorType === "postgres" ? "Host" : "Server"}</span>
          <input value={draft.server} onChange={(event) => onChange({ server: event.target.value })} className="sv-input" />
        </label>
        <label className="sv-field">
          <span className="sv-label">Port</span>
          <input value={draft.port} onChange={(event) => onChange({ port: event.target.value })} className="sv-input" />
        </label>
        <label className="sv-field">
          <span className="sv-label">Database</span>
          <input value={draft.database} onChange={(event) => onChange({ database: event.target.value })} className="sv-input" />
        </label>
      </div>
      <details className="rounded-md border border-surface-border bg-surface-container-low px-3 py-2">
        <summary className="cursor-pointer text-label-md font-bold text-on-surface">Credentials and advanced settings</summary>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <label className="sv-field">
            <span className="sv-label">Replacement User</span>
            <input value={draft.username} onChange={(event) => onChange({ username: event.target.value })} placeholder="Leave blank to keep current user" className="sv-input" />
          </label>
          <div className="sv-field">
            <label htmlFor={passwordInputId} className="sv-label">Replacement Password</label>
            <div className="flex gap-2">
              <input id={passwordInputId} autoComplete="off" type={showPassword ? "text" : "password"} value={draft.password} onChange={(event) => onChange({ password: event.target.value })} placeholder="Leave blank to keep current password" className="sv-input min-w-0 flex-1" />
              <button type="button" onClick={() => setShowPassword((value) => !value)} className="sv-action-secondary min-h-11 shrink-0 px-3" aria-label={passwordToggleLabel} aria-pressed={showPassword} title={passwordToggleLabel}>
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
          {draft.connectorType === "sql_server" ? (
            <>
              <label className="sv-field">
                <span className="sv-label">SQL Server Driver</span>
                <select value={draft.driver} onChange={(event) => onChange({ driver: event.target.value })} className="sv-select">
                  <option value="ODBC Driver 18 for SQL Server">ODBC Driver 18 for SQL Server (recommended)</option>
                  <option value="ODBC Driver 17 for SQL Server">ODBC Driver 17 for SQL Server</option>
                  <option value="custom">Custom driver name</option>
                </select>
              </label>
              {draft.driver === "custom" ? (
                <label className="sv-field">
                  <span className="sv-label">Custom Driver Name</span>
                  <input value={draft.customDriver} onChange={(event) => onChange({ customDriver: event.target.value })} className="sv-input" />
                </label>
              ) : null}
            </>
          ) : (
            <label className="sv-field">
              <span className="sv-label">Connection SSL</span>
              <select value={draft.sslMode} onChange={(event) => onChange({ sslMode: event.target.value })} className="sv-select">
                <option value="prefer">Prefer SSL (default)</option>
                <option value="require">Require SSL</option>
                <option value="disable">Disable SSL</option>
                <option value="verify-ca">Verify certificate authority</option>
                <option value="verify-full">Verify certificate and host</option>
              </select>
            </label>
          )}
        </div>
      </details>
      {error ? <InlineMessage tone="warning">{error}</InlineMessage> : null}
      {mutationError ? <InlineMessage tone="error">{errorMessage(mutationError, "Unable to update database connection.")}</InlineMessage> : null}
      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        <button type="button" onClick={onCancel} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-label-md font-bold text-on-surface hover:border-primary">
          Cancel
        </button>
        <button type="submit" disabled={isSaving} className="sv-action-primary">
          {isSaving ? <Loader2 className="animate-spin" size={16} /> : <Save size={16} />}
          Save Changes
        </button>
      </div>
    </form>
  );
}

export type ConnectorProfilePanelProps = {
  draft: ConnectorProfileDraft;
  error: string | null;
  isCreating: boolean;
  isLoading: boolean;
  mutationError: unknown;
  onChange: (patch: Partial<ConnectorProfileDraft>) => void;
  onProfileAction: (action: "test" | "introspect", id: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  pendingActionId: string | null;
  pendingActionType: "test" | "introspect" | null;
  profiles: ConnectorProfile[];
  showExisting?: boolean;
};

export type ConnectorProfileEditorProps = {
  draft: ConnectorProfileDraft;
  error: string | null;
  isSaving: boolean;
  mutationError: unknown;
  onCancel: () => void;
  onChange: (patch: Partial<ConnectorProfileDraft>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  profile: ConnectorProfile;
};
