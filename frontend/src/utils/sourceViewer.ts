import type { SourceAnchor, SourceRegion } from "../types/api";

export type SourceDocumentKind = "docx" | "image" | "json" | "pdf" | "unsupported";

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

export function clampSourceZoom(scale: number): number {
  const maxScale = SOURCE_VIEWER_ZOOM_STEPS[SOURCE_VIEWER_ZOOM_STEPS.length - 1];
  const minScale = SOURCE_VIEWER_ZOOM_STEPS[0];
  return Math.min(maxScale, Math.max(minScale, scale));
}

export function sourceZoomLabel(scale: number): string {
  return `${Math.round(Math.max(0.01, scale) * 100)}%`;
}

export function sourceViewerHref(source: Pick<SourceAnchor, "chunk_id" | "doc_id">): string {
  const params = new URLSearchParams({
    docId: source.doc_id,
    chunkId: source.chunk_id,
  });
  return `/source-viewer?${params.toString()}`;
}

export function sourceViewerParams(search: string): { documentId: string; chunkId: string } | null {
  const params = new URLSearchParams(search);
  const documentId = params.get("docId")?.trim() ?? "";
  const chunkId = params.get("chunkId")?.trim() ?? "";
  return documentId && chunkId ? { documentId, chunkId } : null;
}

export function sourceDocumentKind(contentType: string, title: string): SourceDocumentKind {
  const normalizedType = contentType.split(";", 1)[0].trim().toLowerCase();
  const normalizedTitle = title.trim().toLowerCase();
  if (normalizedType === "application/pdf" || normalizedTitle.endsWith(".pdf")) return "pdf";
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
  return source.page_start ?? source.page ?? source.source_regions?.find((region) => region.page !== null)?.page ?? 1;
}

export function sourceRegionsForPage(source: SourceAnchor, page: number): SourceRegion[] {
  return (source.source_regions ?? []).filter((region) => region.page === page && region.bbox !== null);
}

export function sourceTextCandidates(source: SourceAnchor): string[] {
  const candidates = [...(source.source_regions ?? []).map((region) => region.text), source.excerpt];
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

export function jsonDocumentText(buffer: ArrayBuffer): { prettyText: string; rawText: string } {
  const rawText = new TextDecoder("utf-8").decode(buffer.slice(0));
  try {
    return { prettyText: JSON.stringify(JSON.parse(rawText), null, 2), rawText };
  } catch {
    return { prettyText: rawText, rawText };
  }
}

export function jsonHighlightRange(text: string, candidates: string[]): { start: number; end: number } | null {
  const variants = candidates.flatMap(jsonMatchingVariants);
  const lowerText = text.toLocaleLowerCase();
  for (const variant of variants) {
    const index = lowerText.indexOf(variant.toLocaleLowerCase());
    if (index >= 0) return { start: index, end: index + variant.length };
  }
  return null;
}

function jsonMatchingVariants(candidate: string): string[] {
  const variants = [candidate.trim()];
  for (const line of candidate.split(/\r?\n/)) {
    const [label, ...valueParts] = line.split(":");
    const value = valueParts.join(":").trim();
    if (value && label.trim().toLocaleLowerCase() !== "json path") {
      variants.push(value);
    }
  }
  const pathMatch = /JSON path:\s*([^\n]+)/i.exec(candidate);
  if (pathMatch) {
    const keyMatch = /(?:\.|\[")([A-Za-z0-9_ -]+)(?:"\])?$/.exec(pathMatch[1]);
    if (keyMatch) variants.push(keyMatch[1]);
  }
  return variants
    .map((value) => value.trim())
    .filter((value, index, values) => value.length >= 2 && values.indexOf(value) === index);
}
