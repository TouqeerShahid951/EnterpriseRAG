import type {
  ImageReviewDecisionResponse,
  ImageReviewQueueResponse,
  ReviewDecisionResponse,
  ReviewItem,
  ReviewQueueSummary,
} from "@/types/api";
import { getConfiguredBaseUrl, normalizeBaseUrl } from "../url";
import { apiClient } from "./apiClient";

export interface ImageReviewDecisionRequest {
  approve_candidate_ids?: string[];
  skip_candidate_ids?: string[];
  approve_recommended?: boolean;
  skip_remaining?: boolean;
}

export const reviewApi = {
  list: () => apiClient.get<{ items: ReviewItem[]; total: number }>("/api/v1/review-queue"),
  summary: () => apiClient.get<ReviewQueueSummary>("/api/v1/review-queue/summary"),
  listImageBatches: () => apiClient.get<ImageReviewQueueResponse>("/api/v1/review-queue/image-batches"),
  decideImageBatch: (batchId: string, request: ImageReviewDecisionRequest) =>
    apiClient.postJson<ImageReviewDecisionResponse>(`/api/v1/review-queue/image-batches/${encodeURIComponent(batchId)}/decisions`, request),
  imageCandidateContentUrl: (contentUrl: string) =>
    contentUrl.startsWith("http")
      ? contentUrl
      : `${normalizeBaseUrl(getConfiguredBaseUrl())}${contentUrl.startsWith("/") ? contentUrl : `/${contentUrl}`}`,
  approve: (itemId: string, correctedText: string) =>
    apiClient.postJson<ReviewDecisionResponse>(`/api/v1/review-queue/${encodeURIComponent(itemId)}/approve`, {
      corrected_text: correctedText,
    }),
  reject: (itemId: string) =>
    apiClient.postJson<ReviewDecisionResponse>(`/api/v1/review-queue/${encodeURIComponent(itemId)}/reject`, null),
};
