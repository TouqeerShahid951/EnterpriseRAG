import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { AUTH_SESSION_EXPIRED_EVENT, AUTH_SESSION_TOUCHED_EVENT } from "../api/client";
import { authApi } from "../api/contracts";
import { getCsrfTokenFromCookie } from "../api/headers";
import { authSessionTimingFromEnv, idleRemainingSeconds, shouldShowIdleWarning } from "./authSessionTiming";

const POST_LOGIN_REDIRECT_STORAGE_KEY = "Prudentia-post-login-redirect";
const AUTH_SESSION_CHANNEL_NAME = "Prudentia-auth-session";
const AUTH_SESSION_MESSAGE_STORAGE_KEY = "Prudentia-auth-session-message";
const AUTH_SESSION_LAST_TOUCHED_STORAGE_KEY = "Prudentia-auth-session-last-touched-at";

export function useAuthSession() {
  const queryClient = useQueryClient();
  const tabId = useRef(createTabId());
  const channelRef = useRef<BroadcastChannel | null>(null);
  const timing = useMemo(() => authSessionTimingFromEnv(), []);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [lastTouchedAt, setLastTouchedAt] = useState(() => readSharedLastTouchedAt() ?? Date.now());
  const [idleWarningRemainingSeconds, setIdleWarningRemainingSeconds] = useState<number | null>(null);
  const hasSessionCookie = Boolean(getCsrfTokenFromCookie());

  const currentUserQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: authApi.currentUser,
    enabled: !sessionExpired && hasSessionCookie,
    retry: false,
  });
  const currentUser = currentUserQuery.isSuccess ? currentUserQuery.data : null;

  const broadcastAuthSessionMessage = useCallback((message: Omit<AuthSessionMessage, "senderId">) => {
    const payload: AuthSessionMessage = {
      ...message,
      senderId: tabId.current,
    };
    channelRef.current?.postMessage(payload);
    writeAuthSessionMessage(payload);
  }, []);

  const markSessionTouched = useCallback((touchedAt = Date.now(), broadcast = true) => {
    setLastTouchedAt((current) => Math.max(current, touchedAt));
    setIdleWarningRemainingSeconds(null);
    setSessionExpired(false);
    if (broadcast) {
      writeSharedLastTouchedAt(touchedAt);
      broadcastAuthSessionMessage({ type: "touched", touchedAt, createdAt: Date.now() });
    }
  }, [broadcastAuthSessionMessage]);

  const expireSession = useCallback((options: ExpireSessionOptions = {}) => {
    if (options.rememberRedirect !== false) rememberPostLoginRedirect();
    setIdleWarningRemainingSeconds(null);
    setSessionExpired(true);
    clearAuthenticatedQueryData(queryClient);
    if (options.broadcast !== false) {
      broadcastAuthSessionMessage({ type: "expired", createdAt: Date.now() });
    }
  }, [broadcastAuthSessionMessage, queryClient]);

  const clearLoggedOutSession = useCallback((broadcast = false) => {
    setSessionExpired(false);
    setIdleWarningRemainingSeconds(null);
    clearPostLoginRedirect();
    clearAuthenticatedQueryData(queryClient);
    if (broadcast) {
      broadcastAuthSessionMessage({ type: "logout", createdAt: Date.now() });
    }
  }, [broadcastAuthSessionMessage, queryClient]);

  const logoutMutation = useMutation({
    mutationFn: authApi.logout,
    onSettled: () => {
      clearLoggedOutSession(true);
    },
  });

  const staySignedInMutation = useMutation({
    mutationFn: authApi.refresh,
    onSuccess: (response) => {
      queryClient.setQueryData(["auth", "me"], response.user);
      markSessionTouched(Date.now(), true);
    },
  });

  useEffect(() => {
    function handleSessionExpired() {
      expireSession();
    }

    function handleSessionTouched() {
      markSessionTouched(Date.now(), true);
    }

    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, handleSessionExpired);
    window.addEventListener(AUTH_SESSION_TOUCHED_EVENT, handleSessionTouched);
    return () => {
      window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, handleSessionExpired);
      window.removeEventListener(AUTH_SESSION_TOUCHED_EVENT, handleSessionTouched);
    };
  }, [expireSession, markSessionTouched]);

  useEffect(() => {
    function handleAuthSessionMessage(message: AuthSessionMessage) {
      if (!isAuthSessionMessage(message) || message.senderId === tabId.current) return;
      if (message.type === "touched") {
        markSessionTouched(message.touchedAt ?? message.createdAt, false);
        return;
      }
      if (message.type === "expired") {
        expireSession({ broadcast: false });
        return;
      }
      clearLoggedOutSession(false);
    }

    function handleStorage(event: StorageEvent) {
      if (event.key === AUTH_SESSION_MESSAGE_STORAGE_KEY && event.newValue) {
        const message = parseAuthSessionMessage(event.newValue);
        if (message) handleAuthSessionMessage(message);
      }
      if (event.key === AUTH_SESSION_LAST_TOUCHED_STORAGE_KEY) {
        const touchedAt = readTimestamp(event.newValue);
        if (touchedAt) markSessionTouched(touchedAt, false);
      }
    }

    if (typeof BroadcastChannel !== "undefined") {
      const channel = new BroadcastChannel(AUTH_SESSION_CHANNEL_NAME);
      channelRef.current = channel;
      channel.addEventListener("message", (event) => handleAuthSessionMessage(event.data));
    }

    window.addEventListener("storage", handleStorage);
    return () => {
      window.removeEventListener("storage", handleStorage);
      channelRef.current?.close();
      channelRef.current = null;
    };
  }, [clearLoggedOutSession, expireSession, markSessionTouched]);

  useEffect(() => {
    if (currentUser) {
      markSessionTouched(readSharedLastTouchedAt() ?? Date.now(), true);
    } else {
      setIdleWarningRemainingSeconds(null);
    }
  }, [currentUser?.user_id, markSessionTouched]);

  useEffect(() => {
    if (!currentUser || sessionExpired) {
      setIdleWarningRemainingSeconds(null);
      return;
    }

    function updateIdleWarning() {
      const sharedTouchedAt = readSharedLastTouchedAt();
      const effectiveTouchedAt = sharedTouchedAt && sharedTouchedAt > lastTouchedAt ? sharedTouchedAt : lastTouchedAt;
      if (effectiveTouchedAt > lastTouchedAt) {
        setLastTouchedAt(effectiveTouchedAt);
      }

      const remainingSeconds = idleRemainingSeconds(effectiveTouchedAt, timing.timeoutMs);
      if (remainingSeconds <= 0) {
        expireSession();
        return;
      }
      setIdleWarningRemainingSeconds(shouldShowIdleWarning(effectiveTouchedAt, timing) ? remainingSeconds : null);
    }

    updateIdleWarning();
    const interval = window.setInterval(updateIdleWarning, 1000);
    document.addEventListener("visibilitychange", updateIdleWarning);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", updateIdleWarning);
    };
  }, [currentUser, expireSession, lastTouchedAt, sessionExpired, timing]);

  function authChanged() {
    markSessionTouched(Date.now(), true);
    setSessionExpired(false);
    void queryClient.invalidateQueries({ queryKey: ["auth"] });
    void queryClient.invalidateQueries({ queryKey: ["admin"] });
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
  }

  return {
    authChanged,
    clearSessionExpired: () => setSessionExpired(false),
    consumePostLoginRedirect,
    currentUser,
    currentUserQuery,
    idleWarning: {
      open: idleWarningRemainingSeconds !== null,
      remainingSeconds: idleWarningRemainingSeconds ?? 0,
      timeoutMinutes: Math.round(timing.timeoutMs / 60_000),
    },
    logoutMutation,
    sessionExpired,
    staySignedIn: () => staySignedInMutation.mutate(),
    staySignedInMutation,
  };
}

