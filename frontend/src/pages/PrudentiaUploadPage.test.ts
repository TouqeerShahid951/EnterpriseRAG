import { describe, expect, it } from "vitest";

import { canShareUploadAcrossSpaces, uploadShareTargetPaths } from "./PrudentiaUploadPage";
import type { User } from "../types/api";

describe("upload shared Knowledge Space helpers", () => {
  it("lets global admins share uploads to any non-owner space", () => {
    expect(canShareUploadAcrossSpaces(_user("system_admin", []), "")).toBe(false);
    expect(uploadShareTargetPaths(_user("system_admin", []), "/legal", _spaces())).toEqual(["/finance", "/ops"]);
  });

  it("lets space admins share only from and to exact managed spaces", () => {
    const user = _user("space_admin", ["/legal", "/finance"]);

    expect(canShareUploadAcrossSpaces(user, "/legal")).toBe(true);
    expect(uploadShareTargetPaths(user, "/legal", _spaces())).toEqual(["/finance"]);
  });

  it("does not expose shared upload targets to contributors", () => {
    const user = _user("contributor", ["/legal"]);

    expect(canShareUploadAcrossSpaces(user, "/legal")).toBe(false);
    expect(uploadShareTargetPaths(user, "/legal", _spaces())).toEqual([]);
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

function _spaces() {
  return [{ path: "/legal" }, { path: "/finance" }, { path: "/ops" }];
}
