type NumericPreferenceOptions = {
  fallback: number;
  max: number;
  min: number;
};

type StringPreferenceOptions<T extends string> = {
  allowed: readonly T[];
  fallback: T;
};

type StorageLike = Pick<Storage, "getItem" | "setItem">;

export function readStoredBoolean(key: string, fallback: boolean, storage: StorageLike | null = browserLocalStorage()): boolean {
  try {
    const value = storage?.getItem(key);
    if (value === "true") return true;
    if (value === "false") return false;
    return fallback;
  } catch {
    return fallback;
  }
}

export function writeStoredBoolean(key: string, value: boolean, storage: StorageLike | null = browserLocalStorage()): void {
  try {
    storage?.setItem(key, value ? "true" : "false");
  } catch {
    // Preference persistence is optional; the UI should keep working without it.
  }
}

export function readStoredNumber(key: string, options: NumericPreferenceOptions, storage: StorageLike | null = browserLocalStorage()): number {
  try {
    const storedValue = storage?.getItem(key);
    if (storedValue === null || storedValue === undefined || storedValue.trim() === "") return options.fallback;
    const value = Number(storedValue);
    if (!Number.isFinite(value)) return options.fallback;
    return Math.min(options.max, Math.max(options.min, value));
  } catch {
    return options.fallback;
  }
}

export function writeStoredNumber(key: string, value: number, storage: StorageLike | null = browserLocalStorage()): void {
  try {
    storage?.setItem(key, String(value));
  } catch {
    // Preference persistence is optional; the UI should keep working without it.
  }
}

export function readStoredString<T extends string>(key: string, options: StringPreferenceOptions<T>, storage: StorageLike | null = browserLocalStorage()): T {
  try {
    const value = storage?.getItem(key);
    if (value && (options.allowed as readonly string[]).includes(value)) return value as T;
    return options.fallback;
  } catch {
    return options.fallback;
  }
}

export function writeStoredString(key: string, value: string, storage: StorageLike | null = browserLocalStorage()): void {
  try {
    storage?.setItem(key, value);
  } catch {
    // Preference persistence is optional; the UI should keep working without it.
  }
}

function browserLocalStorage(): StorageLike | null {
  if (typeof window === "undefined") return null;
  return window.localStorage;
}
