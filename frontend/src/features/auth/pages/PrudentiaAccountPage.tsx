import { useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { KeyRound, LogOut, ShieldCheck } from "lucide-react";

import { authApi } from "@/lib/api/contracts";
import { accountTypeLabel, clearanceLevelLabel } from "@/lib/auth/authz";
import { useToast } from "@/components/feedback/ToastProvider";
import { Fact } from "@/components/layout/Common";
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
      onAuthChanged();
      notify({ title: "Password updated", description: "Use the new password on your next sign-in.", tone: "success" });
    },
    onError: (error) => notify({
      title: "Password change failed",
      description: errorMessage(error, "Password change failed."),
      tone: "error",
    }),
  });

  return (
    <PrudentiaBasicPage
      activeRoute="account"
      onLogout={onLogout}
      onNavigate={onNavigate}
      title="Account Management"
      subtitle="Session details, password rotation, and sign-out controls for your own account."
      user={currentUser}
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="sv-card p-5" data-cursor-glow>
          <div className="flex items-center gap-2">
            <ShieldCheck size={18} className="text-primary" />
            <h2 className="text-headline-sm">Session</h2>
          </div>
          <dl className="mt-4 space-y-3">
            <Fact label="Email" value={userEmail} />
            <Fact label="Role" value={accountTypeLabel(currentUser.account_type)} />
            <Fact label="Clearance" value={clearanceLevelLabel(currentUser.clearance_level)} />
            <Fact label="Knowledge Spaces" value={userGroupPaths.join(", ") || "No spaces"} />
            <Fact label="Permission version" value={`v${permissionVersion}`} />
          </dl>
          <button type="button" onClick={onLogout} disabled={isLoggingOut} className="sv-action-secondary mt-5">
            <LogOut size={16} />
            {isLoggingOut ? "Signing out" : "Sign out"}
          </button>
        </section>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            passwordMutation.mutate();
          }}
          className="sv-card p-5"
          data-cursor-glow
        >
          <div className="flex items-center gap-2">
            <KeyRound size={18} className="text-primary" />
            <h2 className="text-headline-sm">Change Password</h2>
          </div>
          <div className="mt-4 space-y-3">
            <label className="sv-field">
              <span className="sv-label">Current password</span>
              <input
                type="password"
                autoComplete="current-password"
                required
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                className="sv-input"
              />
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
            <button type="submit" disabled={!validation.canSubmit || passwordMutation.isPending} className="sv-action-primary">
              {passwordMutation.isPending ? "Updating" : "Change password"}
            </button>
          </div>
        </form>
      </div>
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
