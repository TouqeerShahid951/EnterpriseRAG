import type { AuditEvent } from "../types/api";

export type AuditCategory = "authentication" | "document" | "ingestion" | "user" | "review" | "query" | "system";

export const auditCategories: AuditCategory[] = ["authentication", "document", "ingestion", "user", "review", "query", "system"];

export function auditCategory(event: AuditEvent): AuditCategory {
  if (event.event_type.startsWith("auth.")) return "authentication";
  if (
    event.target_type === "document" ||
    event.event_type.startsWith("upload.") ||
    event.event_type.startsWith("documents.") ||
    event.event_type.startsWith("folder_ingest.") ||
    event.event_type.startsWith("internal.document") ||
    event.event_type.startsWith("internal.supersession")
  ) return "document";
  if (event.event_type.startsWith("ingest.") || event.event_type.startsWith("internal.ingest.") || event.event_type.startsWith("admin.ingest.")) return "ingestion";
  if (event.target_type === "user" || event.event_type.startsWith("admin.user.")) return "user";
  if (event.event_type.startsWith("review.")) return "review";
  if (event.event_type.startsWith("query.")) return "query";
  return "system";
}

export function auditCategoryLabel(category: string): string {
  return labelize(category);
}

export function actorDisplay(event: AuditEvent): AuditIdentityDisplay {
  if (event.actor_email) return { label: event.actor_email, detail: event.actor_id ?? undefined };
  if (!event.actor_id) return { label: "System", detail: "Automated event" };
  return { label: "Deleted user", detail: event.actor_id, unresolved: true };
}

export function targetDisplay(event: AuditEvent): AuditIdentityDisplay {
  if (!event.target_type && !event.target_id) return { label: "Workspace", detail: "No target" };
  if (event.target_type === "user") {
    if (event.target_user_email) {
      return { label: event.target_user_email, detail: [event.target_user_name, event.target_id].filter(Boolean).join(" | ") };
    }
    return { label: "Deleted user", detail: event.target_id ?? undefined, unresolved: true };
  }
  if (event.target_type === "document") {
    const title = documentDisplayName(event);
    return {
      label: title ?? "Document",
      detail: event.target_id ?? undefined,
      unresolved: !title,
    };
  }
  return {
    label: event.target_type ? labelize(event.target_type) : "Target",
    detail: event.target_id ?? undefined,
  };
}

export function auditImpactSummary(event: AuditEvent): string {
  const documentName = documentDisplayName(event);
  const filename = stringPayload(event, "filename");
  const groupPath = stringPayload(event, "group_path");
  const jobId = stringPayload(event, "job_id");
  const target = targetDisplay(event).label;
  if (event.event_type === "upload.queued") return compactSentence(["Queued upload", filename ?? documentName, groupPath && `in ${groupPath}`]);
  if (event.event_type === "documents.delete") return compactSentence(["Moved", documentName ?? "document", "to Trash", groupPath && `in ${groupPath}`]);
  if (event.event_type === "documents.permanent_delete") return compactSentence(["Permanently deleted", documentName ?? "document", groupPath && `in ${groupPath}`]);
  if (event.event_type === "documents.restore") return compactSentence(["Restored", documentName ?? "document", jobId && `job ${jobId}`]);
  if (event.event_type === "documents.reingest") return compactSentence(["Queued reingestion for", documentName ?? "document", jobId && `job ${jobId}`]);
  if (event.event_type === "documents.clearance_update") return compactSentence(["Updated clearance for", documentName ?? "document", stringPayload(event, "clearance_level")]);
  if (event.event_type === "documents.supersede") return "Updated document supersession chain";
  if (event.event_type === "ingest.cancelled") return compactSentence(["Cancelled ingestion job", jobId ?? event.target_id ?? undefined, documentName && `for ${documentName}`]);
  if (event.event_type === "admin.ingest.requeued") return compactSentence(["Requeued ingestion job", jobId ?? event.target_id ?? undefined, documentName && `for ${documentName}`]);
  if (event.event_type.startsWith("internal.ingest.")) return compactSentence(["Worker ingestion event", jobId ?? event.target_id ?? undefined, documentName && `for ${documentName}`]);
  if (event.event_type === "auth.login") return compactSentence(["User signed in", actorDisplay(event).label]);
  if (event.event_type === "auth.logout") return "Session signed out";
  if (event.event_type === "auth.refresh") return compactSentence(["Session refreshed", actorDisplay(event).label]);
  if (event.event_type === "admin.user.deleted") return compactSentence(["Deleted user account", target]);
  if (event.event_type === "admin.user.password_reset") return compactSentence(["Reset password for", target]);
  if (event.event_type === "admin.user.chat_activity_viewed") return compactSentence(["Viewed chat activity for", target]);
  if (event.event_type === "admin.user.chat_session_viewed") return compactSentence(["Viewed chat transcript for", target]);
  if (event.event_type === "audit.exported") return compactSentence(["Exported audit log CSV", numericPayload(event, "row_count")]);
  if (event.event_type === "review.approved") return "Approved extraction review item";
  if (event.event_type === "review.rejected") return "Rejected extraction review item";
  if (event.event_type === "review.resume_skipped") return "Skipped review resume because job was cancelled";
  if (event.event_type === "query.artifact_created") return compactSentence(["Generated artifact", stringPayload(event, "format")]);
  if (event.event_type === "query.artifact_failed") return compactSentence(["Artifact generation failed", stringPayload(event, "type")]);
  if (event.event_type === "query.artifact_downloaded") return "Downloaded generated artifact";
  return payloadSummary(event.payload);
}

function documentDisplayName(event: AuditEvent): string | undefined {
  return textValue(event.target_document_title)
    ?? stringPayload(event, "target_document_title")
    ?? stringPayload(event, "document_title")
    ?? stringPayload(event, "document_name")
    ?? stringPayload(event, "title")
    ?? stringPayload(event, "filename");
}

export function payloadSummary(payload: Record<string, unknown>, limit = 4): string {
  const entries = Object.entries(payload);
  if (entries.length === 0) return "No payload";
  return entries.slice(0, limit).map(([key, value]) => `${key}: ${formatPayloadValue(value)}`).join(", ");
}

export function formatPayloadValue(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return `[${value.slice(0, 4).map(formatPayloadValue).join(", ")}${value.length > 4 ? ", ..." : ""}]`;
  return JSON.stringify(value);
}

function labelize(value: string): string {
  return value.replace(/_/g, " ").replace(/\./g, " / ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function stringPayload(event: AuditEvent, key: string): string | undefined {
  const value = event.payload[key];
  return textValue(value);
}

function numericPayload(event: AuditEvent, key: string): string | undefined {
  const value = event.payload[key];
  return typeof value === "number" ? `${value} rows` : undefined;
}

function compactSentence(parts: Array<string | undefined | false>): string {
  return parts.filter(Boolean).join(" ");
}

function textValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

export type AuditIdentityDisplay = {
  detail?: string;
  label: string;
  unresolved?: boolean;
};
