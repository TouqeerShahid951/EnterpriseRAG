import { Activity, AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";
import type { UploadJobStep } from "@/types/api";
import type { UploadJobView } from "@/types/chat";

export function stageIcon(job: UploadJobView) {
  if (job.status === "complete") return <CheckCircle2 aria-hidden="true" size={18} />;
  if (job.status === "failed") return <XCircle aria-hidden="true" size={18} />;
  if (job.status === "cancelled") return <XCircle aria-hidden="true" size={18} />;
  if (job.status === "human_review") return <AlertTriangle aria-hidden="true" size={18} />;
  return <Loader2 aria-hidden="true" className="animate-spin" size={18} />;
}

export function jobPanelClass(status: UploadJobView["status"] | "processing") {
  if (status === "complete") return "border-success/30 bg-success/10";
  if (status === "failed") return "border-error-red/25 bg-error-container";
  if (status === "cancelled") return "border-warning-amber/30 bg-warning-amber/10";
  if (status === "human_review") return "border-warning-amber/30 bg-warning-amber/10";
  return "border-surface-border bg-surface-container-low";
}

export function progressFillClass(status: UploadJobView["status"] | "processing") {
  if (status === "complete") return "bg-success";
  if (status === "failed") return "bg-error-red";
  if (status === "cancelled") return "bg-warning-amber";
  if (status === "human_review") return "bg-warning-amber";
  return "bg-primary";
}

export function progressTextClass(status: UploadJobView["status"] | "processing") {
  if (status === "complete") return "text-success";
  if (status === "failed") return "text-error-red";
  if (status === "cancelled") return "text-warning-amber";
  if (status === "human_review") return "text-warning-amber";
  return "text-primary";
}

export function stageIconClass(status: UploadJobView["status"] | "processing") {
  if (status === "complete") return "bg-success/10 text-success";
  if (status === "failed") return "bg-error-container text-error-red";
  if (status === "cancelled") return "bg-warning-amber/10 text-warning-amber";
  if (status === "human_review") return "bg-warning-amber/10 text-warning-amber";
  return "bg-primary/10 text-primary";
}

export function currentJobStep(job: UploadJobView): UploadJobStep | null {
  return job.steps.find((step) => step.state === "active" || step.state === "failed" || step.state === "needs_review")
    ?? job.steps.find((step) => step.id === job.stage)
    ?? null;
}

export function nextJobStep(job: UploadJobView): UploadJobStep | null {
  return job.steps.find((step) => step.state === "pending") ?? null;
}

export function jobActivityText(job: UploadJobView): string {
  if (job.status === "complete") return job.warnings.length > 0 ? "Indexed with warnings" : "Indexed";
  if (job.status === "failed") return "Failed";
  if (job.status === "cancelled") return "Cancelled";
  if (job.status === "human_review") return "Needs review";
  if (job.status === "scheduled") return "Scheduled";
  if (job.status === "queued") return "Waiting for worker";
  const heartbeat = relativeAge(job.lastHeartbeatAt);
  if (!heartbeat) return "Worker starting";
  if (heartbeat.seconds <= 75) return `Worker active ${agoText(heartbeat.label)}`;
  if (heartbeat.seconds <= 180) return `Last worker update ${agoText(heartbeat.label)}`;
  return `No worker update for ${heartbeat.label}`;
}

export function jobActivityClass(job: UploadJobView): string {
  if (job.status === "complete") return "bg-success/10 text-success";
  if (job.status === "failed") return "bg-error-container text-error-red";
  if (job.status === "cancelled") return "bg-warning-amber/10 text-warning-amber";
  if (job.status === "human_review") return "bg-warning-amber/10 text-warning-amber";
  const heartbeat = relativeAge(job.lastHeartbeatAt);
  if (job.status === "processing" && heartbeat && heartbeat.seconds > 180) return "bg-warning-amber/10 text-warning-amber";
  return "bg-primary/10 text-primary";
}

export function elapsedText(job: UploadJobView): string | null {
  const started = relativeAge(job.createdAt);
  if (!started) return null;
  if (job.status === "complete" || job.status === "failed" || job.status === "human_review" || job.status === "cancelled") return `Started ${agoText(started.label)}`;
  return `Running ${started.label}`;
}

export function durationTakenText(job: UploadJobView): string | null {
  if (job.status !== "complete" && job.status !== "failed" && job.status !== "human_review" && job.status !== "cancelled") return null;
  const seconds = secondsBetween(job.createdAt, job.completedAt ?? job.updatedAt);
  if (seconds === null) return null;
  return `Took ${exactDurationLabel(seconds)}`;
}

export function activeStageProgressNote(job: UploadJobView, stageProgress: string | null): string | null {
  if (job.status !== "processing") return null;
  if (job.stage !== "parsing_document") return stageProgress;
  return parserProgressNote(job, stageProgress);
}

function parserProgressNote(job: UploadJobView, stageProgress: string | null): string | null {
  if (job.status !== "processing" || job.stage !== "parsing_document") return null;
  if (stageProgress && stageProgress.toLowerCase().includes("docling")) {
    return "Docling is repairing selected pages before metadata generation starts.";
  }
  if (job.stageProgress?.unit === "pages" && job.stageProgress.total <= 1 && job.stageProgress.current >= job.stageProgress.total) {
    return "Page parsing is complete; OCR, layout, and table structure can still run before metadata starts.";
  }
  if (stageProgress) return "Scanned pages, handwriting, and dense tables may spend extra time in this stage.";
  return "The parser is extracting text, layout, tables, and hierarchy.";
}

export function parserSummaryText(job: UploadJobView): string | null {
  const provenance = job.parserProvenance;
  if (!provenance) return null;
  const parser = provenance.secondary_parser ? `${provenance.primary_parser} + ${provenance.secondary_parser}` : provenance.primary_parser;
  const pages = provenance.page_count ? `${provenance.page_count} page${provenance.page_count === 1 ? "" : "s"}` : "page count pending";
  return `Parser route: ${labelize(provenance.routing_mode)} via ${parser}; ${pages}.`;
}

export function stepChipClass(state: UploadJobStep["state"]): string {
  if (state === "complete") return "border-success/30 bg-success/10 text-success";
  if (state === "active") return "border-primary/40 bg-primary/10 text-primary";
  if (state === "failed") return "border-error-red/30 bg-error-container text-error-red";
  if (state === "cancelled") return "border-warning-amber/30 bg-warning-amber/10 text-warning-amber";
  if (state === "needs_review") return "border-warning-amber/30 bg-warning-amber/10 text-warning-amber";
  return "border-surface-border bg-surface-container-low text-secondary";
}

export function stepStateIcon(step: UploadJobStep) {
  if (step.state === "complete") return <CheckCircle2 aria-hidden="true" size={12} />;
  if (step.state === "failed") return <XCircle aria-hidden="true" size={12} />;
  if (step.state === "cancelled") return <XCircle aria-hidden="true" size={12} />;
  if (step.state === "needs_review") return <AlertTriangle aria-hidden="true" size={12} />;
  if (step.state === "active") return <Loader2 aria-hidden="true" className="animate-spin" size={12} />;
  return <span aria-hidden="true" className="h-2 w-2 rounded-full bg-current opacity-40" />;
}

export function terminalDetailIcon(job: UploadJobView) {
  if (job.status === "complete") return <CheckCircle2 aria-hidden="true" size={13} />;
  if (job.status === "failed") return <XCircle aria-hidden="true" size={13} />;
  if (job.status === "cancelled") return <XCircle aria-hidden="true" size={13} />;
  if (job.status === "human_review") return <AlertTriangle aria-hidden="true" size={13} />;
  return <Activity aria-hidden="true" size={13} />;
}

function relativeAge(value: string | null): { seconds: number; label: string } | null {
  if (!value) return null;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return null;
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  return { seconds, label: durationLabel(seconds) };
}

function durationLabel(totalSeconds: number): string {
  if (totalSeconds < 5) return "just now";
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes > 0 ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
}

function exactDurationLabel(totalSeconds: number): string {
  if (totalSeconds < 1) return "<1s";
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 60) return seconds > 0 ? `${totalMinutes}m ${seconds}s` : `${totalMinutes}m`;
  const minutes = totalMinutes % 60;
  const hours = Math.floor(totalMinutes / 60);
  return seconds > 0 ? `${hours}h ${minutes}m ${seconds}s` : `${hours}h ${minutes}m`;
}

function secondsBetween(startValue: string | null, endValue: string | null): number | null {
  if (!startValue || !endValue) return null;
  const start = Date.parse(startValue);
  const end = Date.parse(endValue);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  return Math.max(0, Math.round((end - start) / 1000));
}

function agoText(label: string): string {
  return label === "just now" ? label : `${label} ago`;
}

function labelize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
