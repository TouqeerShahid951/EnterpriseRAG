import type { Dispatch, FormEvent, SetStateAction } from "react";
import { Check, Copy, Eye, EyeOff, KeyRound, Plus, RefreshCw } from "lucide-react";

import { EmptyPanel, InlineMessage } from "@/components/layout/Common";
import { accountTypeLabel, clearanceLevelDescription, clearanceLevelLabel, roleDescription } from "@/lib/auth/authz";
import type { AccountType, ClearanceLevel } from "@/types/api";
import type { GroupOption } from "@/lib/utils/groups";
import { errorMessage } from "@/lib/utils/format";
import { type CopyState, type UserDraft, isGlobalAccountType } from "@/features/access/utils/accessUserUtils";

export function UserPanel({
  clearanceLevels,
  copyState,
  createdUserEmail,
  draft,
  accountTypes,
  groupOptions,
  isCreate,
  isPending,
  mutationError,
  onChange,
  onClose,
  onCopyPassword,
  onCreateAnother,
  onInitialPasswordChange,
  onRegeneratePassword,
  onSpaceToggle,
  onSubmit,
  onTogglePassword,
  showInitialPassword,
}: UserPanelProps) {
  const createComplete = isCreate && Boolean(createdUserEmail);
  const canSubmit = draft.name.trim().length > 0 && (!isCreate || (draft.email.trim().length > 0 && draft.initialPassword.length >= 8));

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {isCreate ? (
        <TextField
          autoComplete="off"
          disabled={createComplete || isPending}
          helper="Used for sign-in and audit attribution."
          label="Email"
          onChange={(value) => onChange((current) => ({ ...current, email: value }))}
          required
          type="email"
          value={draft.email}
        />
      ) : (
        <ReadOnlyField label="Email" value={draft.email} />
      )}

      <TextField
        autoComplete="off"
        disabled={createComplete || isPending}
        helper="Shown in admin lists and account dialogs."
        label="Name"
        onChange={(value) => onChange((current) => ({ ...current, name: value }))}
        required
        value={draft.name}
      />

      <AccountTypePicker
        accountTypes={accountTypes}
        disabled={createComplete || isPending}
        value={draft.accountType}
        onChange={(accountType) => onChange((current) => ({
          ...current,
          accountType,
          clearanceLevel: isGlobalAccountType(accountType) ? "COSMIC_TOP_SECRET" : current.clearanceLevel,
        }))}
      />

      <ClearanceLevelPicker
        clearanceLevels={clearanceLevels}
        disabled={createComplete || isPending || isGlobalAccountType(draft.accountType)}
        lockedByGlobalRole={isGlobalAccountType(draft.accountType)}
        value={draft.clearanceLevel}
        onChange={(clearanceLevel) => onChange((current) => ({ ...current, clearanceLevel }))}
      />

      {isCreate ? (
        <div className="sv-field">
          <span className="sv-label">Initial password</span>
          <div className="flex gap-2">
            <div className="relative min-w-0 flex-1">
              <KeyRound size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
              <input
                aria-label="Initial password"
                autoComplete="new-password"
                className="sv-input sv-input-with-leading-icon text-code-sm"
                disabled={createComplete || isPending}
                minLength={8}
                onChange={(event) => onInitialPasswordChange(event.target.value)}
                required
                type={showInitialPassword ? "text" : "password"}
                value={draft.initialPassword}
              />
            </div>
            <button type="button" onClick={onTogglePassword} className="sv-action-secondary min-h-11 px-3" aria-label={showInitialPassword ? "Hide initial password" : "Show initial password"}>
              {showInitialPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={onCopyPassword} className="sv-action-secondary min-h-9 px-3">
              {copyState === "copied" ? <Check size={15} /> : <Copy size={15} />} {copyState === "copied" ? "Copied" : "Copy"}
            </button>
            <button type="button" onClick={onRegeneratePassword} disabled={createComplete || isPending} className="sv-action-secondary min-h-9 px-3 disabled:cursor-not-allowed disabled:opacity-60">
              <RefreshCw size={15} /> Regenerate
            </button>
          </div>
          {copyState === "failed" ? <small className="text-error-red">Clipboard access is unavailable. Reveal and copy the password manually.</small> : null}
          <small className="text-secondary">Share once with the new user; they can change it after sign-in.</small>
        </div>
      ) : null}

      <label className="flex items-center gap-3 rounded-lg border border-surface-border bg-surface-container-low p-3 text-body-md text-on-surface">
        <input
          type="checkbox"
          checked={draft.isActive}
          disabled={createComplete || isPending}
          onChange={(event) => onChange((current) => ({ ...current, isActive: event.target.checked }))}
        />
        Active account
      </label>
      <small className="block text-secondary">Disable to block sign-in without removing memberships.</small>

      <SpacePicker disabled={createComplete || isPending} groupOptions={groupOptions} onToggle={onSpaceToggle} selectedPaths={draft.groupPaths} />

      {mutationError ? <InlineMessage tone="error">{errorMessage(mutationError, isCreate ? "Unable to create user." : "Unable to update user.")}</InlineMessage> : null}
      {createdUserEmail ? <InlineMessage tone="success">User {createdUserEmail} was created. Copy the initial password before leaving this dialog.</InlineMessage> : null}

      <div className="flex flex-wrap justify-end gap-2 border-t border-surface-border pt-4">
        {createdUserEmail ? (
          <>
            <button type="button" onClick={onCreateAnother} className="sv-action-secondary">
              <Plus size={16} /> Create another
            </button>
            <button type="button" onClick={onClose} className="sv-action-primary">
              Done
            </button>
          </>
        ) : (
          <>
            <button type="button" onClick={onClose} className="sv-action-secondary" disabled={isPending}>
              Cancel
            </button>
            <button type="submit" disabled={!canSubmit || isPending} className="sv-action-primary disabled:cursor-not-allowed disabled:opacity-60">
              {isPending ? "Saving" : isCreate ? "Create user" : "Save user"}
            </button>
          </>
        )}
      </div>
    </form>
  );
}

