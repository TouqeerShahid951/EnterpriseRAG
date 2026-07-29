import { describe, expect, it } from "vitest";

import { isDocumentWorkspaceEmpty } from "./PrudentiaDocumentOverviewPage";

const emptyWorkspace = {
  jobHistoryKnown: true,
  jobHistoryTotal: 0,
  libraryDocuments: 0,
  overviewKnown: true,
  trash: 0,
};

describe("document overview empty-state detection", () => {
  it("shows onboarding only when every visible source confirms an empty workspace", () => {
    expect(isDocumentWorkspaceEmpty(emptyWorkspace)).toBe(true);
  });

  it("keeps the operational dashboard while data is loading or incomplete", () => {
    expect(isDocumentWorkspaceEmpty({ ...emptyWorkspace, jobHistoryKnown: false })).toBe(false);
    expect(isDocumentWorkspaceEmpty({ ...emptyWorkspace, overviewKnown: false })).toBe(false);
  });

  it("keeps the operational dashboard when any corpus activity exists", () => {
    expect(isDocumentWorkspaceEmpty({ ...emptyWorkspace, libraryDocuments: 1 })).toBe(false);
    expect(isDocumentWorkspaceEmpty({ ...emptyWorkspace, jobHistoryTotal: 1 })).toBe(false);
    expect(isDocumentWorkspaceEmpty({ ...emptyWorkspace, trash: 1 })).toBe(false);
  });
});
