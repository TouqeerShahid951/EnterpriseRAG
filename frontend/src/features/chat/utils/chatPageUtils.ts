import type { SourceAnchor, Document } from "@/types/api";
import type { ChatTurn } from "@/types/chat";
import { isDocumentInSpace } from "@/lib/utils/groups";

const CHAT_BOTTOM_FOLLOW_THRESHOLD_PX = 96;

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
