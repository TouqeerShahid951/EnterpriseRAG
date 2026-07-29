import { describe, expect, it } from "vitest";

import { buildSpaceOverviewRows, canTransferDocumentOwner, ownershipTransferOptions, spaceAttentionCount } from "../utils/documentPageUtils";
import type { Document, DocumentOverviewSpace, User } from "@/types/api";
import type { GroupOption } from "@/lib/utils/groups";

describe("document ownership transfer helpers", () => {
  it("lets global admins target any space except the current owner", () => {
    const options = ownershipTransferOptions(_user("platform_admin", []), "/legal", _spaces());

    expect(options.map((space) => space.path)).toEqual(["/finance", "/ops"]);
  });

  it("lets space admins transfer only between exact managed spaces", () => {
    const user = _user("space_admin", ["/legal", "/finance"]);

    expect(canTransferDocumentOwner(user, _document("/legal"))).toBe(true);
    expect(ownershipTransferOptions(user, "/legal", _spaces()).map((space) => space.path)).toEqual(["/finance"]);
  });

  it("hides transfer controls for contributors and unmanaged owner spaces", () => {
    const contributor = _user("contributor", ["/legal"]);
    const spaceAdmin = _user("space_admin", ["/finance"]);

    expect(canTransferDocumentOwner(contributor, _document("/legal"))).toBe(false);
    expect(canTransferDocumentOwner(spaceAdmin, _document("/legal"))).toBe(false);
    expect(ownershipTransferOptions(spaceAdmin, "/legal", _spaces())).toEqual([]);
  });
});

describe("Knowledge Space overview counts", () => {
  it("uses the server document snapshot and does not count processing as attention", () => {
    const rows = buildSpaceOverviewRows(_spaces(), [_overviewSpace("/finance", { processing_current: 2 }), _overviewSpace("/finance/legal", { failed_current: 1 })]);
    const finance = rows.find((row) => row.space.path === "/finance")!;

    expect(finance.documentsCount).toBe(2);
    expect(finance.processingCount).toBe(2);
    expect(spaceAttentionCount(finance)).toBe(1);
  });
});

function _user(accountType: User["account_type"], groupPaths: string[]): User {
  return {
    user_id: "user-1",
    email: "user@example.test",
    account_type: accountType,
    clearance_level: "NATO_SECRET",
    group_paths: groupPaths,
    permission_version: 1,
  };
}

function _document(ownerGroupPath: string): Document {
  return {
    id: "doc-1",
    title: "Document.pdf",
    doc_type: "report",
    group_path: ownerGroupPath,
    owner_group_path: ownerGroupPath,
    shared_group_paths: [],
    access_group_paths: [ownerGroupPath],
    governance_owner: "space",
    clearance_level: "NATO_RESTRICTED",
    effective_date: null,
    expiry_date: null,
    description: null,
    summary: null,
    language: null,
    topics: [],
    llm_topics: [],
    auto_doc_type: null,
    extracted_dates: {},
    metadata_flags: {},
    entities: [],
    cross_references: [],
    claims: [],
    is_current: true,
    ingest_status: "complete",
    uploaded_by: "user-1",
    superseded_by: null,
    deleted_at: null,
    created_at: "2026-07-06T00:00:00Z",
  };
}

function _spaces(): GroupOption[] {
  return [
    { depth: 0, name: "Legal", parentPath: null, path: "/legal" },
    { depth: 0, name: "Finance", parentPath: null, path: "/finance" },
    { depth: 0, name: "Ops", parentPath: null, path: "/ops" },
  ];
}

function _overviewSpace(groupPath: string, values: Partial<DocumentOverviewSpace>): DocumentOverviewSpace {
  return {
    group_path: groupPath,
    library_documents: 1,
    current_versions: 1,
    processing_current: 0,
    review_current: 0,
    failed_current: 0,
    unknown_current: 0,
    ...values,
  };
}
