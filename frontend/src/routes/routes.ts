import type { User as AuthUser } from "@/types/api";
import { canManageSpaces, canManageUsers, canQuery, canReview, canUpload, canViewAudit, canViewIngestion, isGlobalAdmin, isPlatformAdmin } from "@/lib/auth/authz";

export type RouteId =
  | "abbreviation-glossary"
  | "access"
  | "account"
  | "activity-log"
  | "advanced-search"
  | "analytics"
  | "answer-review"
  | "chat"
  | "database-connectors"
  | "document-extraction"
  | "document-overview"
  | "document-trash"
  | "documents"
  | "evaluations"
  | "ingestion-health"
  | "ingestion-jobs"
  | "knowledge-spaces"
  | "login"
  | "overview"
  | "review"
  | "security-audit"
  | "settings"
  | "source-viewer"
  | "upload"
  | "workspace-settings";

export const routePaths: Record<RouteId, string> = {
  "abbreviation-glossary": "/document-intake/abbreviation-glossary",
  access: "/access",
  account: "/account",
  "activity-log": "/activity-log",
  "advanced-search": "/advanced-search",
  analytics: "/analytics",
  "answer-review": "/answer-review",
  chat: "/chat",
  "database-connectors": "/document-intake/connectors",
  "document-extraction": "/document-extraction",
  "document-overview": "/documents/overview",
  "document-trash": "/documents/trash",
  documents: "/documents",
  evaluations: "/evaluations",
  "ingestion-health": "/ingestion-health",
  "ingestion-jobs": "/ingestion-jobs",
  "knowledge-spaces": "/knowledge-spaces",
  login: "/login",
  overview: "/overview",
  review: "/review",
  "security-audit": "/security-audit",
  settings: "/settings",
  "source-viewer": "/source-viewer",
  upload: "/upload",
  "workspace-settings": "/workspace-settings",
};

export const routeTitles: Record<RouteId, string> = {
  "abbreviation-glossary": "Abbreviation Glossary",
  access: "User Management",
  account: "Account",
  "activity-log": "System Audit",
  "advanced-search": "Query Intelligence",
  analytics: "RAG Evaluation",
  "answer-review": "Review Queue",
  chat: "Query Intelligence",
  "database-connectors": "Database Connectors",
  "document-extraction": "Folder Sources",
  "document-overview": "Document Overview",
  "document-trash": "Document Trash",
  documents: "Documents",
  evaluations: "RAG Evaluation",
  "ingestion-health": "Ingestion Health",
  "ingestion-jobs": "Ingestion Activity",
  "knowledge-spaces": "Knowledge Spaces",
  login: "Sign in",
  overview: "Workspace Summary",
  review: "Review Queue",
  "security-audit": "System Audit",
  settings: "Runtime Settings",
  "source-viewer": "Source Viewer",
  upload: "Add Files",
  "workspace-settings": "Runtime Settings",
};

const routeAliases: Partial<Record<RouteId, RouteId>> = {
  "advanced-search": "chat",
  "answer-review": "review",
  analytics: "evaluations",
  "security-audit": "activity-log",
  "workspace-settings": "settings",
};

const platformOnlyRoutes = new Set<RouteId>([
  "analytics",
  "evaluations",
  "settings",
  "workspace-settings",
]);
const userManagementRoutes = new Set<RouteId>(["access"]);
const auditRoutes = new Set<RouteId>(["activity-log", "security-audit"]);
const glossaryRoutes = new Set<RouteId>(["abbreviation-glossary"]);
const uploadRoutes = new Set<RouteId>(["upload"]);
const folderSourceRoutes = new Set<RouteId>(["document-extraction", "database-connectors"]);
const ingestionRoutes = new Set<RouteId>(["ingestion-health", "ingestion-jobs"]);
const queryRoutes = new Set<RouteId>(["advanced-search", "chat", "source-viewer"]);
const spaceRoutes = new Set<RouteId>(["document-overview", "document-trash", "documents", "knowledge-spaces"]);
const reviewRoutes = new Set<RouteId>(["answer-review", "review"]);

export function canAccessRoute(user: AuthUser, route: RouteId): boolean {
  if (platformOnlyRoutes.has(route)) return isPlatformAdmin(user);
  if (userManagementRoutes.has(route)) return canManageUsers(user);
  if (auditRoutes.has(route)) return canViewAudit(user);
  if (glossaryRoutes.has(route)) return isGlobalAdmin(user);
  if (uploadRoutes.has(route)) return canUpload(user);
  if (folderSourceRoutes.has(route)) return canManageSpaces(user);
  if (ingestionRoutes.has(route)) return canViewIngestion(user);
  if (queryRoutes.has(route)) return canQuery(user);
  if (spaceRoutes.has(route)) return canQuery(user) || canManageSpaces(user) || user.account_type === "auditor";
  if (reviewRoutes.has(route)) return canReview(user);
  return true;
}