function SpacePicker({ disabled, groupOptions, onToggle, selectedPaths }: SpacePickerProps) {
  if (groupOptions.length === 0) return <EmptyPanel>No Knowledge Spaces are available for assignment.</EmptyPanel>;

  return (
    <fieldset className="space-y-2">
      <legend className="sv-label">Knowledge Space memberships</legend>
      <p className="text-body-md text-secondary">Selected spaces control retrieval scope and upload access.</p>
      <div className="max-h-72 overflow-auto rounded-lg border border-surface-border bg-surface-container-low p-2">
        {groupOptions.map((group) => (
          <label key={group.path} className="flex items-start gap-3 rounded-md p-2 text-body-md text-on-surface hover:bg-surface-container-high" style={{ paddingLeft: `${0.5 + group.depth * 1}rem` }}>
            <input type="checkbox" checked={selectedPaths.includes(group.path)} disabled={disabled} onChange={(event) => onToggle(group.path, event.target.checked)} />
            <span className="min-w-0">
              <span className="block font-semibold">{group.name}</span>
              <small className="block break-all text-secondary">{group.path}</small>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function AccountTypePicker({ accountTypes, disabled, onChange, value }: AccountTypePickerProps) {
  return (
    <label className="sv-field" htmlFor="account-type">
      <span className="sv-label">Account type</span>
      <select
        className="sv-select"
        disabled={disabled}
        id="account-type"
        onChange={(event) => onChange(event.target.value as AccountType)}
        value={value}
      >
        {accountTypes.map((accountType) => (
          <option key={accountType} value={accountType}>
            {accountTypeLabel(accountType)}
          </option>
        ))}
      </select>
      <small className="text-secondary">{roleDescription(value)}</small>
    </label>
  );
}

function ClearanceLevelPicker({ clearanceLevels, disabled, lockedByGlobalRole, onChange, value }: ClearanceLevelPickerProps) {
  return (
    <label className="sv-field" htmlFor="clearance-level">
      <span className="sv-label">Clearance level</span>
      <select
        className="sv-select"
        disabled={disabled}
        id="clearance-level"
        onChange={(event) => onChange(event.target.value as ClearanceLevel)}
        value={value}
      >
        {clearanceLevels.map((clearanceLevel) => (
          <option key={clearanceLevel} value={clearanceLevel}>
            {clearanceLevelLabel(clearanceLevel)}
          </option>
        ))}
      </select>
      <small className="text-secondary">
        {lockedByGlobalRole
          ? "Global administrator accounts are always Top Secret."
          : clearanceLevelDescription(value)}
      </small>
    </label>
  );
}

function TextField({ autoComplete, disabled, helper, label, onChange, required, type = "text", value }: TextFieldProps) {
  const id = label.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return (
    <label className="sv-field" htmlFor={id}>
      <span className="sv-label">{label}</span>
      <input autoComplete={autoComplete} className="sv-input" disabled={disabled} id={id} onChange={(event) => onChange(event.target.value)} required={required} type={type} value={value} />
      {helper ? <small className="text-secondary">{helper}</small> : null}
    </label>
  );
}

export function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="sv-metadata">{label}</span>
      <p className="mt-1 break-all rounded-lg border border-surface-border bg-surface-container-low p-3 text-body-md font-semibold text-on-surface">{value}</p>
    </div>
  );
}

export type UserPanelProps = {
  accountTypes: AccountType[];
  clearanceLevels: ClearanceLevel[];
  copyState: CopyState;
  createdUserEmail: string | null;
  draft: UserDraft;
  groupOptions: GroupOption[];
  isCreate: boolean;
  isPending: boolean;
  mutationError: unknown;
  onChange: Dispatch<SetStateAction<UserDraft>>;
  onClose: () => void;
  onCopyPassword: () => void;
  onCreateAnother: () => void;
  onInitialPasswordChange: (initialPassword: string) => void;
  onRegeneratePassword: () => void;
  onSpaceToggle: (groupPath: string, checked: boolean) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onTogglePassword: () => void;
  showInitialPassword: boolean;
};

type TextFieldProps = {
  autoComplete?: string;
  disabled?: boolean;
  helper?: string;
  label: string;
  onChange: (value: string) => void;
  required?: boolean;
  type?: string;
  value: string;
};

type SpacePickerProps = {
  disabled?: boolean;
  groupOptions: GroupOption[];
  onToggle: (groupPath: string, checked: boolean) => void;
  selectedPaths: string[];
};

type AccountTypePickerProps = {
  accountTypes: AccountType[];
  disabled?: boolean;
  onChange: (accountType: AccountType) => void;
  value: AccountType;
};

type ClearanceLevelPickerProps = {
  clearanceLevels: ClearanceLevel[];
  disabled?: boolean;
  lockedByGlobalRole: boolean;
  onChange: (clearanceLevel: ClearanceLevel) => void;
  value: ClearanceLevel;
};
