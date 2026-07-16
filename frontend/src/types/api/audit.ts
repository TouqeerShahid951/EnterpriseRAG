import type { ISODateString } from "./common";

export interface AuditEvent {
  id: string;
  event_type: string;
  actor_id: string | null;
  actor_email: string | null;
  target_type: string | null;
  target_id: string | null;
  target_user_email: string | null;
  target_user_name: string | null;
  target_document_title: string | null;
  payload: Record<string, unknown>;
  created_at: ISODateString | null;
}

export interface AuditSummary {
  total: number;
  document_events: number;
  auth_events: number;
  system_events: number;
  actor_count: number;
  event_type_count: number;
  category_counts: Record<string, number>;
  target_type_counts: Record<string, number>;
  event_type_counts: Record<string, number>;
}

export interface AuditEventListResponse {
  items: AuditEvent[];
  total: number;
  limit: number;
  offset: number;
  summary: AuditSummary;
}
