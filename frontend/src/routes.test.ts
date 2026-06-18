import { describe, expect, it } from "vitest";

import { canAssignAccountType, canUploadToSpace, canWriteDocument } from "./authz";
import { canAccessRoute, defaultRouteForUser, navigationGroupForRoute, routeFromLocation, visibleNavigation, type RouteId } from "./routes";
import type { AccountType, ClearanceLevel, User } from "./types/api";

describe("account type route access", () => {
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
    ["space_admin", ["chat", "upload", "document-overview", "knowledge-spaces", "documents", "document-trash", "document-extraction", "ingestion-health", "ingestion-jobs"], ["access", "settings", "review"]],
    ["contributor", ["chat", "upload", "document-overview", "knowledge-spaces", "documents", "document-trash", "ingestion-health", "ingestion-jobs"], ["access", "settings", "review", "document-extraction"]],
    ["reviewer", ["chat", "review", "document-overview", "knowledge-spaces", "documents", "document-trash", "ingestion-health", "ingestion-jobs"], ["access", "settings", "upload", "document-extraction"]],
    ["auditor", ["activity-log", "document-overview", "knowledge-spaces", "documents", "document-trash", "ingestion-health", "ingestion-jobs"], ["chat", "upload", "review", "settings", "document-extraction"]],
    ["member", ["chat", "document-overview", "knowledge-spaces", "documents", "document-trash", "ingestion-health", "ingestion-jobs"], ["access", "settings", "upload", "review", "document-extraction"]],
  ] as [AccountType, RouteId[], RouteId[]][])("applies scoped route access for %s", (accountType, allowed, denied) => {
    const user = makeUser(accountType);

    for (const route of allowed) expect(canAccessRoute(user, route)).toBe(true);
    for (const route of denied) expect(canAccessRoute(user, route)).toBe(false);
  });

  it("uses a non-chat default route for non-query roles", () => {
    expect(defaultRouteForUser(makeUser("user_manager"))).toBe("access");
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
    expect(canWriteDocument(makeUser("reviewer"), "/finance")).toBe(false);
  });

  it("prevents lower admin roles from assigning platform-only roles", () => {
    expect(canAssignAccountType(makeUser("platform_admin"), "system_admin")).toBe(true);
    expect(canAssignAccountType(makeUser("system_admin"), "platform_admin")).toBe(false);
    expect(canAssignAccountType(makeUser("system_admin"), "system_admin")).toBe(true);
    expect(canAssignAccountType(makeUser("user_manager"), "system_admin")).toBe(false);
    expect(canAssignAccountType(makeUser("user_manager"), "space_admin")).toBe(true);
  });

  it("redirects legacy Knowledge Space tabs to focused routes", () => {
    expect(routeFromLocation("/knowledge-spaces", "?tab=documents")).toBe("documents");
    expect(routeFromLocation("/knowledge-spaces", "?tab=trash")).toBe("document-trash");
    expect(routeFromLocation("/knowledge-spaces", "?tab=jobs")).toBe("ingestion-jobs");
    expect(routeFromLocation("/knowledge-spaces", "?space=%2Ffinance")).toBe("knowledge-spaces");
    expect(routeFromLocation("/documents/overview", "")).toBe("document-overview");
  });

  it("filters nested navigation by role and resolves active groups", () => {
    const contributorNavigation = visibleNavigation(makeUser("contributor"));
    const contributorIntake = contributorNavigation.find((item) => item.id === "document-intake");
    const contributorLibrary = contributorNavigation.find((item) => item.id === "document-library");
    const spaceAdminNavigation = visibleNavigation(makeUser("space_admin"));
    const spaceAdminIntake = spaceAdminNavigation.find((item) => item.id === "document-intake");
    const reviewerNavigation = visibleNavigation(makeUser("reviewer"));
    const reviewerIntake = reviewerNavigation.find((item) => item.id === "document-intake");
    const reviewerLibrary = reviewerNavigation.find((item) => item.id === "document-library");
    const memberNavigation = visibleNavigation(makeUser("member"));
    const memberLibrary = memberNavigation.find((item) => item.id === "document-library");
    const reviewQueue = reviewerNavigation.find((item) => item.id === "review");
    const adminNavigation = visibleNavigation(makeUser("platform_admin"));
    const evaluations = adminNavigation.find((item) => item.id === "evaluations");
    const systemAdminNavigation = visibleNavigation(makeUser("system_admin"));

    expect(contributorIntake?.children?.map((child) => child.route)).toEqual(["upload", "ingestion-jobs"]);
    expect(contributorLibrary?.children?.map((child) => child.route)).toEqual(["document-overview", "documents", "knowledge-spaces", "document-trash"]);
    expect(spaceAdminIntake?.children?.map((child) => child.route)).toEqual(["upload", "document-extraction", "ingestion-jobs"]);
    expect(reviewerIntake?.children?.map((child) => child.route)).toEqual(["ingestion-jobs"]);
    expect(reviewerLibrary?.children?.map((child) => child.route)).toEqual(["document-overview", "documents", "knowledge-spaces", "document-trash"]);
    expect(memberLibrary?.children?.map((child) => child.route)).toEqual(["document-overview", "documents", "knowledge-spaces", "document-trash"]);
    expect(reviewQueue?.badge).toBe("review");
    expect(evaluations?.label).toBe("RAG Evaluation");
    expect(systemAdminNavigation.some((item) => item.id === "evaluations")).toBe(false);
    expect(systemAdminNavigation.some((item) => item.id === "settings")).toBe(false);
    expect(systemAdminNavigation.some((item) => item.id === "users")).toBe(true);
    expect(navigationGroupForRoute("ingestion-jobs")).toBe("document-intake");
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
