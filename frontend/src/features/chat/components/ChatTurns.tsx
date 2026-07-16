import { AssistantZipTurn } from "@/features/chat/components/AssistantZipTurn";
import type { Props } from "@/features/chat/types/chatPageTypes";

export function ChatTurns({
  chatTurns,
  documents,
  onCancelArtifactJob,
  onClarifyArtifactJob,
  onExpandSourceSearch,
  onRetryArtifactJob,
  onSelectSource,
  selectedSource,
}: Pick<Props, "chatTurns" | "documents" | "onCancelArtifactJob" | "onClarifyArtifactJob" | "onExpandSourceSearch" | "onRetryArtifactJob" | "onSelectSource" | "selectedSource">) {
  return chatTurns.map((turn) =>
    turn.role === "user" ? (
      <div key={turn.id} className="flex justify-end">
        <div className="rag-user-message">{turn.content}</div>
      </div>
    ) : (
      <AssistantZipTurn
        key={turn.id}
        documents={documents}
        onCancelArtifactJob={onCancelArtifactJob}
        onClarifyArtifactJob={onClarifyArtifactJob}
        onExpandSourceSearch={onExpandSourceSearch}
        onRetryArtifactJob={onRetryArtifactJob}
        onSelectSource={onSelectSource}
        selectedSource={selectedSource}
        turn={turn}
      />
    ),
  );
}
