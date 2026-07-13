const DEFAULT_IDLE_TIMEOUT_MINUTES = 30;
const DEFAULT_IDLE_WARNING_SECONDS = 120;

type AuthSessionEnv = {
  readonly VITE_AUTH_IDLE_TIMEOUT_MINUTES?: string;
  readonly VITE_AUTH_IDLE_WARNING_SECONDS?: string;
};

export type AuthSessionTiming = {
  timeoutMs: number;
  warningMs: number;
};

export function authSessionTimingFromEnv(env: AuthSessionEnv = import.meta.env): AuthSessionTiming {
  const timeoutMs = readPositiveNumber(env.VITE_AUTH_IDLE_TIMEOUT_MINUTES, DEFAULT_IDLE_TIMEOUT_MINUTES) * 60_000;
  const requestedWarningMs = readPositiveNumber(env.VITE_AUTH_IDLE_WARNING_SECONDS, DEFAULT_IDLE_WARNING_SECONDS) * 1000;
  const warningMs = Math.min(requestedWarningMs, Math.max(1000, Math.floor(timeoutMs / 2)));
  return { timeoutMs, warningMs };
}

export function idleRemainingSeconds(lastTouchedAt: number, timeoutMs: number, now = Date.now()): number {
  return Math.max(0, Math.ceil((lastTouchedAt + timeoutMs - now) / 1000));
}

export function shouldShowIdleWarning(lastTouchedAt: number, timing: AuthSessionTiming, now = Date.now()): boolean {
  const remainingMs = lastTouchedAt + timing.timeoutMs - now;
  return remainingMs > 0 && remainingMs <= timing.warningMs;
}

export function formatIdleCountdown(totalSeconds: number): string {
  const safeSeconds = Math.max(0, Math.ceil(totalSeconds));
  const minutes = Math.floor(safeSeconds / 60);
  const seconds = safeSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function readPositiveNumber(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}
