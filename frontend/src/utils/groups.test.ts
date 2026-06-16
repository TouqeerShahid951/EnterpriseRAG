import { describe, expect, it } from "vitest";

import { collectDescendantPaths, countGroups, flattenGroups } from "./groups";
import type { Group } from "../types/api";

describe("group utilities", () => {
  it("handles legacy group payloads without children arrays", () => {
    const groups = [
      { name: "Finance", path: "/finance" },
      { name: "Operations", path: "/ops", children: [{ name: "Field", path: "/ops/field" }] },
    ] as unknown as Group[];

    expect(flattenGroups(groups).map((group) => group.path)).toEqual(["/finance", "/ops", "/ops/field"]);
    expect(collectDescendantPaths(groups, "/finance")).toEqual([]);
    expect(countGroups(groups)).toBe(3);
  });
});
