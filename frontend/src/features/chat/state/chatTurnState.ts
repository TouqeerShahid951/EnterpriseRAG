import type { ArtifactJobSummary, QuerySourceMode, RAGResponse } from "@/types/api";
import type { AssistantTurn, ChatTurn, QueryProgressItem } from "@/types/chat";
import { compactText } from "@/features/chat/state/chatStreamReducer";
import { createId } from "@/lib/utils/ids";

export function createAssistantTurn(
  question: string,
  documentIds: string[] = [],
  groupPath: string | null = null,
  sourceMode: QuerySourceMode = "auto",
  querySourceId: string | null = null,
): AssistantTurn {
  return {
    id: createId("assistant"),
    role: "assistant",
    status: "pending",
    question,
    groupPath,
    documentIds,
    sourceMode,
    querySourceId,
    progress: initialProgressForQuestion(question, "Opening retrieval graph", documentIds, groupPath),
    createdAt: new Date().toISOString(),
  };
}

export type SourceSubmitOverride = {
  sourceMode?: QuerySourceMode;
  querySourceId?: string | null;
  allowSourceExpansion?: boolean;
  documentIds?: string[];
};

export function initialProgressForQuestion(question: string, graphLabel = "Opening retrieval graph", documentIds: string[] = [], groupPath: string | null = null): QueryProgressItem[] {
  return [
    {
      id: createId("progress"),
      label: "Analyzing question",
      detail: compactText(question),
      kind: "system",
    },
    {
      id: createId("progress"),
      label: graphLabel,
      detail: documentIds.length ? "Preparing tagged document search" : `Preparing ${groupPath ?? "Knowledge Space"} search`,
      kind: "node",
    },
  ];
}

export function replaceAssistantTurn(turns: ChatTurn[], assistantTurnId: string, response: RAGResponse): ChatTurn[] {
  return turns.map((turn) =>
    turn.id === assistantTurnId && turn.role === "assistant" ? { ...turn, status: "complete", response } : turn,
  );
}

export function activeArtifactJobs(turns: ChatTurn[]): string[] {
  const ids = new Set<string>();
  for (const turn of turns) {
    if (turn.role !== "assistant") continue;
    const job = turn.response?.artifact_job;
    if (job && !isArtifactJobTerminal(job.status)) {
      ids.add(job.id);
    }
  }
  return [...ids];
}

export function mergeArtifactJobIntoTurns(turns: ChatTurn[], job: ArtifactJobSummary): ChatTurn[] {
  return turns.map((turn) => {
    if (turn.role !== "assistant" || !turn.response?.artifact_job || turn.response.artifact_job.id !== job.id) {
      return turn;
    }
    const artifacts = mergeArtifacts(turn.response.artifacts ?? [], job.artifacts);
    return {
      ...turn,
      response: {
        ...turn.response,
        artifact_job: job,
        artifacts,
      },
    };
  });
}

function mergeArtifacts(current: RAGResponse["artifacts"], next: RAGResponse["artifacts"]): RAGResponse["artifacts"] {
  const byId = new Map<string, NonNullable<RAGResponse["artifacts"]>[number]>();
  for (const artifact of current ?? []) byId.set(artifact.id, artifact);
  for (const artifact of next ?? []) byId.set(artifact.id, artifact);
  return [...byId.values()];
}

function isArtifactJobTerminal(status: ArtifactJobSummary["status"]): boolean {
  return status === "complete" || status === "partial" || status === "failed" || status === "cancelled";
}

export function latestCompleteResponse(turns: ChatTurn[]): RAGResponse | null {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index];
    if (turn.role === "assistant" && turn.status === "complete") {
      return turn.response ?? null;
    }
  }
  return null;
}

export function markAssistantTurnErrored(turns: ChatTurn[], assistantTurnId: string, message: string): ChatTurn[] {
  return turns.map((turn) =>
    turn.id === assistantTurnId && turn.role === "assistant"
      ? { ...turn, status: "error", errorMessage: message }
      : turn,
  );
}

export function markAssistantTurnCancelled(turns: ChatTurn[], assistantTurnId: string): ChatTurn[] {
  return turns.map((turn) => {
    if (turn.id !== assistantTurnId || turn.role !== "assistant") return turn;
    if (turn.status === "complete") return turn;
    if (turn.status === "cancelled") return turn;
    return {
      ...turn,
      status: "cancelled",
      errorMessage: undefined,
      progress: [
        ...turn.progress,
        {
          id: createId("progress"),
          label: "Generation stopped",
          detail: "Request cancelled.",
          kind: "warning",
        },
      ],
    };
  });
}

export function isAbortError(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "name" in error && error.name === "AbortError");
}
