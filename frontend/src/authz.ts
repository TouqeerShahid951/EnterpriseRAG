import type { AccountType, ClearanceLevel, User } from "./types/api";

export const accountTypeOptions: AccountType[] = [
  "platform_admin",
  "system_admin",
  "space_admin",
  "contributor",
  "auditor",
  "member",
];

const clearanceLevelOptions: ClearanceLevel[] = [
  "NATO_UNCLASSIFIED",
  "NATO_RESTRICTED",
  "NATO_CONFIDENTIAL",
  "NATO_SECRET",
  "COSMIC_TOP_SECRET",
];

export const defaultClearanceLevel: ClearanceLevel = "NATO_RESTRICTED";

const clearanceRanks = new Map<ClearanceLevel, number>(clearanceLevelOptions.map((level, index) => [level, index]));

export function accountTypeLabel(accountType: AccountType): string {
  return {
    platform_admin: "Platform Admin",
    system_admin: "System Admin",
    user_manager: "Space Admin (legacy)",
    space_admin: "Space Admin",
    contributor: "Document Contributor",
    reviewer: "Document Reviewer (legacy)",
    auditor: "Audit Viewer",
    member: "Chat Member",
  }[accountType];
}

export function clearanceLevelLabel(clearanceLevel: ClearanceLevel): string {
  return {
    NATO_UNCLASSIFIED: "Unclassified",
    NATO_RESTRICTED: "Restricted",
    NATO_CONFIDENTIAL: "Confidential",
    NATO_SECRET: "Secret",
    COSMIC_TOP_SECRET: "Top Secret",
  }[clearanceLevel];
}

export function clearanceLevelDescription(clearanceLevel: ClearanceLevel): string {
  return {
    NATO_UNCLASSIFIED: "Lowest classification; visible to every cleared account in scope.",
    NATO_RESTRICTED: "Default document and account level for restricted internal material.",
    NATO_CONFIDENTIAL: "Requires confidential clearance or higher inside the selected Knowledge Space.",
    NATO_SECRET: "Requires secret clearance or higher inside the selected Knowledge Space.",
    COSMIC_TOP_SECRET: "Highest level; reserved for global administrators and explicitly cleared users.",
  }[clearanceLevel];
}

function clearanceRank(clearanceLevel: ClearanceLevel): number {
  return clearanceRanks.get(clearanceLevel) ?? 0;
}

export function canAccessClearance(user: User, clearanceLevel: ClearanceLevel): boolean {
  return clearanceRank(clearanceLevel) <= clearanceRank(user.clearance_level);
}

export function clearanceLevelsAssignableBy(user: User): ClearanceLevel[] {
  if (isGlobalAdmin(user)) return clearanceLevelOptions;
  return clearanceLevelOptions.filter((level) => canAccessClearance(user, level));
}

export function roleDescription(accountType: AccountType): string {
  return {
    platform_admin: "Global control across users, spaces, Runtime Settings, documents, review, audit, and queries.",
    system_admin: "Global control across users, spaces, documents, review, audit, and queries, excluding Runtime Settings and RAG evaluations.",
    user_manager: "Legacy scoped admin account. Use Space Admin for new assignments.",
    space_admin: "Manages users, Knowledge Spaces, documents, upload, review, and chat within assigned scopes.",
    contributor: "Chats with documents, uploads source files, and reviews ingestion/OCR issues in assigned Knowledge Spaces.",
    reviewer: "Legacy intake account that uploads and reviews documents without chat access.",
    auditor: "Views audit, user, space, and document metadata without query or content access.",
    member: "Chats with and reads documents in assigned Knowledge Spaces.",
  }[accountType];
}

export function canQuery(user: User): boolean {
  return ["platform_admin", "system_admin", "space_admin", "contributor", "member"].includes(user.account_type);
}

export function canUpload(user: User): boolean {
  return ["platform_admin", "system_admin", "space_admin", "contributor", "reviewer"].includes(user.account_type);
}

export function canUploadToSpace(user: User, groupPath: string): boolean {
  if (isGlobalAdmin(user)) return Boolean(groupPath);
  if (user.account_type === "space_admin") return isGroupPathInUserScope(user, groupPath);
  if (user.account_type === "contributor") return hasExactGroupScope(user, groupPath);
  if (user.account_type === "reviewer") return hasExactGroupScope(user, groupPath);
  return false;
}

export function canWriteDocument(user: User, groupPath: string, clearanceLevel?: ClearanceLevel): boolean {
  return canUploadToSpace(user, groupPath) && (!clearanceLevel || canAccessClearance(user, clearanceLevel));
}

export function canReview(user: User): boolean {
  return ["platform_admin", "system_admin", "space_admin", "contributor", "reviewer"].includes(user.account_type);
}

export function canManageUsers(user: User): boolean {
  return ["platform_admin", "system_admin", "space_admin", "user_manager"].includes(user.account_type);
}

export function canManageSpaces(user: User): boolean {
  return ["platform_admin", "system_admin", "space_admin"].includes(user.account_type);
}

export function canViewSpaceMetadata(user: User): boolean {
  return ["platform_admin", "system_admin", "user_manager", "space_admin", "auditor"].includes(user.account_type);
}

export function canViewAudit(user: User): boolean {
  return ["platform_admin", "system_admin", "auditor"].includes(user.account_type);
}

export function canViewIngestion(user: User): boolean {
  return ["platform_admin", "system_admin", "space_admin", "contributor", "reviewer", "auditor", "member"].includes(user.account_type);
}

export function isPlatformAdmin(user: User): boolean {
  return user.account_type === "platform_admin";
}

export function isGlobalAdmin(user: User): boolean {
  return user.account_type === "platform_admin" || user.account_type === "system_admin";
}

export function canAssignAccountType(actor: User, accountType: AccountType): boolean {
  if (actor.account_type === "platform_admin") return true;
  if (actor.account_type === "system_admin") return accountType !== "platform_admin";
  return ["space_admin", "user_manager"].includes(actor.account_type) && ["contributor", "member"].includes(accountType);
}

export function isGroupPathInUserScope(user: User, groupPath: string): boolean {
  return user.group_paths.some((scope) => isAncestorOrEqual(scope, groupPath));
}

export function hasExactGroupScope(user: User, groupPath: string): boolean {
  return user.group_paths.some((scope) => normalizeGroupPath(scope) === normalizeGroupPath(groupPath));
}

function isAncestorOrEqual(ancestor: string, candidate: string): boolean {
  const normalizedAncestor = normalizeGroupPath(ancestor);
  const normalizedCandidate = normalizeGroupPath(candidate);
  return normalizedCandidate === normalizedAncestor || normalizedCandidate.startsWith(`${normalizedAncestor}/`);
}

function normalizeGroupPath(path: string): string {
  const trimmed = path.trim();
  if (!trimmed) return "";
  const normalized = `/${trimmed.replace(/^\/+|\/+$/g, "")}`;
  return normalized === "/" ? "" : normalized;
}
