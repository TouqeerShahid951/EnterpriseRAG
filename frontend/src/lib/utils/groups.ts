import type { Group } from "@/types/api";

const GROUP_PATH_PATTERN = /^\/[a-z0-9][a-z0-9-]*$/;

export type GroupOption = {
  depth: number;
  name: string;
  parentPath: string | null;
  path: string;
};

export function flattenGroups(groups: Group[] = [], parentPath: string | null = null, depth = 0): GroupOption[] {
  return groups.flatMap((group) => [
    { depth, name: group.name, parentPath, path: group.path },
    ...flattenGroups(group.children ?? [], group.path, depth + 1),
  ]);
}

export function collectDescendantPaths(groups: Group[] = [], path: string): string[] {
  for (const group of groups) {
    if (group.path === path) return flattenGroups(group.children ?? []).map((child) => child.path);
    const descendants = collectDescendantPaths(group.children ?? [], path);
    if (descendants.length > 0) return descendants;
  }
  return [];
}

export function countGroups(groups: Group[] = []): number {
  return flattenGroups(groups).length;
}

export function nextSelectedGroups(selectedPaths: string[], groupPath: string, checked: boolean, groupOptions: GroupOption[]): string[] {
  const next = new Set(selectedPaths);
  if (checked) next.add(groupPath);
  else next.delete(groupPath);
  return groupOptions.map((group) => group.path).filter((path) => next.has(path));
}

export function buildGroupPath(parentPath: string, name: string): string {
  const segment = slugPathSegment(name);
  if (!segment) return "";
  return `${parentPath || ""}/${segment}`.replace(/\/+/g, "/");
}

export function groupPathIssue(path: string, pathExists: boolean): string | null {
  const trimmed = path.trim();
  if (!trimmed) return "Knowledge space path is required.";
  if (!GROUP_PATH_PATTERN.test(trimmed)) return "Path must be one top-level segment using lowercase letters, numbers, and hyphens.";
  if (pathExists) return "A knowledge space with this path already exists.";
  return null;
}

function displayNameFromPath(path: string): string {
  const segment = path.split("/").filter(Boolean).at(-1) ?? path;
  return segment
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function userSpacesFromPaths(paths: string[] = []): GroupOption[] {
  return paths.map((path) => ({
    depth: Math.max(0, path.split("/").filter(Boolean).length - 1),
    name: displayNameFromPath(path),
    parentPath: parentPathFromPath(path),
    path,
  }));
}

export function isDocumentInSpace(documentGroupPath: string, spacePath: string): boolean {
  return documentGroupPath === spacePath || documentGroupPath.startsWith(`${spacePath}/`);
}

function parentPathFromPath(path: string): string | null {
  const parts = path.split("/").filter(Boolean);
  if (parts.length <= 1) return null;
  return `/${parts.slice(0, -1).join("/")}`;
}

function slugPathSegment(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
