import { AssistantZipTurn } from "@/features/chat/components/AssistantZipTurn";
import type { Props } from "@/features/chat/types/chatPageTypes";
import { AssistantResponseActions } from "./AssistantResponseActions";
import { replyLabelForTurn, replyPreviewForTurn } from "@/features/chat/utils/chatPageUtils";
import type { ChatTurn } from "@/types/chat";

export function ChatTurns({
  chatTurns,
  documents,
  onCancelArtifactJob,
  onClarifyArtifactJob,
  onChooseQuerySource,
  onExpandSourceSearch,
  onReplyToTurn,
  onRetryArtifactJob,
  onSelectSource,
  selectedSource,
}: Pick<Props, "chatTurns" | "documents" | "onCancelArtifactJob" | "onClarifyArtifactJob" | "onChooseQuerySource" | "onExpandSourceSearch" | "onReplyToTurn" | "onRetryArtifactJob" | "onSelectSource" | "selectedSource">) {
  return chatTurns.map((turn) => {
    const replyTarget = turn.replyToTurnId
      ? chatTurns.find((candidate) => candidate.id === turn.replyToTurnId) ?? null
      : null;
    return turn.role === "user" ? (
      <div key={turn.id} id={`chat-turn-${turn.id}`} className="rag-chat-message-row is-user">
        <div className="rag-user-message">
          {replyTarget ? <ReplyQuote turn={replyTarget} /> : null}
          <div>{turn.content}</div>
        </div>
      </div>
    ) : (
      <div key={turn.id} id={`chat-turn-${turn.id}`} className="rag-chat-message-row is-assistant">
        <AssistantZipTurn
          documents={documents}
          onCancelArtifactJob={onCancelArtifactJob}
          onClarifyArtifactJob={onClarifyArtifactJob}
          onChooseQuerySource={onChooseQuerySource}
          onExpandSourceSearch={onExpandSourceSearch}
          onRetryArtifactJob={onRetryArtifactJob}
          onSelectSource={(source) => onSelectSource(source, turn.id)}
          selectedSource={selectedSource}
          turn={turn}
        />
        {turn.status === "complete" ? (
          <AssistantResponseActions
            answer={turn.response?.source_clarification?.question ?? turn.response?.answer ?? ""}
            createdAt={turn.createdAt}
            onReply={() => onReplyToTurn(turn.id)}
          />
        ) : null}
      </div>
    );
  });
}

function ReplyQuote({ turn }: { turn: ChatTurn }) {
  return (
    <div className="rag-message-reply-quote">
      <strong>{replyLabelForTurn(turn)}</strong>
      <span>{replyPreviewForTurn(turn)}</span>
    </div>
  );
}
