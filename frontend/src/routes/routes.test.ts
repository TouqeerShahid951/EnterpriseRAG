import { describe, expect, it } from "vitest";

import { accountTypeLabel, accountTypeOptions, canAssignAccountType, canUploadToSpace, canWriteDocument } from "@/lib/auth/authz";
import { authenticatedRouteForUser, canAccessRoute, defaultRouteForUser, navigationGroupForRoute, routeFromLocation, visibleNavigation, type RouteId } from "@/routes/routes";
import type { AccountType, ClearanceLevel, User } from "@/types/api";

describe("account type route access", () => {
  it("uses simplified visible role names for assignment", () => {
    expect(accountTypeOptions).toEqual(["platform_admin", "system_admin", "space_admin", "contributor", "auditor", "member"]);
    expect(accountTypeLabel("contributor")).toBe("Document Contributor");
    expect(accountTypeLabel("member")).toBe("Chat Member");
    expect(accountTypeLabel("auditor")).toBe("Audit Viewer");
  });

  it("allows platform admins to reach global surfaces", () => {
    const user = makeUser("platform_admin");

    expect(canAccessRoute(user, "settings")).toBe(true);
    expect(canAccessRoute(user, "access")).toBe(true);
    expect(canAccessRoute(user, "review")).toBe(true);
    expect(canAccessRoute(user, "upload")).toBe(true);
    expect(canAccessRoute(user, "document-overview")).toBe(true);
    expect(canAccessRoute(user, "document-trash")).toBe(true);
    expect(canAccessRoute(user, "ingestion-health")).toBe(true);
    expect(canAccessRoute(user, "ingestion-jobs")).toBe(true);
    expect(defaultRouteForUser(user)).toBe("chat");
  });

  it("allows system admins everywhere except configs and RAG evaluations", () => {
    const user = makeUser("system_admin");

    expect(canAccessRoute(user, "settings")).toBe(false);
    expect(canAccessRoute(user, "evaluations")).toBe(false);
    expect(canAccessRoute(user, "access")).toBe(true);
    expect(canAccessRoute(user, "review")).toBe(true);
    expect(canAccessRoute(user, "upload")).toBe(true);
    expect(canAccessRoute(user, "document-overview")).toBe(true);
    expect(canAccessRoute(user, "document-trash")).toBe(true);
    expect(canAccessRoute(user, "ingestion-health")).toBe(true);
    expect(canAccessRoute(user, "ingestion-jobs")).toBe(true);
    expect(defaultRouteForUser(user)).toBe("chat");
  });

  it.each([
    ["user_manager", ["access"], ["chat", "upload", "settings", "review", "document-overview", "documents", "document-trash", "ingestion-health", "ingestion-jobs"]],
    ["space_admin", ["access", "chat", "upload", "review", "document-overview", "knowledge-spaces", "documents", "document-trash", "document-extraction", "database-connectors", "ingestion-health", "ingestion-jobs"], ["settings"]],
    ["contributor", ["chat", "upload", "review", "document-overview", "knowledge-spaces", "documents", "document-trash", "ingestion-health", "ingestion-jobs"], ["access", "settings", "document-extraction", "database-connectors"]],
    ["reviewer", ["upload", "review", "ingestion-health", "ingestion-jobs"], ["access", "chat", "settings", "document-overview", "knowledge-spaces", "documents", "document-trash", "document-extraction", "database-connectors"]],
    ["auditor", ["activity-log", "document-overview", "knowledge-spaces", "documents", "document-trash", "ingestion-health", "ingestion-jobs"], ["chat", "upload", "review", "settings", "document-extraction", "database-connectors"]],
    ["member", ["chat", "document-overview", "knowledge-spaces", "documents", "document-trash", "ingestion-health", "ingestion-jobs"], ["access", "settings", "upload", "review", "document-extraction", "database-connectors"]],
  ] as [AccountType, RouteId[], RouteId[]][])("applies scoped route access for %s", (accountType, allowed, denied) => {
    const user = makeUser(accountType);

    for (const route of allowed) expect(canAccessRoute(user, route)).toBe(true);
    for (const route of denied) expect(canAccessRoute(user, route)).toBe(false);
  });

  it("uses a non-chat default route for non-query roles", () => {
    expect(defaultRouteForUser(makeUser("user_manager"))).toBe("access");
    expect(defaultRouteForUser(makeUser("reviewer"))).toBe("upload");
    expect(defaultRouteForUser(makeUser("auditor"))).toBe("activity-log");
  });

  it("limits the source viewer to users who can query documents", () => {
    expect(canAccessRoute(makeUser("member"), "source-viewer")).toBe(true);
    expect(canAccessRoute(makeUser("auditor"), "source-viewer")).toBe(false);
  });

  it("mirrors document write scope rules for upload and delete controls", () => {
    expect(canUploadToSpace(makeUser("platform_admin"), "/engineering")).toBe(true);
    expect(canUploadToSpace(makeUser("system_admin"), "/engineering")).toBe(true);
    expect(canUploadToSpace(makeUser("space_admin"), "/finance/procurement")).toBe(true);
    expect(canWriteDocument(makeUser("space_admin"), "/finance/procurement")).toBe(true);
    expect(canWriteDocument(makeUser("space_admin", "NATO_RESTRICTED"), "/finance/procurement", "NATO_SECRET")).toBe(false);
    expect(canUploadToSpace(makeUser("contributor"), "/finance")).toBe(true);
    expect(canWriteDocument(makeUser("contributor"), "/finance/procurement")).toBe(false);
    expect(canUploadToSpace(makeUser("member"), "/finance")).toBe(false);
    expect(canUploadToSpace(makeUser("reviewer"), "/finance")).toBe(true);
    expect(canWriteDocument(makeUser("reviewer"), "/finance/procurement")).toBe(false);
  });

  it("prevents lower admin roles from assigning platform-only roles", () => {
    expect(canAssignAccountType(makeUser("platform_admin"), "system_admin")).toBe(true);
    expect(canAssignAccountType(makeUser("system_admin"), "platform_admin")).toBe(false);
    expect(canAssignAccountType(makeUser("system_admin"), "system_admin")).toBe(true);
    expect(canAssignAccountType(makeUser("user_manager"), "system_admin")).toBe(false);
    expect(canAssignAccountType(makeUser("user_manager"), "space_admin")).toBe(false);
    expect(canAssignAccountType(makeUser("space_admin"), "contributor")).toBe(true);
    expect(canAssignAccountType(makeUser("space_admin"), "member")).toBe(true);
    expect(canAssignAccountType(makeUser("space_admin"), "auditor")).toBe(false);
  });

  it("redirects legacy Knowledge Space tabs to focused routes", () => {
    expect(routeFromLocation("/document-intake/connectors", "")).toBe("database-connectors");
    expect(routeFromLocation("/knowledge-spaces", "?tab=documents")).toBe("documents");
    expect(routeFromLocation("/knowledge-spaces", "?tab=trash")).toBe("document-trash");
    expect(routeFromLocation("/knowledge-spaces", "?tab=jobs")).toBe("ingestion-jobs");
    expect(routeFromLocation("/knowledge-spaces", "?space=%2Ffinance")).toBe("knowledge-spaces");
    expect(routeFromLocation("/documents/overview", "")).toBe("document-overview");
  });

  it("resolves authenticated locations to an accessible canonical route", () => {
    expect(authenticatedRouteForUser(makeUser("member"), "advanced-search")).toBe("chat");
    expect(authenticatedRouteForUser(makeUser("system_admin"), "workspace-settings")).toBe("chat");
    expect(authenticatedRouteForUser(makeUser("auditor"), "documents")).toBe("documents");
    expect(authenticatedRouteForUser(makeUser("user_manager"), null)).toBe("access");
  });

  it("keeps password-change enforcement ahead of requested routes", () => {
    const user = { ...makeUser("member"), must_change_password: true };

    expect(authenticatedRouteForUser(user, "chat")).toBe("account");
  });

  it("filters nested navigation by role and resolves active groups", () => {
    const contributorNavigation = visibleNavigation(makeUser("contributor"));
    const contributorIntake = contributorNavigation.find((item) => item.id === "document-intake");
    const contributorLibrary = contributorNavigation.find((item) => item.id === "document-library");
    const contributorReview = contributorNavigation.find((item) => item.id === "review");
    const spaceAdminNavigation = visibleNavigation(makeUser("space_admin"));
    const spaceAdminIntake = spaceAdminNavigation.find((item) => item.id === "document-intake");
    const spaceAdminReview = spaceAdminNavigation.find((item) => item.id === "review");
    const reviewerNavigation = visibleNavigation(makeUser("reviewer"));
    const reviewerIntake = reviewerNavigation.find((item) => item.id === "document-intake");
    const reviewerLibrary = reviewerNavigation.find((item) => item.id === "document-library");
    const memberNavigation = visibleNavigation(makeUser("member"));
    const memberLibrary = memberNavigation.find((item) => item.id === "document-library");
    const reviewQueue = reviewerNavigation.find((item) => item.id === "review");
    const adminNavigation = visibleNavigation(makeUser("platform_admin"));
    const evaluations = adminNavigation.find((item) => item.id === "evaluations");
    const settings = adminNavigation.find((item) => item.id === "settings");
    const systemAdminNavigation = visibleNavigation(makeUser("system_admin"));

    expect(contributorIntake?.children?.map((child) => child.route)).toEqual(["upload", "ingestion-jobs"]);
    expect(contributorLibrary?.children?.map((child) => child.route)).toEqual(["document-overview", "documents", "knowledge-spaces", "document-trash"]);
    expect(contributorReview?.badge).toBe("review");
    expect(spaceAdminIntake?.children?.map((child) => child.route)).toEqual(["upload", "document-extraction", "database-connectors", "ingestion-jobs"]);
    expect(spaceAdminReview?.badge).toBe("review");
    expect(spaceAdminNavigation.some((item) => item.id === "users")).toBe(true);
    expect(reviewerIntake?.children?.map((child) => child.route)).toEqual(["upload", "ingestion-jobs"]);
    expect(reviewerLibrary).toBeUndefined();
    expect(memberLibrary?.children?.map((child) => child.route)).toEqual(["document-overview", "documents", "knowledge-spaces", "document-trash"]);
    expect(reviewQueue?.badge).toBe("review");
    expect(evaluations?.label).toBe("RAG Evaluation");
    expect(settings?.label).toBe("Runtime Settings");
    expect(systemAdminNavigation.some((item) => item.id === "evaluations")).toBe(false);
    expect(systemAdminNavigation.some((item) => item.id === "settings")).toBe(false);
    expect(systemAdminNavigation.some((item) => item.id === "users")).toBe(true);
    expect(navigationGroupForRoute("ingestion-jobs")).toBe("document-intake");
    expect(navigationGroupForRoute("database-connectors")).toBe("document-intake");
    expect(navigationGroupForRoute("document-overview")).toBe("document-library");
    expect(navigationGroupForRoute("documents")).toBe("document-library");
    expect(navigationGroupForRoute("document-trash")).toBe("document-library");
    expect(navigationGroupForRoute("ingestion-health")).toBe("overview");
  });
});

function makeUser(accountType: AccountType, clearanceLevel: ClearanceLevel = "COSMIC_TOP_SECRET"): User {
  return {
    user_id: `user-${accountType}`,
    email: `${accountType}@example.com`,
    account_type: accountType,
    group_paths: ["/finance"],
    clearance_level: clearanceLevel,
    permission_version: 1,
    must_change_password: false,
  };
}
