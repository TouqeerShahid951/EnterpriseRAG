import { describe, expect, it } from "vitest";

import { isDocumentWorkspaceEmpty } from "./PrudentiaDocumentOverviewPage";

const emptyWorkspace = {
  documentsCount: 0,
  documentsLoading: false,
  jobsKnown: true,
  jobsTotal: 0,
  trashCount: 0,
  trashKnown: true,
  uploadJobsCount: 0,
};

describe("document overview empty-state detection", () => {
  it("shows onboarding only when every visible source confirms an empty workspace", () => {
    expect(isDocumentWorkspaceEmpty(emptyWorkspace)).toBe(true);
  });

  it("keeps the operational dashboard while data is loading or incomplete", () => {
    expect(isDocumentWorkspaceEmpty({ ...emptyWorkspace, documentsLoading: true })).toBe(false);
    expect(isDocumentWorkspaceEmpty({ ...emptyWorkspace, jobsKnown: false })).toBe(false);
    expect(isDocumentWorkspaceEmpty({ ...emptyWorkspace, trashKnown: false })).toBe(false);
  });

  it("keeps the operational dashboard when any corpus activity exists", () => {
    expect(isDocumentWorkspaceEmpty({ ...emptyWorkspace, documentsCount: 1 })).toBe(false);
    expect(isDocumentWorkspaceEmpty({ ...emptyWorkspace, jobsTotal: 1 })).toBe(false);
    expect(isDocumentWorkspaceEmpty({ ...emptyWorkspace, trashCount: 1 })).toBe(false);
    expect(isDocumentWorkspaceEmpty({ ...emptyWorkspace, uploadJobsCount: 1 })).toBe(false);
  });
});
