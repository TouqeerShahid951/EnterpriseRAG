import type { ReactNode } from "react";

import { FahamWordmark } from "../brand/FahamBrand";

export function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="sv-metadata">{label}</dt>
      <dd className="mt-1 break-words text-body-md font-semibold text-on-surface">{value}</dd>
    </div>
  );
}

export function EmptyPanel({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-surface-border bg-surface-container-low p-4 text-body-md text-secondary">{children}</div>;
}

export function InlineMessage({ children, tone }: { children: ReactNode; tone: "error" | "success" | "warning" }) {
  const className = tone === "error" ? "faham-error-banner" : tone === "success" ? "faham-success-banner" : "faham-planned-banner";
  return <div className={`mt-4 rounded p-3 text-body-md ${className}`}>{children}</div>;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <span aria-hidden="true" className={`sv-skeleton ${className}`} />;
}

export function SessionLoading() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background text-on-background">
      <section className="sv-card w-[min(32rem,calc(100vw-2rem))] p-8" role="status">
        <FahamWordmark className="faham-session-wordmark" />
        <p className="sv-eyebrow">Secure Workspace</p>
        <h1 className="text-headline-md">Checking secure session</h1>
        <p className="sr-only">Preparing your authenticated Faham AI workspace.</p>
        <div className="mt-5 grid gap-3" aria-hidden="true">
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-4 w-3/5" />
          <div className="mt-2 grid grid-cols-3 gap-3">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        </div>
      </section>
    </main>
  );
}