export function defaultRouteForUser(user: AuthUser): RouteId {
  if (canAccessRoute(user, "chat")) return "chat";
  if (canAccessRoute(user, "access")) return "access";
  if (canAccessRoute(user, "activity-log")) return "activity-log";
  if (canAccessRoute(user, "upload")) return "upload";
  if (canAccessRoute(user, "review")) return "review";
  if (canAccessRoute(user, "knowledge-spaces")) return "knowledge-spaces";
  return "account";
}

export function authenticatedRouteForUser(user: AuthUser, requestedRoute: RouteId | null): RouteId {
  if (user.must_change_password) return "account";
  if (!requestedRoute || requestedRoute === "login") return defaultRouteForUser(user);

  const targetRoute = canonicalRoute(requestedRoute);
  return canAccessRoute(user, targetRoute) ? targetRoute : defaultRouteForUser(user);
}

export function canonicalRoute(route: RouteId): RouteId {
  return routeAliases[route] ?? route;
}

export function routeFromLocation(pathname = location.pathname, search = location.search): RouteId | null {
  const legacy = legacyKnowledgeSpaceRoute(pathname, search);
  if (legacy) return legacy;
  const entry = Object.entries(routePaths).find(([, path]) => path === pathname);
  return (entry?.[0] as RouteId | undefined) ?? null;
}

const workspaceNavigation: WorkspaceNavigationItem[] = [
  {
    children: [
      { label: "Workspace Summary", route: "overview" },
      { label: "Ingestion Health", route: "ingestion-health" },
    ],
    icon: "overview",
    id: "overview",
    label: "System Overview",
    section: "Operate",
  },
  { icon: "query", id: "query", label: "Query Intelligence", route: "chat", section: "Operate" },
  {
    children: [
      { label: "Add Files", route: "upload" },
      { label: "Abbreviation Glossary", route: "abbreviation-glossary" },
      { label: "Folder Sources", route: "document-extraction" },
      { label: "Database Connectors", route: "database-connectors" },
      { label: "Activity", route: "ingestion-jobs" },
    ],
    icon: "documents",
    id: "document-intake",
    label: "Document Intake",
    section: "Corpus",
  },
  {
    children: [
      { label: "Overview", route: "document-overview" },
      { label: "Documents", route: "documents" },
      { label: "Knowledge Spaces", route: "knowledge-spaces" },
      { badge: "trash", label: "Trash", route: "document-trash" },
    ],
    icon: "spaces",
    id: "document-library",
    label: "Document Library",
    section: "Corpus",
  },
  { badge: "review", icon: "review", id: "review", label: "Review Queue", route: "review", section: "Evaluate" },
  { icon: "evaluations", id: "evaluations", label: "RAG Evaluation", route: "evaluations", section: "Evaluate" },
  { icon: "audit", id: "audit", label: "System Audit", route: "activity-log", section: "Govern" },
  { icon: "users", id: "users", label: "User Management", route: "access", section: "Govern" },
  { icon: "settings", id: "settings", label: "Runtime Settings", route: "settings", section: "Govern" },
];

export function visibleNavigation(user: AuthUser): WorkspaceNavigationItem[] {
  return workspaceNavigation.flatMap((item) => {
    if (item.children) {
      const children = item.children.filter((child) => canAccessRoute(user, child.route));
      return children.length ? [{ ...item, children }] : [];
    }
    return item.route && canAccessRoute(user, item.route) ? [item] : [];
  });
}

export function navigationGroupForRoute(route: RouteId): string | null {
  return workspaceNavigation.find((item) => item.route === route || item.children?.some((child) => child.route === route))?.id ?? null;
}

function legacyKnowledgeSpaceRoute(pathname: string, search: string): RouteId | null {
  if (pathname !== routePaths["knowledge-spaces"]) return null;
  const tab = new URLSearchParams(search).get("tab");
  if (tab === "documents") return "documents";
  if (tab === "trash") return "document-trash";
  if (tab === "jobs" || tab === "uploads") return "ingestion-jobs";
  return null;
}

export type NavigationBadge = "review" | "trash";
export type NavigationIcon = "audit" | "documents" | "evaluations" | "overview" | "query" | "review" | "settings" | "spaces" | "users";
export type NavigateOptions = { replace?: boolean; search?: string | URLSearchParams };
type WorkspaceNavigationChild = { badge?: NavigationBadge; label: string; route: RouteId };
export type WorkspaceNavigationItem = {
  badge?: NavigationBadge;
  children?: WorkspaceNavigationChild[];
  icon: NavigationIcon;
  id: string;
  label: string;
  route?: RouteId;
  section: "Operate" | "Corpus" | "Evaluate" | "Govern";
};
