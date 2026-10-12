import { useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AtSign, KeyRound, LogOut, Pencil, ShieldCheck } from "lucide-react";

import { authApi } from "@/lib/api/contracts";
import { accountTypeLabel, clearanceLevelLabel } from "@/lib/auth/authz";
import { useToast } from "@/components/feedback/ToastProvider";
import { Fact } from "@/components/layout/Common";
import { Modal } from "@/components/layout/Modal";
import { PrudentiaBasicPage } from "@/components/layout/PrudentiaWorkspace";
import type { RouteId } from "@/routes/routes";
import type { User as AuthUser } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";

export function PrudentiaAccountPage({ currentUser, isLoggingOut, onAuthChanged, onLogout, onNavigate }: Props) {
  const { notify } = useToast();
  const userEmail = currentUser.email ?? "Unknown user";
  const userGroupPaths = currentUser.group_paths ?? [];
  const permissionVersion = currentUser.permission_version ?? "unknown";
  const [currentPassword, setCurrentPassword] = useState("");
  const [emailPassword, setEmailPassword] = useState("");
  const [emailDialogOpen, setEmailDialogOpen] = useState(false);
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false);
  const [newEmail, setNewEmail] = useState(currentUser.email);
  const [newPassword, setNewPassword] = useState("");
  const [confirmedPassword, setConfirmedPassword] = useState("");
  const passwordRequirementsId = useId();
  const passwordMismatchId = useId();
  const validation = passwordChangeValidation(currentPassword, newPassword, confirmedPassword);
  const passwordMutation = useMutation({
    mutationFn: () => authApi.changePassword({ current_password: currentPassword, new_password: newPassword }),
    onSuccess: () => {
      setCurrentPassword("");
      setNewPassword("");
      setConfirmedPassword("");
      setPasswordDialogOpen(false);
      onAuthChanged();
      notify({ title: "Password updated", description: "Use the new password on your next sign-in.", tone: "success" });
    },
    onError: (error) => notify({
      title: "Password change failed",
      description: errorMessage(error, "Password change failed."),
      tone: "error",
    }),
  });
  const emailMutation = useMutation({
    mutationFn: () => authApi.changeEmail({ current_password: emailPassword, new_email: newEmail.trim() }),
    onSuccess: (updated) => {
      setEmailPassword("");
      setNewEmail(updated.email);
      setEmailDialogOpen(false);
      onAuthChanged();
      notify({ title: "Email updated", description: "Use the new email the next time you sign in.", tone: "success" });
    },
    onError: (error) => notify({
      title: "Email change failed",
      description: errorMessage(error, "Unable to change email."),
      tone: "error",
    }),
  });

  return (
    <PrudentiaBasicPage
      activeRoute="account"
      onLogout={onLogout}
      onNavigate={onNavigate}
      title="Account Management"
      subtitle="Review your account, update sign-in details, and manage your session."
      user={currentUser}
    >
      <div className="max-w-3xl">
        <section className="sv-card p-5" data-cursor-glow>
          <div className="flex items-center gap-2">
            <ShieldCheck size={18} className="text-primary" />
            <h2 className="text-headline-sm">Account</h2>
          </div>
          <section className="mt-5" aria-labelledby="account-sign-in-title">
            <h3 id="account-sign-in-title" className="text-label-md font-bold text-on-surface">Sign-in</h3>
            <dl className="mt-2 divide-y divide-surface-border rounded-lg border border-surface-border">
              <div className="flex items-center justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <dt className="sv-metadata">Email</dt>
                  <dd className="mt-1 break-words text-body-md font-semibold text-on-surface">{userEmail}</dd>
                </div>
                <button
                  type="button"
                  className="Prudentia-icon-button shrink-0"
                  aria-label="Change email address"
                  title="Change email address"
                  onClick={() => {
                    setNewEmail(currentUser.email);
                    setEmailPassword("");
                    setEmailDialogOpen(true);
                  }}
                >
                  <Pencil size={15} />
                </button>
              </div>
              <div className="flex items-center justify-between gap-4 px-4 py-3">
                <div>
                  <dt className="sv-metadata">Password</dt>
                  <dd className="mt-1 text-body-md font-semibold text-on-surface">••••••••</dd>
                </div>
                <button
                  type="button"
                  className="Prudentia-icon-button shrink-0"
                  aria-label="Change password"
                  title="Change password"
                  onClick={() => {
                    setCurrentPassword("");
                    setNewPassword("");
                    setConfirmedPassword("");
                    setPasswordDialogOpen(true);
                  }}
                >
                  <Pencil size={15} />
                </button>
              </div>
            </dl>
          </section>
          <section className="mt-6 border-t border-surface-border pt-5" aria-labelledby="account-access-title">
            <h3 id="account-access-title" className="text-label-md font-bold text-on-surface">Access</h3>
            <dl className="mt-3 grid gap-4 sm:grid-cols-2">
              <Fact label="Role" value={accountTypeLabel(currentUser.account_type)} />
              <Fact label="Clearance" value={clearanceLevelLabel(currentUser.clearance_level)} />
              <Fact label="Knowledge Spaces" value={userGroupPaths.join(", ") || "No spaces"} />
              <Fact label="Permission version" value={`v${permissionVersion}`} />
            </dl>
          </section>
          <div className="mt-6 border-t border-surface-border pt-4">
            <button type="button" onClick={onLogout} disabled={isLoggingOut} className="sv-action-secondary">
              <LogOut size={16} />
              {isLoggingOut ? "Signing out" : "Sign out"}
            </button>
          </div>
        </section>
      </div>
      <Modal
        description="Confirm your current password to use the new email for future sign-ins. Other signed-in sessions will be ended."
        icon={<AtSign size={18} />}
        onClose={() => {
          if (!emailMutation.isPending) setEmailDialogOpen(false);
        }}
        open={emailDialogOpen}
        size="sm"
        title="Change email address"
      >
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            emailMutation.mutate();
          }}
        >
          <div className="rounded-lg border border-surface-border bg-surface-container-low px-3 py-2">
            <p className="sv-metadata">Current email</p>
            <p className="mt-1 break-words text-body-md font-semibold text-on-surface">{userEmail}</p>
          </div>
          <label className="sv-field">
            <span className="sv-label">New email</span>
            <input type="email" autoComplete="email" required value={newEmail} onChange={(event) => setNewEmail(event.target.value)} className="sv-input" />
          </label>
          <label className="sv-field">
            <span className="sv-label">Current password</span>
            <input type="password" autoComplete="current-password" required value={emailPassword} onChange={(event) => setEmailPassword(event.target.value)} className="sv-input" />
          </label>
          <div className="flex justify-end gap-2 border-t border-surface-border pt-4">
            <button type="button" disabled={emailMutation.isPending} onClick={() => setEmailDialogOpen(false)} className="sv-action-secondary">Cancel</button>
            <button type="submit" disabled={!newEmail.trim() || !emailPassword || emailMutation.isPending} className="sv-action-primary">
              {emailMutation.isPending ? "Updating" : "Save email"}
            </button>
          </div>
        </form>
      </Modal>
      <Modal
        description="Enter your current password, then choose and confirm a new one."
        icon={<KeyRound size={18} />}
        onClose={() => {
          if (!passwordMutation.isPending) setPasswordDialogOpen(false);
        }}
        open={passwordDialogOpen}
        size="sm"
        title="Change password"
      >
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            passwordMutation.mutate();
          }}
        >
          <label className="sv-field">
            <span className="sv-label">Current password</span>
            <input type="password" autoComplete="current-password" required value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} className="sv-input" />
          </label>
          <label className="sv-field">
            <span className="sv-label">New password</span>
            <input
              type="password"
              autoComplete="new-password"
              aria-describedby={passwordRequirementsId}
              minLength={8}
              required
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              className="sv-input"
            />
          </label>
          <div id={passwordRequirementsId} className="account-password-requirements">
            <p className="font-semibold text-on-surface">Password requirements</p>
            <p className="mt-1">Use at least 8 characters, then enter the same password again below.</p>
          </div>
          <label className="sv-field">
            <span className="sv-label">Confirm new password</span>
            <input
              type="password"
              autoComplete="new-password"
              aria-describedby={validation.showMismatch ? passwordMismatchId : passwordRequirementsId}
              aria-invalid={validation.showMismatch}
              required
              value={confirmedPassword}
              onChange={(event) => setConfirmedPassword(event.target.value)}
              className="sv-input"
            />
            {validation.showMismatch ? (
              <small id={passwordMismatchId} className="text-error-red" role="alert">
                The new passwords do not match.
              </small>
            ) : null}
          </label>
          <div className="flex justify-end gap-2 border-t border-surface-border pt-4">
            <button type="button" disabled={passwordMutation.isPending} onClick={() => setPasswordDialogOpen(false)} className="sv-action-secondary">Cancel</button>
            <button type="submit" disabled={!validation.canSubmit || passwordMutation.isPending} className="sv-action-primary">
              {passwordMutation.isPending ? "Updating" : "Save password"}
            </button>
          </div>
        </form>
      </Modal>
    </PrudentiaBasicPage>
  );
}

export function passwordChangeValidation(currentPassword: string, newPassword: string, confirmedPassword: string) {
  const showMismatch = confirmedPassword.length > 0 && newPassword !== confirmedPassword;
  return {
    canSubmit: currentPassword.length > 0 && newPassword.length >= 8 && newPassword === confirmedPassword,
    showMismatch,
  };
}

type Props = {
  currentUser: AuthUser;
  isLoggingOut: boolean;
  onAuthChanged: () => void;
  onLogout: () => void;
  onNavigate: (route: RouteId) => void;
};
