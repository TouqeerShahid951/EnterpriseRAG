import type { DocumentRegion } from "@/features/documents/components/DocumentRegionViewer";
import type { ImageReviewCandidate, ReviewItem } from "@/types/api";

export function reviewRegionFromItem(item: ReviewItem): DocumentRegion {
  return {
    bbox: normalizeBBox(item.bbox),
    confidence: item.confidence,
    page: item.page_start ?? item.page_end,
    regionType: item.item_type,
    text: item.partial_text,
  };
}

export function groupReviewItemsByDocument(items: ReviewItem[]): ReviewDocumentGroup[] {
  const groups = new Map<string, ReviewDocumentGroup>();
  for (const item of items) {
    const group = groups.get(item.doc_id) ?? { docId: item.doc_id, docTitle: item.doc_title, items: [] };
    group.items.push(item);
    groups.set(item.doc_id, group);
  }
  return [...groups.values()];
}

function normalizeBBox(value: number[] | null): [number, number, number, number] | null {
  if (!value || value.length !== 4 || !value.every(Number.isFinite)) return null;
  const [x0, y0, x1, y1] = value;
  if (x1 <= x0 || y1 <= y0) return null;
  return [x0, y0, x1, y1];
}

export function confidenceLabel(confidence: number | null): string {
  if (confidence === null) return "Missing confidence";
  return `${Math.round(confidence * 100)}%`;
}

export function confidencePillClass(item: ReviewItem): string {
  if (item.confidence === null || item.confidence < 0.8) return "sv-pill sv-pill-warning";
  return "sv-pill sv-pill-success";
}

export function confidencePercent(item: ReviewItem): number {
  if (item.confidence === null) return 0;
  return Math.max(0, Math.min(100, Math.round(item.confidence * 100)));
}

export function pageRange(item: ReviewItem): string {
  if (!item.page_start) return "Unknown";
  if (!item.page_end || item.page_end === item.page_start) return String(item.page_start);
  return `${item.page_start}-${item.page_end}`;
}

export function itemTypeLabel(value: string): string {
  if (!value) return "Block";
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function qualityFlagLabel(value: string): string {
  return value.replace(/^source:/, "").replace(/[_-]+/g, " ");
}

export function qualitySummary(item: ReviewItem): string {
  if (item.quality_flags.length === 0) return "No flags";
  return item.quality_flags.slice(0, 2).map(qualityFlagLabel).join(", ");
}

export function candidateLabel(candidate: ImageReviewCandidate): string {
  const page = candidate.page ? `Page ${candidate.page}` : "Unknown page";
  return `${page} | ${itemTypeLabel(candidate.source_kind)}`;
}

export function candidateQuality(candidate: ImageReviewCandidate): string {
  const size = candidate.width && candidate.height ? `${candidate.width}x${candidate.height}` : "size unknown";
  const area = candidate.page_area_ratio !== null ? `${Math.round(candidate.page_area_ratio * 100)}% page` : "area unknown";
  const flags = candidate.quality_flags.slice(0, 2).map(qualityFlagLabel).join(", ");
  return [size, area, flags].filter(Boolean).join(" | ");
}

export interface ReviewDocumentGroup {
  docId: string;
  docTitle: string;
  items: ReviewItem[];
}
