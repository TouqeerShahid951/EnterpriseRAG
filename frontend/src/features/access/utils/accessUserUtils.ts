import { accountTypeLabel, clearanceLevelLabel, clearanceLevelsAssignableBy, defaultClearanceLevel } from "@/lib/auth/authz";
import type { AccountType, ClearanceLevel, User as AuthUser, UserAdmin } from "@/types/api";

export function matchesUser(user: UserAdmin, search: string): boolean {
  const query = search.toLowerCase().trim();
  if (!query) return true;
  return (
    user.name.toLowerCase().includes(query) ||
    user.email.toLowerCase().includes(query) ||
    accountTypeLabel(user.account_type).toLowerCase().includes(query) ||
    clearanceLevelLabel(user.clearance_level).toLowerCase().includes(query) ||
    user.group_paths.some((path) => path.toLowerCase().includes(query))
  );
}

export function createUserDraft(clearanceLevel: ClearanceLevel): UserDraft {
  return {
    accountType: "member",
    clearanceLevel,
    email: "",
    groupPaths: [],
    initialPassword: generateInitialPassword(),
    isActive: true,
    name: "",
  };
}

export function defaultAssignableClearance(user: AuthUser): ClearanceLevel {
  const assignable = clearanceLevelsAssignableBy(user);
  if (assignable.includes(defaultClearanceLevel)) return defaultClearanceLevel;
  return assignable.at(-1) ?? defaultClearanceLevel;
}

export function isGlobalAccountType(accountType: AccountType): boolean {
  return accountType === "platform_admin" || accountType === "system_admin";
}

export function generateInitialPassword(length = 16): string {
  const requiredSets = ["ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnopqrstuvwxyz", "23456789", "!@#$%"];
  const allCharacters = requiredSets.join("");
  const characters = [
    ...requiredSets.map((set) => pickCharacter(set)),
    ...Array.from({ length: Math.max(0, length - requiredSets.length) }, () => pickCharacter(allCharacters)),
  ];

  for (let index = characters.length - 1; index > 0; index -= 1) {
    const swapIndex = randomIndex(index + 1);
    [characters[index], characters[swapIndex]] = [characters[swapIndex], characters[index]];
  }

  return characters.join("");
}

function pickCharacter(characters: string): string {
  return characters[randomIndex(characters.length)];
}

function randomIndex(max: number): number {
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    const values = new Uint32Array(1);
    crypto.getRandomValues(values);
    return values[0] % max;
  }
  return Math.floor(Math.random() * max);
}

export type CopyState = "idle" | "copied" | "failed";

export type UserPanelState = { kind: "create-user" } | { kind: "edit-user"; user: UserAdmin } | null;

export type UserDraft = {
  accountType: AccountType;
  clearanceLevel: ClearanceLevel;
  email: string;
  groupPaths: string[];
  initialPassword: string;
  isActive: boolean;
  name: string;
};
