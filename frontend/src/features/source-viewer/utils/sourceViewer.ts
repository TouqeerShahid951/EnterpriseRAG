import type { SourceAnchor } from "@/types/api";

export type SourceDocumentKind = "docx" | "image" | "json" | "pdf" | "pptx" | "spreadsheet" | "unsupported";

interface PdfPageFit {
  containerHeight: number;
  containerWidth: number;
  pageHeight: number;
  pageWidth: number;
}

interface PdfWidthFit {
  containerWidth: number;
  pageWidth: number;
}

const PDF_PAGE_GUTTER = 32;
const PDF_MAX_SCALE = 1.8;
const PDF_MIN_SCALE = 0.1;
const SOURCE_VIEWER_ZOOM_STEPS = [0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3];

export function fitPdfPageScale({
  containerHeight,
  containerWidth,
  pageHeight,
  pageWidth,
}: PdfPageFit): number {
  const availableWidth = Math.max(1, containerWidth - PDF_PAGE_GUTTER);
  const availableHeight = Math.max(1, containerHeight - PDF_PAGE_GUTTER);
  const widthScale = availableWidth / Math.max(1, pageWidth);
  const heightScale = availableHeight / Math.max(1, pageHeight);

  return Math.min(PDF_MAX_SCALE, Math.max(PDF_MIN_SCALE, Math.min(widthScale, heightScale)));
}

export function fitPdfWidthScale({
  containerWidth,
  pageWidth,
}: PdfWidthFit): number {
  const availableWidth = Math.max(1, containerWidth - PDF_PAGE_GUTTER);
  const widthScale = availableWidth / Math.max(1, pageWidth);
  return clampSourceZoom(widthScale);
}

export function fitContentScale({
  containerHeight,
  containerWidth,
  contentHeight,
  contentWidth,
  maxScale = 1,
}: {
  containerHeight: number;
  containerWidth: number;
  contentHeight: number;
  contentWidth: number;
  maxScale?: number;
}): number {
  const availableWidth = Math.max(1, containerWidth - PDF_PAGE_GUTTER);
  const availableHeight = Math.max(1, containerHeight - PDF_PAGE_GUTTER);
  const widthScale = availableWidth / Math.max(1, contentWidth);
  const heightScale = availableHeight / Math.max(1, contentHeight);
  return Math.min(maxScale, Math.max(PDF_MIN_SCALE, Math.min(widthScale, heightScale)));
}

export function fitContentWidthScale({
  containerWidth,
  contentWidth,
  maxScale = 1,
}: {
  containerWidth: number;
  contentWidth: number;
  maxScale?: number;
}): number {
  const availableWidth = Math.max(1, containerWidth - PDF_PAGE_GUTTER);
  const widthScale = availableWidth / Math.max(1, contentWidth);
  return Math.min(maxScale, Math.max(PDF_MIN_SCALE, widthScale));
}

export function clampSourcePage(page: number, pageCount: number): number {
  return Math.min(Math.max(1, page), Math.max(1, pageCount));
}

export function sourcePageFromInput(value: string, currentPage: number, pageCount: number): number {
  const normalizedValue = value.trim();
  if (!/^\d+$/.test(normalizedValue)) return clampSourcePage(currentPage, pageCount);
  const parsedPage = Number.parseInt(normalizedValue, 10);
  if (!Number.isFinite(parsedPage)) return clampSourcePage(currentPage, pageCount);
  return clampSourcePage(parsedPage, pageCount);
}

export function stepSourceZoom(currentScale: number, direction: "in" | "out"): number {
  const scale = clampSourceZoom(currentScale);
  if (direction === "in") {
    return SOURCE_VIEWER_ZOOM_STEPS.find((step) => step > scale + 0.001) ?? SOURCE_VIEWER_ZOOM_STEPS[SOURCE_VIEWER_ZOOM_STEPS.length - 1];
  }
  for (let index = SOURCE_VIEWER_ZOOM_STEPS.length - 1; index >= 0; index -= 1) {
    const step = SOURCE_VIEWER_ZOOM_STEPS[index];
    if (step < scale - 0.001) return step;
  }
  return SOURCE_VIEWER_ZOOM_STEPS[0];
}

function clampSourceZoom(scale: number): number {
  const maxScale = SOURCE_VIEWER_ZOOM_STEPS[SOURCE_VIEWER_ZOOM_STEPS.length - 1];
  const minScale = SOURCE_VIEWER_ZOOM_STEPS[0];
  return Math.min(maxScale, Math.max(minScale, scale));
}

