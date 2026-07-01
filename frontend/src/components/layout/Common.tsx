import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, XCircle, type LucideIcon } from "lucide-react";

import { PrudentiaWordmark } from "../brand/PrudentiaBrand";

export function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="sv-metadata">{label}</dt>
      <dd className="mt-1 break-words text-body-md font-semibold text-on-surface">{value}</dd>
    </div>
  );
}

export function EmptyPanel({ action, children, icon: Icon = Info, title }: { action?: ReactNode; children: ReactNode; icon?: LucideIcon; title?: string }) {
  return (
    <div className="sv-empty-panel">
      <span className="sv-empty-icon" aria-hidden="true">
        <Icon size={17} />
      </span>
      <div className="sv-empty-content">
        {title ? <strong className="sv-empty-title">{title}</strong> : null}
        <div className="sv-empty-copy">{children}</div>
        {action ? <div className="sv-empty-action">{action}</div> : null}
      </div>
    </div>
  );
}

export function InlineMessage({ children, tone }: { children: ReactNode; tone: "error" | "success" | "warning" }) {
  const Icon = tone === "error" ? XCircle : tone === "success" ? CheckCircle2 : AlertTriangle;
  const className = tone === "error" ? "Prudentia-error-banner" : tone === "success" ? "Prudentia-success-banner" : "Prudentia-planned-banner";
  return (
    <div className={`sv-inline-message sv-inline-message-${tone} mt-4 ${className}`} role={tone === "error" ? "alert" : "status"}>
      <Icon size={16} aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <span aria-hidden="true" className={`sv-skeleton ${className}`} />;
}

export function SessionLoading() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background text-on-background">
      <section className="Prudentia-session-card sv-card w-[min(32rem,calc(100vw-2rem))] p-8" role="status">
        <PrudentiaWordmark className="Prudentia-session-wordmark" />
        <p className="sv-eyebrow">Secure Workspace</p>
        <h1 className="text-headline-md">Checking secure session</h1>
        <p className="sr-only">Preparing your authenticated Prudentia AI workspace.</p>
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
