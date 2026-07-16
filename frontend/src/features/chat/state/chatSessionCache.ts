import type { InfiniteData } from "@tanstack/react-query";
import type { ChatTurn, SavedChatSessionPage, SavedChatSessionSummary } from "@/types/chat";
import { createId } from "@/lib/utils/ids";

export type ChatHistoryQueryData = InfiniteData<SavedChatSessionPage, number>;

export type ChatSessionTurnCache = Record<string, ChatTurn[]>;

export function mergeSavedSessionsWithLocal(savedSessions: SavedChatSessionSummary[], localSessions: SavedChatSessionSummary[], generatingSessionId: string | null = null): SavedChatSessionSummary[] {
  const savedIds = new Set(savedSessions.map((session) => session.id));
  const visibleLocalSessions = localSessions.filter((session) => session.id === generatingSessionId || !savedIds.has(session.id));
  const seen = new Set<string>();
  return [...visibleLocalSessions, ...savedSessions]
    .filter((session) => {
      if (seen.has(session.id)) return false;
      seen.add(session.id);
      return true;
    })
    .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
}

export function updateChatSessionTurns(cache: ChatSessionTurnCache, sessionId: string, updater: (turns: ChatTurn[]) => ChatTurn[]): ChatSessionTurnCache {
  return { ...cache, [sessionId]: updater(cache[sessionId] ?? []) };
}

export function removeCachedSession(cache: ChatSessionTurnCache, sessionId: string): ChatSessionTurnCache {
  if (!(sessionId in cache)) return cache;
  const { [sessionId]: _removed, ...remaining } = cache;
  return remaining;
}

export function upsertLocalSessionSummary(summaries: SavedChatSessionSummary[], summary: SavedChatSessionSummary): SavedChatSessionSummary[] {
  const next = summaries.filter((session) => session.id !== summary.id);
  return [summary, ...next];
}

export function questionCountForTurns(turns: ChatTurn[]): number {
  return turns.filter((turn) => turn.role === "user").length;
}

export function compactSessionTitle(value: string): string {
  const trimmed = value.trim() || "New chat";
  return trimmed.length > 52 ? `${trimmed.slice(0, 49).trimEnd()}...` : trimmed;
}

export function createUserTurn(content: string, createdAt = new Date().toISOString()): ChatTurn {
  return { id: createId("user"), role: "user", content, createdAt };
}

export function removeSessionFromPages(current: ChatHistoryQueryData | undefined, sessionId: string): ChatHistoryQueryData | undefined {
  if (!current) return current;
  const containedSession = current.pages.some((page) => page.items.some((session) => session.id === sessionId));
  if (!containedSession) return current;
  return {
    ...current,
    pages: current.pages.map((page) => ({
      ...page,
      total: Math.max(0, page.total - 1),
      items: page.items.filter((session) => session.id !== sessionId),
    })),
  };
}