export function sourceZoomLabel(scale: number): string {
  return `${Math.round(Math.max(0.01, scale) * 100)}%`;
}

export function sourceViewerHref(
  source: Pick<SourceAnchor, "chunk_id" | "doc_id" | "index_generation_id" | "content_hash" | "evidence_hash">,
  returnTo?: { sessionId: string | null; turnId: string | null; citationChunkIds?: string[] },
): string {
  const params = new URLSearchParams({
    docId: source.doc_id,
    chunkId: source.chunk_id,
  });
  if (source.index_generation_id) params.set("generation_id", source.index_generation_id);
  if (source.content_hash) params.set("content_hash", source.content_hash);
  if (source.evidence_hash) params.set("evidence_hash", source.evidence_hash);
  for (const chunkId of [...new Set(returnTo?.citationChunkIds?.map((id) => id.trim()).filter(Boolean) ?? [])]) {
    params.append("citationChunkId", chunkId);
  }
  if (returnTo?.sessionId) params.set("returnSessionId", returnTo.sessionId);
  if (returnTo?.turnId) params.set("returnTurnId", returnTo.turnId);
  return `/source-viewer?${params.toString()}`;
}

export function documentViewerHref(documentId: string): string {
  return `/source-viewer?${new URLSearchParams({ docId: documentId }).toString()}`;
}

export function sourceViewerParams(search: string): { documentId: string; chunkId: string | null; citationChunkIds: string[]; returnSessionId: string | null; returnTurnId: string | null; revision: Pick<SourceAnchor, "index_generation_id" | "content_hash" | "evidence_hash"> } | null {
  const params = new URLSearchParams(search);
  const documentId = params.get("docId")?.trim() ?? "";
  const chunkId = params.get("chunkId")?.trim() || null;
  const citationChunkIds = [...new Set(params.getAll("citationChunkId").map((id) => id.trim()).filter(Boolean))];
  return documentId
    ? {
      documentId,
      chunkId,
      citationChunkIds,
      revision: { index_generation_id: params.get("generation_id"), content_hash: params.get("content_hash"), evidence_hash: params.get("evidence_hash") },
      returnSessionId: params.get("returnSessionId")?.trim() || null,
      returnTurnId: params.get("returnTurnId")?.trim() || null,
    }
    : null;
}

export function sourceViewerReturnHref(params: ReturnType<typeof sourceViewerParams>): string {
  if (params && !params.chunkId) return "/documents";
  if (!params?.returnSessionId) return "/chat";
  const search = new URLSearchParams({ sessionId: params.returnSessionId });
  if (params.returnTurnId) search.set("turnId", params.returnTurnId);
  return `/chat?${search.toString()}`;
}

export function sourceDocumentKind(contentType: string, title: string): SourceDocumentKind {
  const normalizedType = contentType.split(";", 1)[0].trim().toLowerCase();
  const normalizedTitle = title.trim().toLowerCase();
  if (normalizedType === "application/pdf" || normalizedTitle.endsWith(".pdf")) return "pdf";
  if (
    normalizedType === "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    || normalizedTitle.endsWith(".pptx")
  ) return "pptx";
  if (
    normalizedType === "text/csv"
    || normalizedType === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    || normalizedTitle.endsWith(".csv")
    || normalizedTitle.endsWith(".xlsx")
  ) return "spreadsheet";
  if (normalizedType === "application/json" || normalizedTitle.endsWith(".json")) return "json";
  if (
    normalizedType === "image/jpeg"
    || normalizedType === "image/png"
    || normalizedTitle.endsWith(".jpg")
    || normalizedTitle.endsWith(".jpeg")
    || normalizedTitle.endsWith(".png")
  ) return "image";
  if (
    normalizedType === "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    || normalizedTitle.endsWith(".docx")
  ) {
    return "docx";
  }
  return "unsupported";
}

export function citedSourcePage(source: SourceAnchor): number {
  const targetPage = source.citation_targets.flatMap((target) => (
    target.kind === "page" || target.kind === "slide" ? [target.page] : []
  ))[0];
  return source.page_start ?? source.page ?? targetPage ?? 1;
}

