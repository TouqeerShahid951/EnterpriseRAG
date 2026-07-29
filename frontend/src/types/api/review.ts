import type { ISODateString } from "./common";

type ReviewStatus = "pending" | "approved" | "rejected";

type ImageReviewCandidateStatus = "pending" | "approved" | "skipped";

export interface ReviewItem {
  id: string;
  batch_id: string;
  doc_id: string;
  doc_title: string;
  item_index: number;
  item_type: string;
  page_start: number | null;
  page_end: number | null;
  bbox: number[] | null;
  quality_flags: string[];
  confidence: number | null;
  partial_text: string;
  corrected_text: string | null;
  status: ReviewStatus;
  assigned_to: string | null;
  created_at: ISODateString | null;
  updated_at: ISODateString | null;
}

export interface ReviewDecisionResponse {
  id: string;
  status: ReviewStatus;
  batch_id: string;
  batch_status: ReviewStatus;
  batch_complete: boolean;
}

export interface ReviewQueueSummary {
  pending_document_count: number;
}

export interface ImageReviewCandidate {
  id: string;
  batch_id: string;
  doc_id: string;
  doc_title: string;
  candidate_key: string;
  filename: string;
  source_kind: string;
  page: number | null;
  bbox: number[] | null;
  page_area_ratio: number | null;
  content_url: string;
  content_type: string;
  width: number | null;
  height: number | null;
  quality_flags: string[];
  score: number;
  recommended: boolean;
  status: ImageReviewCandidateStatus;
  assigned_to: string | null;
  skip_reason: string | null;
  created_at: ISODateString | null;
  updated_at: ISODateString | null;
}

export interface ImageReviewBatch {
  id: string;
  job_id: string;
  doc_id: string;
  doc_title: string;
  status: ReviewStatus;
  candidate_count: number;
  recommended_count: number;
  pending_count: number;
  approved_count: number;
  skipped_count: number;
  candidates: ImageReviewCandidate[];
  created_at: ISODateString | null;
  updated_at: ISODateString | null;
}

export interface ImageReviewQueueResponse {
  batches: ImageReviewBatch[];
  total: number;
  candidate_total: number;
}

export interface ImageReviewDecisionResponse {
  batch_id: string;
  batch_status: ReviewStatus;
  batch_complete: boolean;
  approved_count: number;
  skipped_count: number;
  pending_count: number;
}
