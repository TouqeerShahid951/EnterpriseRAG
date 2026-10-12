import type { Document, SourceAnchor } from "@/types/api";
import type { ChatTurn } from "@/types/chat";

export type Props = {
  documents: Document[];
  onCancelArtifactJob?: (jobId: string) => Promise<void>;
  onClarifyArtifactJob?: (jobId: string, answers: Record<string, string>) => Promise<void>;
  onChooseQuerySource?: (assistantTurnId: string, sourceId: string) => void;
  onExpandSourceSearch?: (assistantTurnId: string) => void;
  onRetryArtifactJob?: (jobId: string) => Promise<void>;
  onSelectSource: (source: SourceAnchor | null, turnId?: string) => void;
  selectedSource: SourceAnchor | null;
  turn: Extract<ChatTurn, { role: "assistant" }>;
};
