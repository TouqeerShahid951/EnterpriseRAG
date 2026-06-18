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
    payload: {},
    created_at: "2026-06-18T12:00:00Z",
    ...overrides,
  };
}
