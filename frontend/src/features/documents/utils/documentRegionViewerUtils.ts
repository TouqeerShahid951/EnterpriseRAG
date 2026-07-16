import { normalizeSourceText } from "@/features/source-viewer/utils/sourceViewer";

export function sourceTextCandidates(regions: Array<{ text: string }>, explicitCandidates: string[] | undefined): string[] {
  const candidates = [...(explicitCandidates ?? []), ...regions.map((region) => region.text)];
  const seen = new Set<string>();
  return candidates.filter((candidate) => {
    const normalized = normalizeSourceText(candidate);
    if (!normalized || seen.has(normalized)) return false;
    seen.add(normalized);
    return true;
  });
}

export function highlightFirstSourceText(root: HTMLElement, candidates: string[]): boolean {
  const indexedText = indexRenderedText(root);
  if (!indexedText.normalized) return false;

  for (const candidate of candidates) {
    for (const query of matchingVariants(candidate)) {
      const matchStart = indexedText.normalized.indexOf(query);
      if (matchStart < 0) continue;
      wrapMatchedText(indexedText.positions.slice(matchStart, matchStart + query.length));
      return true;
    }
  }
  return false;
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
      return node.nodeValue?.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    },
  });
  const positions: TextPosition[] = [];
  let normalized = "";
  let pendingSpace: TextPosition | null = null;
  let node = walker.nextNode() as Text | null;

  while (node) {
    const value = node.nodeValue ?? "";
    for (let offset = 0; offset < value.length; offset += 1) {
      const character = value[offset];
      if (/\s/.test(character)) {
        if (normalized && !normalized.endsWith(" ")) pendingSpace = { node, offset };
        continue;
      }
      if (pendingSpace) {
        normalized += " ";
        positions.push(pendingSpace);
        pendingSpace = null;
      }
      normalized += character.toLocaleLowerCase();
      positions.push({ node, offset });
    }
    node = walker.nextNode() as Text | null;
  }

  return { normalized, positions };
}

function matchingVariants(candidate: string): string[] {
  const normalized = normalizeSourceText(candidate);
  if (!normalized) return [];
  const variants = [normalized];
  if (normalized.length > 320) variants.push(normalized.slice(0, 320).trim());
  if (normalized.length > 160) variants.push(normalized.slice(0, 160).trim());
  return variants.filter((variant, index) => variant.length >= 16 && variants.indexOf(variant) === index);
}

function wrapMatchedText(positions: TextPosition[]) {
  const groups: TextPosition[][] = [];
  for (const position of positions) {
    const current = groups[groups.length - 1];
    const previous = current?.[current.length - 1];
    if (current && previous?.node === position.node && position.offset <= previous.offset + 1) current.push(position);
    else groups.push([position]);
  }

  for (const group of groups.reverse()) {
    const first = group[0];
    const last = group[group.length - 1];
    const range = document.createRange();
    range.setStart(first.node, first.offset);
    range.setEnd(last.node, last.offset + 1);
    const mark = document.createElement("mark");
    mark.className = "source-viewer-docx-highlight";
    range.surroundContents(mark);
  }
}

interface TextPosition {
  node: Text;
  offset: number;
}
