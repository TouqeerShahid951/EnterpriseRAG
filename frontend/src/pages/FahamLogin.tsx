import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";

import { authApi } from "../api/contracts";
import { FahamWordmark } from "../components/brand/FahamBrand";
import { InlineMessage } from "../components/layout/Common";
import { errorMessage } from "../utils/format";

export function FahamLogin({ onAuthChanged }: { onAuthChanged: () => void }) {
  const [email, setEmail] = useState("admin@faham.ai");
  const [password, setPassword] = useState("");
  const loginMutation = useMutation({
    mutationFn: () => authApi.login({ email: email.trim(), password }),
    onSuccess: onAuthChanged,
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    loginMutation.mutate();
  }

  return (
    <div className="faham-page flex min-h-screen items-center justify-center p-4 text-on-background antialiased">
      <main className="w-full max-w-xl overflow-hidden rounded-lg border border-surface-border bg-surface-card shadow-2xl shadow-black/20">
        <section className="p-6 sm:p-8">
          <div className="mb-8">
            <FahamWordmark className="faham-login-wordmark" />
            <p className="sv-eyebrow">Enterprise RAG Workspace</p>
            <h2 className="mt-2 text-headline-md text-on-surface">Secure Login</h2>
            <p className="mt-2 text-body-md text-on-surface-variant">Enter your enterprise credentials to open the Faham AI workspace.</p>
          </div>
          <form onSubmit={handleSubmit} className="space-y-4">
            <label className="sv-field">
              <span className="sv-label">Email Address</span>
              <input autoComplete="username" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} className="sv-input" />
            </label>
            <label className="sv-field">
              <span className="sv-label">Password</span>
              <input autoComplete="current-password" type="password" required value={password} onChange={(event) => setPassword(event.target.value)} className="sv-input text-code-sm" />
            </label>
            <button type="submit" disabled={loginMutation.isPending || !email.trim() || !password} className="sv-action-primary w-full">
              {loginMutation.isPending ? "Authenticating" : "Authenticate Session"}
            </button>
          </form>
          {loginMutation.isError ? <InlineMessage tone="error">{errorMessage(loginMutation.error, "Sign in failed.")}</InlineMessage> : null}
          <div className="mt-8 border-t border-surface-border pt-4">
            <p className="text-[12px] font-semibold text-secondary">Secured by Enterprise JWT and CSRF-aware API calls.</p>
          </div>
        </section>
      </main>
    </div>
  );
}
