export interface ExactTextTarget {
  exactText: string;
  occurrence: number;
  prefix: string;
  suffix: string;
}

export function countRenderedTextMatches(root: HTMLElement, query: string): number {
  const indexedText = indexRenderedText(root);
  return normalizedTextMatches(indexedText.normalized, query).length;
}

export function highlightRenderedTextMatch(root: HTMLElement, query: string, occurrence: number): boolean {
  const indexedText = indexRenderedText(root);
  const match = normalizedTextMatches(indexedText.normalized, query)[occurrence];
  if (!match) return false;
  wrapMatchedText(indexedText.positions.slice(match.start, match.end), "source-viewer-search-highlight");
  return true;
}

export function highlightExactSourceText(root: HTMLElement, targets: ExactTextTarget[]): boolean {
  const indexedText = indexRenderedText(root);
  if (!indexedText.normalized) return false;

  const matchedPositions = new Set<TextPosition>();
  for (const target of targets) {
    const match = exactSourceTextOffset(indexedText.normalized, target);
    if (!match) continue;
    for (const position of indexedText.positions.slice(match.start, match.end)) matchedPositions.add(position);
  }
  // Resolve every target before wrapping changes the underlying text nodes.
  wrapMatchedText(indexedText.positions.filter((position) => matchedPositions.has(position)), "source-viewer-docx-highlight");
  return matchedPositions.size > 0;
}

export function exactSourceTextOffset(text: string, target: ExactTextTarget): { start: number; end: number } | null {
  const normalizedText = normalizeText(text);
  const exactText = normalizeText(target.exactText);
  if (!exactText) return null;
  const prefix = normalizeText(target.prefix);
  const suffix = normalizeText(target.suffix);
  let matchStart = -1;
  let occurrence = 0;
  while ((matchStart = normalizedText.indexOf(exactText, matchStart + 1)) >= 0) {
    const matchEnd = matchStart + exactText.length;
    if (!normalizedText.slice(0, matchStart).trimEnd().endsWith(prefix)
      || !normalizedText.slice(matchEnd).trimStart().startsWith(suffix)) continue;
    if (occurrence < target.occurrence) {
      occurrence += 1;
      continue;
    }
    return { start: matchStart, end: matchEnd };
  }
  return null;
}

export function readableError(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function isRenderCancellation(error: unknown): boolean {
  return error instanceof Error && error.name === "RenderingCancelledException";
}

export function shouldIgnoreViewerShortcut(event: KeyboardEvent): boolean {
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return true;
  const target = event.target;
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return target.isContentEditable || tagName === "input" || tagName === "select" || tagName === "textarea";
}

export function measureElementContent(element: HTMLElement): { height: number; width: number } {
  const rect = element.getBoundingClientRect();
  return {
    height: Math.max(1, element.scrollHeight, element.offsetHeight, Math.ceil(rect.height)),
    width: Math.max(1, element.scrollWidth, element.offsetWidth, Math.ceil(rect.width)),
  };
}

function indexRenderedText(root: HTMLElement): { normalized: string; positions: TextPosition[] } {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent || parent.closest("script, style")) return NodeFilter.FILTER_REJECT;
      return node.nodeValue ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    },
  });
  const positions: TextPosition[] = [];
  let normalized = "";
  let pendingSpace: TextPosition | null = null;
  let previousBlock: Element | null = null;
  let node = walker.nextNode() as Text | null;

  while (node) {
    const value = node.nodeValue ?? "";
    const block = node.parentElement?.closest("p, li, td, th, h1, h2, h3, h4, h5, h6") ?? null;
    if (normalized && block && previousBlock && block !== previousBlock && !normalized.endsWith(" ")) {
      pendingSpace = { node, start: 0, end: 0 };
    }
    for (let offset = 0; offset < value.length;) {
      const escapedWhitespace = isEscapedWhitespace(value, offset);
      const sourceLength = escapedWhitespace ? 2 : codePointLengthAt(value, offset);
      const character = value.slice(offset, offset + sourceLength);
      const position = { node, start: offset, end: offset + sourceLength };
      if (escapedWhitespace || /\s/u.test(character)) {
        if (normalized && !normalized.endsWith(" ")) pendingSpace = extendPosition(pendingSpace, position);
        offset += sourceLength;
        continue;
      }
      const canonical = canonicalCharacter(character);
      if (!canonical) {
        offset += sourceLength;
        continue;
      }
      if (pendingSpace) {
        normalized += " ";
        positions.push(pendingSpace);
        pendingSpace = null;
      }
      const folded = canonical.toLocaleLowerCase();
      normalized += folded;
      for (let index = 0; index < folded.length; index += 1) positions.push(position);
      offset += sourceLength;
    }
    previousBlock = block;
    node = walker.nextNode() as Text | null;
  }

  return { normalized, positions };
}

function wrapMatchedText(positions: TextPosition[], className: string) {
  const groups: TextPosition[][] = [];
  for (const position of positions) {
    const current = groups[groups.length - 1];
    const previous = current?.[current.length - 1];
    if (current && previous?.node === position.node && position.start <= previous.end) current.push(position);
    else groups.push([position]);
  }

  for (const group of groups.reverse()) {
    const first = group[0];
    const last = group[group.length - 1];
    const range = document.createRange();
    range.setStart(first.node, first.start);
    range.setEnd(last.node, last.end);
    const mark = document.createElement("mark");
    mark.className = className;
    range.surroundContents(mark);
  }
}

function normalizedTextMatches(text: string, query: string): Array<{ start: number; end: number }> {
  const normalizedQuery = normalizeText(query);
  if (!normalizedQuery) return [];
  const matches: Array<{ start: number; end: number }> = [];
  let start = text.indexOf(normalizedQuery);
  while (start >= 0) {
    matches.push({ start, end: start + normalizedQuery.length });
    start = text.indexOf(normalizedQuery, start + normalizedQuery.length);
  }
  return matches;
}

interface TextPosition {
  node: Text;
  start: number;
  end: number;
}

function normalizeText(value: string): string {
  return value
    .replace(/(?:\\|\/)[nrt]/gi, " ")
    .replace(/[\u00ad\u200b-\u200d\u2060\ufeff]/gu, "")
    .replace(/[\u2018\u2019\u201a\u201b\u02bc\uff07]/gu, "'")
    .replace(/[\u201c\u201d\u201e\u201f\uff02]/gu, '"')
    .replace(/[\u2010-\u2015\u2212\ufe58\ufe63\uff0d]/gu, "-")
    .replace(/\s+/gu, " ")
    .trim()
    .toLocaleLowerCase();
}

function canonicalCharacter(character: string): string {
  if (/[\u00ad\u200b-\u200d\u2060\ufeff]/u.test(character)) return "";
  if (/[\u2018\u2019\u201a\u201b\u02bc\uff07]/u.test(character)) return "'";
  if (/[\u201c\u201d\u201e\u201f\uff02]/u.test(character)) return '"';
  if (/[\u2010-\u2015\u2212\ufe58\ufe63\uff0d]/u.test(character)) return "-";
  return character;
}

function isEscapedWhitespace(value: string, offset: number): boolean {
  return (value[offset] === "\\" || value[offset] === "/") && /[nrt]/i.test(value[offset + 1] ?? "");
}

function codePointLengthAt(value: string, offset: number): number {
  return (value.codePointAt(offset) ?? 0) > 0xffff ? 2 : 1;
}

function extendPosition(current: TextPosition | null, next: TextPosition): TextPosition {
  return current?.node === next.node
    ? { node: current.node, start: current.start, end: next.end }
    : current ?? next;
}