export function sourceTextCandidates(source: SourceAnchor): string[] {
  const candidates = source.citation_targets.map((target) => target.exact_text);
  const seen = new Set<string>();
  return candidates.filter((candidate) => {
    const normalized = normalizeSourceText(candidate);
    if (!normalized || seen.has(normalized)) return false;
    seen.add(normalized);
    return true;
  });
}

export function normalizeSourceText(value: string): string {
  return value.replace(/\s+/g, " ").trim().toLocaleLowerCase();
}

export interface SourceTextRange {
  start: number;
  end: number;
}

export function sourceTextMatchRanges(text: string, query: string): SourceTextRange[] {
  const normalizedQuery = normalizeSourceText(query);
  if (!normalizedQuery) return [];
  const pattern = normalizedQuery.split(" ").map(escapeRegExp).join("\\s+");
  return [...text.matchAll(new RegExp(pattern, "giu"))].map((match) => {
    const start = match.index ?? 0;
    return { start, end: start + match[0].length };
  });
}

export function sourceTextMatchPages(pages: string[], query: string): number[] {
  return pages.flatMap((page, index) => sourceTextMatchRanges(page, query).length ? [index + 1] : []);
}

export function highlightPdfTextLayer(textDivs: HTMLElement[], query: string, active: boolean): number {
  textDivs.forEach((textDiv) => textDiv.classList.remove("source-viewer-pdf-search-highlight", "is-active"));
  const text = textDivs.map((textDiv) => textDiv.textContent ?? "").join(" ");
  const matches = sourceTextMatchRanges(text, query);
  let offset = 0;
  let activeApplied = false;

  textDivs.forEach((textDiv) => {
    const end = offset + (textDiv.textContent ?? "").length;
    if (matches.some((match) => match.start < end && match.end > offset)) {
      textDiv.classList.add("source-viewer-pdf-search-highlight");
      if (active && !activeApplied) {
        textDiv.classList.add("is-active");
        activeApplied = true;
      }
    }
    offset = end + 1;
  });

  return matches.length;
}

export function jsonDocumentText(buffer: ArrayBuffer): { prettyText: string; rawText: string } {
  const rawText = new TextDecoder("utf-8").decode(buffer.slice(0));
  try {
    return { prettyText: JSON.stringify(JSON.parse(rawText), null, 2), rawText };
  } catch {
    return { prettyText: rawText, rawText };
  }
}

export function jsonPointerRange(text: string, pointer: string): { start: number; end: number } | null {
  const ranges = new Map<string, { start: number; end: number }>();
  let cursor = 0;
  const whitespace = () => { while (/\s/.test(text[cursor] ?? "")) cursor += 1; };
  const string = () => {
    const start = cursor++;
    while (cursor < text.length) {
      if (text[cursor] === "\\") cursor += 2;
      else if (text[cursor++] === '"') break;
    }
    return JSON.parse(text.slice(start, cursor)) as string;
  };
  const value = (path: string) => {
    whitespace();
    const start = cursor;
    if (text[cursor] === "{") {
      cursor += 1;
      whitespace();
      while (cursor < text.length && text[cursor] !== "}") {
        const key = string();
        whitespace();
        if (text[cursor++] !== ":") throw new Error("Invalid JSON object");
        value(`${path}/${escapeJsonPointerToken(key)}`);
        whitespace();
        if (text[cursor] === ",") {
          cursor += 1;
          whitespace();
        } else break;
      }
      if (text[cursor++] !== "}") throw new Error("Invalid JSON object");
    } else if (text[cursor] === "[") {
      cursor += 1;
      whitespace();
      let index = 0;
      while (cursor < text.length && text[cursor] !== "]") {
        value(`${path}/${index}`);
        index += 1;
        whitespace();
        if (text[cursor] === ",") {
          cursor += 1;
          whitespace();
        } else break;
      }
      if (text[cursor++] !== "]") throw new Error("Invalid JSON array");
    } else if (text[cursor] === '"') string();
    else {
      while (cursor < text.length && !/[\s,}\]]/.test(text[cursor])) cursor += 1;
    }
    ranges.set(path, { start, end: cursor });
  };
  try {
    value("");
    whitespace();
    if (cursor !== text.length) return null;
    return ranges.get(pointer) ?? null;
  } catch {
    return null;
  }
}

function escapeJsonPointerToken(value: string): string {
  return value.replace(/~/g, "~0").replace(/\//g, "~1");
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
