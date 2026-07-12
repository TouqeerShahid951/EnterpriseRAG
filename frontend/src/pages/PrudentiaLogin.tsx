import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { Eye, EyeOff, ShieldCheck } from "lucide-react";

import { authApi } from "../api/contracts";
import { PrudentiaWordmark } from "../components/brand/PrudentiaBrand";
import { InlineMessage } from "../components/layout/Common";
import type { User as AuthUser } from "../types/api";
import { errorMessage } from "../utils/format";

export function PrudentiaLogin({ onAuthChanged, sessionExpired = false }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const loginMutation = useMutation({
    mutationFn: () => authApi.login({ email: email.trim(), password }),
    onSuccess: (response) => onAuthChanged(response.user),
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    loginMutation.mutate();
  }

  return (
    <div className="Prudentia-page flex min-h-screen items-center justify-center p-4 text-on-background antialiased">
      <main className="Prudentia-auth-card w-full max-w-xl overflow-hidden rounded-lg border border-surface-border bg-surface-card shadow-2xl shadow-black/20">
        <section className="p-6 sm:p-8">
          <div className="mb-8">
            <PrudentiaWordmark className="Prudentia-login-wordmark" />
            <p className="sv-eyebrow">Secure enterprise workspace</p>
            <h1 className="mt-2 text-headline-md text-on-surface">Sign in to Prudentia</h1>
            <p className="mt-2 text-body-md text-on-surface-variant">Use your organization credentials to continue.</p>
          </div>
          {sessionExpired ? (
            <div className="mb-4">
              <InlineMessage tone="warning">
                Your session expired after inactivity. Sign in again to continue where you left off.
              </InlineMessage>
            </div>
          ) : null}
          <form onSubmit={handleSubmit} className="space-y-4">
            <label className="sv-field">
              <span className="sv-label">Email Address</span>
              <input autoComplete="username" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} className="sv-input" />
            </label>
            <label className="sv-field">
              <span className="sv-label">Password</span>
              <span className="sv-password-field">
                <input
                  autoComplete="current-password"
                  type={showPassword ? "text" : "password"}
                  required
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className="sv-input text-code-sm"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((visible) => !visible)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                >
                  {showPassword ? <EyeOff size={17} aria-hidden="true" /> : <Eye size={17} aria-hidden="true" />}
                </button>
              </span>
            </label>
            <button type="submit" disabled={loginMutation.isPending || !email.trim() || !password} className="sv-action-primary w-full" aria-busy={loginMutation.isPending}>
              {loginMutation.isPending ? "Signing in" : "Sign in"}
            </button>
          </form>
          {loginMutation.isError ? <InlineMessage tone="error">{errorMessage(loginMutation.error, "Sign in failed.")}</InlineMessage> : null}
          <div className="Prudentia-login-assurance mt-8 border-t border-surface-border pt-4">
            <ShieldCheck size={16} aria-hidden="true" />
            <p>Access follows your assigned role and Knowledge Spaces.</p>
          </div>
        </section>
      </main>
    </div>
  );
}

type Props = {
  onAuthChanged: (user: AuthUser) => void;
  sessionExpired?: boolean;
};
