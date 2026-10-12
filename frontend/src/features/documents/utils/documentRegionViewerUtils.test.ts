import { afterEach, describe, expect, it, vi } from "vitest";

import {
  countRenderedTextMatches,
  exactSourceTextOffset,
  highlightExactSourceText,
  highlightRenderedTextMatch,
} from "./documentRegionViewerUtils";

afterEach(() => vi.unstubAllGlobals());

describe("exactSourceTextOffset", () => {
  it("uses exact context and occurrence instead of partial text guesses", () => {
    expect(exactSourceTextOffset("Role Ada. Backup Ada.", {
      exactText: "Ada",
      occurrence: 0,
      prefix: "Backup ",
      suffix: ".",
    })).toEqual({ start: 17, end: 20 });
  });

  it("does not highlight a partial anchor", () => {
    expect(exactSourceTextOffset("Ada Lovelace", {
      exactText: "Ada Analyst",
      occurrence: 0,
      prefix: "",
      suffix: "",
    })).toBeNull();
  });

  it.each(["\\n", "/n", "\\r", "\\t"])("treats parser escape %s as rendered whitespace", (escape) => {
    expect(exactSourceTextOffset("Payment terms apply.", {
      exactText: `Payment terms${escape}apply.`,
      occurrence: 0,
      prefix: "",
      suffix: "",
    })).toEqual({ start: 0, end: 20 });
  });

  it("matches OCR punctuation variants", () => {
    expect(exactSourceTextOffset('The "Supplier"-Touqeer', {
      exactText: "The “Supplier”—Touqeer",
      occurrence: 0,
      prefix: "",
      suffix: "",
    })).toEqual({ start: 0, end: 22 });
  });

  it("ignores OCR soft hyphens and zero-width characters", () => {
    expect(exactSourceTextOffset("Touqeer contract", {
      exactText: "Tou\u200Bqeer co\u00ADntract",
      occurrence: 0,
      prefix: "",
      suffix: "",
    })).toEqual({ start: 0, end: 16 });
  });

  it("preserves spaces stored in separate Word formatting runs", () => {
    const block = {} as Element;
    const nodes = [textNode("Records", block), textNode(" ", block), textNode("must be retained.", block)];
    const surroundContents = mockRenderedText(nodes);

    expect(highlightExactSourceText({} as HTMLElement, [{
      exactText: "Records must be retained.", occurrence: 0, prefix: "", suffix: "",
    }])).toBe(true);
    expect(surroundContents).toHaveBeenCalledTimes(3);
  });

  it("highlights the cited paragraph as well as its heading", () => {
    const nodes = [textNode("Policy", {} as Element), textNode("Records must be retained.", {} as Element)];
    const surroundContents = mockRenderedText(nodes);

    expect(highlightExactSourceText({} as HTMLElement, [
      { exactText: "Policy", occurrence: 0, prefix: "", suffix: "Records must be retained." },
      { exactText: "Records must be retained.", occurrence: 0, prefix: "Policy", suffix: "" },
    ])).toBe(true);
    expect(surroundContents).toHaveBeenCalledTimes(2);
  });

  it("treats separate DOCX paragraphs as whitespace", () => {
    const firstBlock = {} as Element;
    const secondBlock = {} as Element;
    const nodes = [
      textNode("Dataset.", firstBlock),
      textNode("Screenshot 5.2", secondBlock),
    ];
    mockRenderedText(nodes);

    expect(highlightExactSourceText({} as HTMLElement, [{
      exactText: "Dataset. Screenshot 5.2",
      occurrence: 0,
      prefix: "",
      suffix: "",
    }])).toBe(true);
  });

  it("keeps rendered offsets aligned when ignored OCR characters occur inside a match", () => {
    const node = textNode("Tou\u200Bqeer co\u00ADntract", {} as Element);
    const range = mockRenderedText([node]);

    expect(highlightExactSourceText({} as HTMLElement, [{
      exactText: "Touqeer contract", occurrence: 0, prefix: "", suffix: "",
    }])).toBe(true);
    expect(range.setStart).toHaveBeenCalledWith(node, 0);
    expect(range.setEnd).toHaveBeenCalledWith(node, 18);
  });

  it("counts and highlights the requested rendered-text occurrence", () => {
    const firstBlock = {} as Element;
    const secondBlock = {} as Element;
    const nodes = [
      textNode("Space", firstBlock),
      textNode(" resources", firstBlock),
      textNode("Space resources", secondBlock),
    ];
    const surroundContents = mockRenderedText(nodes);

    expect(countRenderedTextMatches({} as HTMLElement, "space resources")).toBe(2);
    expect(highlightRenderedTextMatch({} as HTMLElement, "space resources", 1)).toBe(true);
    expect(surroundContents).toHaveBeenCalled();
    expect(highlightRenderedTextMatch({} as HTMLElement, "missing", 0)).toBe(false);
  });
});

function mockRenderedText(nodes: Text[]) {
  const surroundContents = vi.fn();
  const setStart = vi.fn();
  const setEnd = vi.fn();
  vi.stubGlobal("NodeFilter", { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1, FILTER_SKIP: 3 });
  vi.stubGlobal("document", {
    createTreeWalker: (_root: HTMLElement, _show: number, filter: { acceptNode: (node: Node) => number }) => {
      const accepted = nodes.filter((node) => filter.acceptNode(node) === 1);
      let index = 0;
      return { nextNode: () => accepted[index++] ?? null };
    },
    createRange: () => ({ setStart, setEnd, surroundContents }),
    createElement: () => ({ className: "" }),
  });
  return Object.assign(surroundContents, { setStart, setEnd });
}

function textNode(value: string, block: Element): Text {
  return {
    nodeValue: value,
    parentElement: {
      closest: (selector: string) => selector === "script, style" ? null : block,
    },
  } as unknown as Text;
}
