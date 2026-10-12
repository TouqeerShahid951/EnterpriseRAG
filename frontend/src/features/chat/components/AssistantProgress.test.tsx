import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { BrandProvider } from "@/components/brand/BrandContext";
import { PendingAssistant } from "./AssistantProgress";

describe("assistant progress", () => {
  it("renders a Windows-safe active activity indicator", () => {
    const markup = renderToStaticMarkup(
      <BrandProvider>
        <PendingAssistant
          documents={[]}
          onSelectSource={() => undefined}
          selectedSource={null}
          turn={{
            id: "assistant-1",
            role: "assistant",
            status: "pending",
            question: "What is the retrieval route?",
            createdAt: new Date().toISOString(),
            progress: [{ id: "route", label: "Choosing the retrieval route", kind: "node" }],
          }}
        />
      </BrandProvider>,
    );

    expect(markup).toContain("rag-progress-icon-spinner");
    expect(markup).toContain("rag-progress-icon-static");
  });
});
