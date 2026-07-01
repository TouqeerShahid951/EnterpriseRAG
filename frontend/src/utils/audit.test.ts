import { describe, expect, it } from "vitest";

import { actorDisplay, auditCategory, auditImpactSummary, payloadSummary, targetDisplay } from "./audit";
import type { AuditEvent } from "../types/api";

describe("audit formatting helpers", () => {
  it("prefers actor and target user email over raw ids", () => {
    const event = auditEvent({
      actor_id: "actor-1",
      actor_email: "admin@example.test",
      target_type: "user",
      target_id: "target-1",
      target_user_email: "member@example.test",
      target_user_name: "Member User",
    });

    expect(actorDisplay(event)).toEqual({ label: "admin@example.test", detail: "actor-1" });
    expect(targetDisplay(event)).toEqual({ label: "member@example.test", detail: "Member User | target-1" });
  });

  it("shows deleted user fallbacks when identity cannot be resolved", () => {
    const event = auditEvent({
      actor_id: "old-actor",
      actor_email: null,
      target_type: "user",
      target_id: "old-target",
      target_user_email: null,
      target_user_name: null,
    });

    expect(actorDisplay(event)).toEqual({ label: "Deleted user", detail: "old-actor", unresolved: true });
    expect(targetDisplay(event)).toEqual({ label: "Deleted user", detail: "old-target", unresolved: true });
  });

  it("classifies known event families", () => {
    expect(auditCategory(auditEvent({ event_type: "auth.login" }))).toBe("authentication");
    expect(auditCategory(auditEvent({ event_type: "upload.queued", target_type: "document" }))).toBe("document");
    expect(auditCategory(auditEvent({ event_type: "internal.ingest.status" }))).toBe("ingestion");
    expect(auditCategory(auditEvent({ event_type: "query.artifact_created" }))).toBe("query");
  });

  it("summarizes known and unknown payloads", () => {
    const upload = auditEvent({
      event_type: "upload.queued",
      payload: { filename: "Budget.pdf", group_path: "/finance" },
    });

    expect(auditImpactSummary(upload)).toBe("Queued upload Budget.pdf in /finance");
    expect(payloadSummary({ alpha: "one", beta: 2, nested: { ok: true } })).toBe('alpha: one, beta: 2, nested: {"ok":true}');
  });

  it("summarizes admin password reset events", () => {
    const event = auditEvent({
      event_type: "admin.user.password_reset",
      target_type: "user",
      target_id: "user-1",
      target_user_email: "member@example.test",
    });

    expect(auditImpactSummary(event)).toBe("Reset password for member@example.test");
  });

  it("shows document titles for document targets", () => {
    const event = auditEvent({
      event_type: "documents.delete",
      target_type: "document",
      target_id: "doc-1",
      target_document_title: "Budget.pdf",
      payload: { group_path: "/finance" },
    });

    expect(targetDisplay(event)).toEqual({ label: "Budget.pdf", detail: "doc-1", unresolved: false });
    expect(auditImpactSummary(event)).toBe("Moved Budget.pdf to Trash in /finance");
  });

  it("falls back to payload filenames for older document audit rows", () => {
    const event = auditEvent({
      event_type: "documents.permanent_delete",
      target_type: "document",
      target_id: "doc-1",
      payload: { filename: "Legacy.pdf", group_path: "/legal" },
    });

    expect(targetDisplay(event)).toEqual({ label: "Legacy.pdf", detail: "doc-1", unresolved: false });
    expect(auditImpactSummary(event)).toBe("Permanently deleted Legacy.pdf in /legal");
  });
});

function auditEvent(overrides: Partial<AuditEvent>): AuditEvent {
  return {
    id: "audit-1",
    event_type: "admin.user.deleted",
    actor_id: null,
    actor_email: null,
    target_type: null,
    target_id: null,
    target_user_email: null,
    target_user_name: null,
    target_document_title: null,
    payload: {},
    created_at: "2026-06-18T12:00:00Z",
    ...overrides,
  };
}
