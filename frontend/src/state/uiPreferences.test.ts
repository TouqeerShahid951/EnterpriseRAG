import { describe, expect, it } from "vitest";

import { readStoredBoolean, readStoredNumber, readStoredString, writeStoredBoolean, writeStoredNumber, writeStoredString } from "./uiPreferences";

describe("ui preference storage", () => {
  it("reads booleans with fallbacks for missing and invalid values", () => {
    const storage = new MemoryStorage();

    expect(readStoredBoolean("sidebar", true, storage)).toBe(true);
    storage.setItem("sidebar", "false");
    expect(readStoredBoolean("sidebar", true, storage)).toBe(false);
    storage.setItem("sidebar", "maybe");
    expect(readStoredBoolean("sidebar", true, storage)).toBe(true);
  });

  it("writes booleans as stable string values", () => {
    const storage = new MemoryStorage();

    writeStoredBoolean("history", true, storage);
    expect(storage.getItem("history")).toBe("true");
    writeStoredBoolean("history", false, storage);
    expect(storage.getItem("history")).toBe("false");
  });

  it("reads and writes validated string preferences", () => {
    const storage = new MemoryStorage();
    const options = { allowed: ["auto", "corpus_only", "db_only", "hybrid"] as const, fallback: "auto" as const };

    expect(readStoredString("source-mode", options, storage)).toBe("auto");
    writeStoredString("source-mode", "hybrid", storage);
    expect(readStoredString("source-mode", options, storage)).toBe("hybrid");
    storage.setItem("source-mode", "invalid");
    expect(readStoredString("source-mode", options, storage)).toBe("auto");
  });

  it("clamps numeric preferences and falls back safely", () => {
    const storage = new MemoryStorage();

    expect(readStoredNumber("width", { fallback: 280, min: 240, max: 400 }, storage)).toBe(280);
    storage.setItem("width", "640");
    expect(readStoredNumber("width", { fallback: 280, min: 240, max: 400 }, storage)).toBe(400);
    storage.setItem("width", "200");
    expect(readStoredNumber("width", { fallback: 280, min: 240, max: 400 }, storage)).toBe(240);
    storage.setItem("width", "wide");
    expect(readStoredNumber("width", { fallback: 280, min: 240, max: 400 }, storage)).toBe(280);
  });

  it("ignores storage failures", () => {
    const storage = new ThrowingStorage();

    expect(readStoredBoolean("sidebar", false, storage)).toBe(false);
    expect(readStoredNumber("width", { fallback: 280, min: 240, max: 400 }, storage)).toBe(280);
    expect(readStoredString("source-mode", { allowed: ["auto", "hybrid"] as const, fallback: "auto" }, storage)).toBe("auto");
    expect(() => writeStoredBoolean("sidebar", true, storage)).not.toThrow();
    expect(() => writeStoredNumber("width", 320, storage)).not.toThrow();
    expect(() => writeStoredString("source-mode", "hybrid", storage)).not.toThrow();
  });
});

class MemoryStorage implements Pick<Storage, "getItem" | "setItem"> {
  private values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

class ThrowingStorage implements Pick<Storage, "getItem" | "setItem"> {
  getItem(): string | null {
    throw new Error("storage unavailable");
  }

  setItem(): void {
    throw new Error("storage unavailable");
  }
}
