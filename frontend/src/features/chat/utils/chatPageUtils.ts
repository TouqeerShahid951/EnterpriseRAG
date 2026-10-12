import type { SourceAnchor, Document } from "@/types/api";
import type { ChatTurn } from "@/types/chat";
import { isDocumentInSpace } from "@/lib/utils/groups";

const CHAT_BOTTOM_FOLLOW_THRESHOLD_PX = 96;
const REPLY_PREVIEW_MAX_CHARS = 180;

export function replyPreviewForTurn(turn: ChatTurn): string {
  const value = turn.role === "user"
    ? turn.content
    : turn.response?.answer ?? turn.streamText ?? turn.question;
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length > REPLY_PREVIEW_MAX_CHARS
    ? `${compact.slice(0, REPLY_PREVIEW_MAX_CHARS - 1).trimEnd()}…`
    : compact;
}

export function replyLabelForTurn(turn: ChatTurn): string {
  return turn.role === "user" ? "Your question" : "Prudentia AI";
}

export function chatStreamPositionKey(chatTurns: ChatTurn[]): string {
  const lastTurn = chatTurns[chatTurns.length - 1];
  if (!lastTurn) return "empty";
  if (lastTurn.role === "user") return `${lastTurn.id}:${lastTurn.content.length}`;
  return [
    lastTurn.id,
    lastTurn.status,
    lastTurn.progress.length,
    lastTurn.streamText?.length ?? 0,
    lastTurn.response?.sources.length ?? 0,
  ].join(":");
}

export function restoredChatTurnKey(sessionId: string | null, turnId: string | null, chatTurns: ChatTurn[]): string | null {
  return turnId && chatTurns.some((turn) => turn.id === turnId) ? `${sessionId ?? "new"}:${turnId}` : null;
}

export function isNearChatBottom(scrollNode: Pick<HTMLElement, "clientHeight" | "scrollHeight" | "scrollTop">): boolean {
  const distanceFromBottom = scrollNode.scrollHeight - scrollNode.scrollTop - scrollNode.clientHeight;
  return distanceFromBottom <= CHAT_BOTTOM_FOLLOW_THRESHOLD_PX;
}

export function selectedSourceNumber(sources: SourceAnchor[], selectedSource: SourceAnchor | null): number | null {
  if (!selectedSource) return null;
  const index = sources.findIndex((source) => source.doc_id === selectedSource.doc_id && source.chunk_id === selectedSource.chunk_id);
  return index === -1 ? null : index + 1;
}

export function documentsInActiveSpace(documents: Document[], activeSpacePath: string | null): Document[] {
  if (!activeSpacePath) return documents;
  return documents.filter((document) => isDocumentInSpace(document.group_path, activeSpacePath));
}
