import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Clock, ShieldAlert } from "lucide-react";
import type { FaithfulnessStatus } from "@/types/query";
import { formatScore } from "@/lib/utils/format";

function hasLowFaithfulness(status: FaithfulnessStatus, score: number): boolean {
  return status === "checked" && score < 0.8;
}

export function faithfulnessBadgeFor(status: FaithfulnessStatus, score: number): { className: string; icon: ReactNode; label: string } {
  if (status === "pending") {
    return { className: "", icon: <Clock size={14} />, label: "Checking grounding" };
  }
  if (status === "skipped") {
    return { className: "", icon: <Clock size={14} />, label: "Grounding not checked" };
  }
  if (status === "failed") {
    return { className: "sv-pill-warning", icon: <AlertTriangle size={14} />, label: "Grounding check failed" };
  }
  if (score < 0.8) {
    return { className: "sv-pill-warning", icon: <AlertTriangle size={14} />, label: `${formatScore(score)} faithfulness` };
  }
  return { className: "sv-pill-success", icon: <CheckCircle2 size={14} />, label: `${formatScore(score)} faithfulness` };
}

export function ResponseNotices({ conflictFlag, degraded, degradedReason, faithfulnessScore, faithfulnessStatus, unfoundedClaims }: NoticeProps) {
  const lowFaithfulness = hasLowFaithfulness(faithfulnessStatus, faithfulnessScore);
  const faithfulnessFailed = faithfulnessStatus === "failed";
  if (!conflictFlag && !degraded && !lowFaithfulness && !faithfulnessFailed) return null;
  return (
    <div className="grid gap-2">
      {conflictFlag ? (
        <Notice icon={<ShieldAlert size={16} />} tone="error" text="The indexed sources conflict. Inspect the cited evidence before using this answer." />
      ) : null}
      {faithfulnessFailed ? (
        <Notice icon={<AlertTriangle size={16} />} tone="warning" text="Grounding check failed before it could score this answer. Inspect the cited evidence before using it." />
      ) : null}
      {lowFaithfulness ? (
        <Notice icon={<AlertTriangle size={16} />} tone="warning" text={faithfulnessNoticeText(faithfulnessScore, unfoundedClaims)} />
      ) : null}
      {degraded && !faithfulnessFailed ? (
        <Notice icon={<AlertTriangle size={16} />} tone="warning" text={`Response is degraded${degradedReason ? `: ${degradedReason}` : "."}`} />
      ) : null}
    </div>
  );
}

function faithfulnessNoticeText(score: number, claims: string[]): string {
  const prefix = `Faithfulness is low (${formatScore(score)}).`;
  const visibleClaims = claims.filter(Boolean).slice(0, 3);
  return visibleClaims.length ? `${prefix} Unsupported: ${visibleClaims.join("; ")}` : `${prefix} Inspect the cited evidence before using this answer.`;
}

function Notice({ icon, text, tone }: { icon: ReactNode; text: string; tone: "error" | "warning" }) {
  const className = tone === "error" ? "border-error-red/25 bg-error-container text-error-red" : "border-warning-amber/25 bg-warning-amber/10 text-warning-amber";
  return <div className={`flex items-start gap-2 rounded border p-3 text-body-md ${className}`}><span className="mt-0.5">{icon}</span><span>{text}</span></div>;
}

export function ErrorAssistant({ message }: { message?: string }) {
  return <div className="rag-assistant-error rounded-lg border border-error-red/20 bg-error-container p-4 text-body-md text-error-red" role="alert">{message ?? "Query failed."}</div>;
}

export type NoticeProps = {
  conflictFlag: boolean;
  degraded: boolean;
  degradedReason: string | null;
  faithfulnessScore: number;
  faithfulnessStatus: FaithfulnessStatus;
  unfoundedClaims: string[];
};
