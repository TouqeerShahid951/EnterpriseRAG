import { queryApi } from "@/lib/api/contracts";
import type { RagSseEvent, RAGResponse } from "@/types/api";
import type { QueryRunVariables } from "@/types/chat";

export async function runStreamingQuery(
  variables: QueryRunVariables,
  onEvent: (event: RagSseEvent) => void,
): Promise<RAGResponse> {
  let finalResponse: RAGResponse | null = null;
  for await (const event of queryApi.stream(variables.request, { signal: variables.signal })) {
    onEvent(event);
    if (event.event === "done") {
      finalResponse = event.data;
    }
    if (event.event === "verified") {
      finalResponse = event.data;
    }
    if (event.event === "error") {
      throw new Error(event.data.message || event.data.code);
    }
  }
  if (!finalResponse) {
    throw new Error("The query stream ended before returning a final answer.");
  }
  return finalResponse;
}