function clearAuthenticatedQueryData(queryClient: QueryClient) {
  queryClient.setQueryData(["auth", "me"], null);
  queryClient.removeQueries({
    predicate: (query) => query.queryKey[0] !== "auth",
  });
  void queryClient.invalidateQueries({ queryKey: ["auth"] });
}

function rememberPostLoginRedirect() {
  if (typeof window === "undefined") return;
  const target = `${window.location.pathname}${window.location.search}`;
  if (!target || target === "/" || target.startsWith("/login")) return;
  try {
    window.sessionStorage.setItem(POST_LOGIN_REDIRECT_STORAGE_KEY, target);
  } catch {
    // Redirect restoration is helpful, not required for secure session expiry.
  }
}

function consumePostLoginRedirect(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const target = window.sessionStorage.getItem(POST_LOGIN_REDIRECT_STORAGE_KEY);
    window.sessionStorage.removeItem(POST_LOGIN_REDIRECT_STORAGE_KEY);
    return target;
  } catch {
    return null;
  }
}

function clearPostLoginRedirect() {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(POST_LOGIN_REDIRECT_STORAGE_KEY);
  } catch {
    // Ignore storage failures; logout still clears in-memory auth state.
  }
}

function createTabId(): string {
  return `tab-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function writeSharedLastTouchedAt(touchedAt: number) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(AUTH_SESSION_LAST_TOUCHED_STORAGE_KEY, String(touchedAt));
  } catch {
    // Cross-tab warning sync is helpful, but local state still protects this tab.
  }
}

function readSharedLastTouchedAt(): number | null {
  if (typeof window === "undefined") return null;
  try {
    return readTimestamp(window.localStorage.getItem(AUTH_SESSION_LAST_TOUCHED_STORAGE_KEY));
  } catch {
    return null;
  }
}

function writeAuthSessionMessage(message: AuthSessionMessage) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(AUTH_SESSION_MESSAGE_STORAGE_KEY, JSON.stringify(message));
  } catch {
    // BroadcastChannel may still be available; otherwise this tab has already handled the event.
  }
}

function parseAuthSessionMessage(value: string): AuthSessionMessage | null {
  try {
    const parsed = JSON.parse(value);
    return isAuthSessionMessage(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function isAuthSessionMessage(value: unknown): value is AuthSessionMessage {
  if (!value || typeof value !== "object") return false;
  const message = value as Partial<AuthSessionMessage>;
  return (
    typeof message.senderId === "string"
    && typeof message.createdAt === "number"
    && (message.type === "touched" || message.type === "expired" || message.type === "logout")
  );
}

function readTimestamp(value: string | null): number | null {
  if (!value) return null;
  const timestamp = Number(value);
  return Number.isFinite(timestamp) && timestamp > 0 ? timestamp : null;
}

type ExpireSessionOptions = {
  broadcast?: boolean;
  rememberRedirect?: boolean;
};

type AuthSessionMessage = {
  createdAt: number;
  senderId: string;
  touchedAt?: number;
  type: "expired" | "logout" | "touched";
};
