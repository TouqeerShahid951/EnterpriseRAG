import { describe, expect, it } from "vitest";

import { documentMentionBeforeCursor, hasDocumentMention, insertDocumentMention, removeDocumentMention } from "../utils/chatComposerUtils";
import { resizeComposerInput } from "./ChatComposer";

describe("resizeComposerInput", () => {
  it("grows with content and caps long messages at the composer limit", () => {
    const input = fakeTextarea(72);
    resizeComposerInput(input);
    expect(input.style).toMatchObject({ height: "72px", overflowY: "hidden" });

    Object.defineProperty(input, "scrollHeight", { configurable: true, value: 240 });
    resizeComposerInput(input);
    expect(input.style).toMatchObject({ height: "128px", overflowY: "auto" });
  });
});

describe("insertDocumentMention", () => {
  it("replaces the active query with a readable @document mention", () => {
    expect(insertDocumentMention("summarize the @contract", "Signed Contract.pdf")).toBe("summarize the @Signed Contract.pdf ");
    expect(insertDocumentMention("@", "Policy.pdf")).toBe("@Policy.pdf ");
    expect(removeDocumentMention("summarize the @Policy.pdf and @Policy.pdf", "Policy.pdf")).toBe("summarize the and");
    expect(hasDocumentMention("summarize the @Policy.pdf ", "Policy.pdf")).toBe(true);
    expect(hasDocumentMention("summarize the Policy.pdf", "Policy.pdf")).toBe(false);
    expect(documentMentionBeforeCursor("summarize the @Policy.pdf ", "Policy.pdf", 25)).toBe(true);
  });
});

function fakeTextarea(scrollHeight: number): HTMLTextAreaElement {
  return {
    scrollHeight,
    style: { height: "", overflowY: "" },
  } as unknown as HTMLTextAreaElement;
}
