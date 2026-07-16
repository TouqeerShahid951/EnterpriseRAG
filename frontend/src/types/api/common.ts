export type ISODateString = string;

export type DocType = string;

export type AccountType =
  | "platform_admin"
  | "system_admin"
  | "user_manager"
  | "space_admin"
  | "contributor"
  | "reviewer"
  | "auditor"
  | "member";

export type ClearanceLevel =
  | "NATO_UNCLASSIFIED"
  | "NATO_RESTRICTED"
  | "NATO_CONFIDENTIAL"
  | "NATO_SECRET"
  | "COSMIC_TOP_SECRET";

export interface ApiError {
  status: number;
  code: string;
  message: string;
  details?: unknown;
  trace_id?: string;
}
