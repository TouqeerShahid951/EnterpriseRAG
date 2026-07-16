import { EmptyPanel, InlineMessage, Skeleton } from "@/components/layout/Common";
import type { ChatTurn, SavedChatSession, SavedChatSessionSummary } from "@/types/chat";
import type { UserAdmin } from "@/types/api";
import { formatDateTime } from "@/lib/utils/format";

export function ChatActivityPanel({
  error,
  loading,
  onSelectSession,
  selectedSession,
  selectedSessionError,
  selectedSessionId,
  selectedSessionLoading,
  sessions,
  target,
  total,
}: ChatActivityPanelProps) {
  return (
    <div className="admin-chat-activity">
      <div className="admin-chat-activity-header">
        <div>
          <span className="sv-metadata">Account</span>
          <h3>{target.name}</h3>
          <p>{target.email}</p>
        </div>
        <div>
          <span className="sv-metadata">Current permission</span>
          <strong>v{target.permission_version}</strong>
          <small>{total} saved session{total === 1 ? "" : "s"}</small>
        </div>
      </div>

      <div className="admin-chat-activity-grid">
        <section className="admin-chat-session-panel" aria-label="Saved chat sessions">
          <div className="admin-chat-panel-heading">
            <h3>Saved sessions</h3>
            <p>{loading ? "Loading" : `${sessions.length} shown`}</p>
          </div>
          {error ? <InlineMessage tone="error">{error}</InlineMessage> : null}
          {loading ? <ChatActivitySkeleton /> : null}
          {!loading && !error && sessions.length === 0 ? <EmptyPanel>No saved chat sessions for this permission version.</EmptyPanel> : null}
          {!loading && sessions.length > 0 ? (
            <div className="admin-chat-session-list">
              {sessions.map((session) => (
                <button
                  aria-pressed={selectedSessionId === session.id}
                  className={selectedSessionId === session.id ? "admin-chat-session-item is-active" : "admin-chat-session-item"}
                  key={session.id}
                  onClick={() => onSelectSession(session.id)}
                  type="button"
                >
                  <strong>{session.title}</strong>
                  <small>{session.questionCount} question{session.questionCount === 1 ? "" : "s"} | Updated {formatDateTime(session.updatedAt)}</small>
                </button>
              ))}
            </div>
          ) : null}
        </section>

        <section className="admin-chat-transcript-panel" aria-label="Selected chat transcript">
          {!selectedSessionId ? (
            <EmptyPanel>Select a saved session to inspect the transcript.</EmptyPanel>
          ) : selectedSessionLoading ? (
            <ChatActivitySkeleton />
          ) : selectedSessionError ? (
            <InlineMessage tone="error">{selectedSessionError}</InlineMessage>
          ) : selectedSession ? (
            <ChatTranscript session={selectedSession} />
          ) : null}
        </section>
      </div>
    </div>
  );
}

function ChatTranscript({ session }: { session: SavedChatSession }) {
  return (
    <div className="admin-chat-transcript">
      <header>
        <h3>{session.title}</h3>
        <p>{session.questionCount} question{session.questionCount === 1 ? "" : "s"} | {formatDateTime(session.createdAt)} to {formatDateTime(session.updatedAt)}</p>
      </header>
      <div className="admin-chat-turn-list">
        {session.turns.map((turn) => (
          <ChatTurnItem key={turn.id} turn={turn} />
        ))}
      </div>
      {session.turns.length === 0 ? <EmptyPanel>This saved session does not contain transcript turns.</EmptyPanel> : null}
    </div>
  );
}

function ChatTurnItem({ turn }: { turn: ChatTurn }) {
  const isAssistant = turn.role === "assistant";
  return (
    <article className={isAssistant ? "admin-chat-turn admin-chat-turn-assistant" : "admin-chat-turn admin-chat-turn-user"}>
      <div>
        <strong>{isAssistant ? "Assistant" : "User"}</strong>
        <small>{formatDateTime(turn.createdAt)}</small>
      </div>
      <p>{chatTurnContent(turn)}</p>
      {isAssistant && turn.response ? (
        <footer>
          <span>{turn.response.intent.replace(/_/g, " ")}</span>
          <span>{turn.response.sources.length} source{turn.response.sources.length === 1 ? "" : "s"}</span>
          {turn.groupPath ? <span>{turn.groupPath}</span> : null}
        </footer>
      ) : null}
    </article>
  );
}

function chatTurnContent(turn: ChatTurn): string {
  if (turn.role === "user") return turn.content;
  if (turn.response?.answer) return turn.response.answer;
  if (turn.streamText) return turn.streamText;
  if (turn.errorMessage) return turn.errorMessage;
  return "Assistant response unavailable.";
}

function ChatActivitySkeleton() {
  return (
    <div className="grid gap-2">
      {Array.from({ length: 3 }, (_, index) => (
        <Skeleton className="h-14 w-full" key={index} />
      ))}
    </div>
  );
}

export type ChatActivityPanelProps = {
  error: string | null;
  loading: boolean;
  onSelectSession: (sessionId: string) => void;
  selectedSession: SavedChatSession | null;
  selectedSessionError: string | null;
  selectedSessionId: string | null;
  selectedSessionLoading: boolean;
  sessions: SavedChatSessionSummary[];
  target: UserAdmin;
  total: number;
};
