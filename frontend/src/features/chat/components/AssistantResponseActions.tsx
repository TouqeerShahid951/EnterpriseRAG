import { useState } from "react";
import { Check, Copy, Reply } from "lucide-react";
import { formatDateTime } from "@/lib/utils/format";

export function AssistantResponseActions({ answer, createdAt, onReply }: {
  answer: string;
  createdAt: string;
  onReply: () => void;
}) {
  const [copyStatus, setCopyStatus] = useState("");
  const date = new Date(createdAt);

  async function copyResponse() {
    try {
      await navigator.clipboard.writeText(answer);
      setCopyStatus("Copied");
    } catch {
      setCopyStatus("Could not copy. Select the response and copy it manually.");
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-label-md text-secondary">
      <button type="button" className="rag-message-reply-action" onClick={copyResponse} disabled={!answer} aria-label="Copy response" title="Copy response">
        {copyStatus === "Copied" ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
      </button>
      <button type="button" className="rag-message-reply-action" onClick={onReply} aria-label="Reply to this answer" title="Reply to this answer">
        <Reply size={14} aria-hidden="true" />
        <span className="rag-message-reply-label">Reply</span>
      </button>
      {Number.isNaN(date.getTime()) ? null : (
        <time dateTime={createdAt} title={`Response started: ${date.toLocaleString()}`}>
          {formatDateTime(createdAt)}
        </time>
      )}
      <span role="status">{copyStatus}</span>
    </div>
  );
}
