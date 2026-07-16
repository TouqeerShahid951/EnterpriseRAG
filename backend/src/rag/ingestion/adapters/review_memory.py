"""In-memory human-review and image-review repository behavior."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ...documents.adapters.memory_values import _bbox_list, _int_or_none
from ..review.models import (
    ImageReviewBatchClosedError,
    ImageReviewBatchRecord,
    ImageReviewCandidateRecord,
    ImageReviewDecisionRecord,
    ReviewBatchRecord,
    ReviewDecisionRecord,
    ReviewItemRecord,
)


class InMemoryReviewRepositoryMixin:
    def create_review_batch(
        self,
        *,
        job_id: str,
        doc_id: str,
        parsed_items: list[dict[str, Any]],
        resume_payload: dict[str, Any],
        review_items: list[dict[str, Any]],
    ) -> ReviewBatchRecord:
        if doc_id not in self._documents:
            raise ValueError("document does not exist")
        now = datetime.now(UTC)
        batch = ReviewBatchRecord(
            id=str(uuid4()),
            job_id=job_id,
            doc_id=doc_id,
            status="pending",
            parsed_items=[dict(item) for item in parsed_items],
            resume_payload=dict(resume_payload),
            created_at=now,
            updated_at=now,
        )
        self._review_batches[batch.id] = batch
        document = self._documents[doc_id]
        for item in review_items:
            record = ReviewItemRecord(
                id=str(uuid4()),
                batch_id=batch.id,
                doc_id=doc_id,
                doc_title=document.title or document.id,
                item_index=int(item["item_index"]),
                item_type=str(item.get("item_type") or "text"),
                page_start=_int_or_none(item.get("page_start")),
                page_end=_int_or_none(item.get("page_end")),
                bbox=_bbox_list(item.get("bbox")),
                quality_flags=tuple(str(flag) for flag in item.get("quality_flags", []) if str(flag)),
                partial_text=str(item.get("partial_text") or ""),
                corrected_text=None,
                confidence=float(item["confidence"]) if isinstance(item.get("confidence"), (int, float)) else None,
                status="pending",
                assigned_to=None,
                created_at=now,
                updated_at=now,
            )
            self._review_items[record.id] = record
        return batch

    def get_review_batch(self, batch_id: str) -> ReviewBatchRecord | None:
        return self._review_batches.get(batch_id)

    def list_review_items(self, *, status: str = "pending") -> list[ReviewItemRecord]:
        items = [item for item in self._review_items.values() if item.status == status]
        return sorted(items, key=lambda item: item.created_at or datetime.min.replace(tzinfo=UTC))

    def list_review_items_for_batch(self, batch_id: str) -> list[ReviewItemRecord]:
        return sorted(
            [item for item in self._review_items.values() if item.batch_id == batch_id],
            key=lambda item: item.item_index,
        )

    def approve_review_item(self, item_id: str, *, corrected_text: str, reviewer_id: str) -> ReviewDecisionRecord | None:
        item = self._review_items.get(item_id)
        if item is None:
            return None
        now = datetime.now(UTC)
        updated_item = replace(item, status="approved", corrected_text=corrected_text, assigned_to=reviewer_id, updated_at=now)
        self._review_items[item_id] = updated_item
        batch = self._review_batches[item.batch_id]
        batch_items = self.list_review_items_for_batch(batch.id)
        complete = all(block.status == "approved" for block in batch_items)
        if complete:
            batch = replace(batch, status="approved", updated_at=now)
            self._review_batches[batch.id] = batch
        return ReviewDecisionRecord(item=updated_item, batch=batch, batch_complete=complete)

    def reject_review_item(self, item_id: str, *, reviewer_id: str) -> ReviewDecisionRecord | None:
        item = self._review_items.get(item_id)
        if item is None:
            return None
        now = datetime.now(UTC)
        updated_item = replace(item, status="rejected", assigned_to=reviewer_id, updated_at=now)
        self._review_items[item_id] = updated_item
        batch = replace(self._review_batches[item.batch_id], status="rejected", updated_at=now)
        self._review_batches[batch.id] = batch
        return ReviewDecisionRecord(item=updated_item, batch=batch, batch_complete=False)

    def create_image_review_batch(
        self,
        *,
        job_id: str,
        doc_id: str,
        parsed_items: list[dict[str, Any]],
        resume_payload: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> ImageReviewBatchRecord:
        if doc_id not in self._documents:
            raise ValueError("document does not exist")
        now = datetime.now(UTC)
        document = self._documents[doc_id]
        batch = ImageReviewBatchRecord(
            id=str(uuid4()),
            job_id=job_id,
            doc_id=doc_id,
            doc_title=document.title or document.id,
            status="pending",
            parsed_items=[dict(item) for item in parsed_items],
            resume_payload=dict(resume_payload),
            candidate_count=len(candidates),
            recommended_count=sum(1 for candidate in candidates if bool(candidate.get("recommended", True))),
            created_at=now,
            updated_at=now,
        )
        self._image_review_batches[batch.id] = batch
        for candidate in candidates:
            record = ImageReviewCandidateRecord(
                id=str(candidate.get("id") or uuid4()),
                batch_id=batch.id,
                doc_id=doc_id,
                doc_title=batch.doc_title,
                candidate_key=str(candidate["candidate_key"]),
                filename=str(candidate.get("filename") or "image"),
                source_kind=str(candidate.get("source_kind") or "pdf_image"),
                page=_int_or_none(candidate.get("page")),
                bbox=_bbox_list(candidate.get("bbox")),
                page_area_ratio=float(candidate["page_area_ratio"]) if isinstance(candidate.get("page_area_ratio"), (int, float)) else None,
                object_path=str(candidate["object_path"]),
                content_type=str(candidate.get("content_type") or "image/png"),
                width=_int_or_none(candidate.get("width")),
                height=_int_or_none(candidate.get("height")),
                content_hash=str(candidate["content_hash"]),
                quality_flags=tuple(str(flag) for flag in candidate.get("quality_flags", []) if str(flag)),
                score=int(candidate.get("score") or 0),
                recommended=bool(candidate.get("recommended", True)),
                status="pending",
                assigned_to=None,
                skip_reason=None,
                created_at=now,
                updated_at=now,
            )
            self._image_review_candidates[record.id] = record
        return batch

    def get_image_review_batch(self, batch_id: str) -> ImageReviewBatchRecord | None:
        return self._image_review_batches.get(batch_id)

    def list_image_review_batches(self, *, status: str = "pending") -> list[ImageReviewBatchRecord]:
        batches = [batch for batch in self._image_review_batches.values() if batch.status == status]
        return sorted(batches, key=lambda batch: batch.created_at or datetime.min.replace(tzinfo=UTC))

    def list_image_review_candidates_for_batch(
        self,
        batch_id: str,
        *,
        status: str | None = None,
    ) -> list[ImageReviewCandidateRecord]:
        candidates = [candidate for candidate in self._image_review_candidates.values() if candidate.batch_id == batch_id]
        if status is not None:
            candidates = [candidate for candidate in candidates if candidate.status == status]
        return sorted(candidates, key=lambda candidate: (candidate.page or 0, -candidate.score, candidate.filename, candidate.id))

    def get_image_review_candidate(self, candidate_id: str) -> ImageReviewCandidateRecord | None:
        return self._image_review_candidates.get(candidate_id)

    def apply_image_review_decisions(
        self,
        batch_id: str,
        *,
        approve_candidate_ids: list[str],
        skip_candidate_ids: list[str],
        reviewer_id: str,
        approve_recommended: bool = False,
        skip_remaining: bool = False,
    ) -> ImageReviewDecisionRecord | None:
        batch = self._image_review_batches.get(batch_id)
        if batch is None:
            return None
        if batch.status == "rejected":
            raise ImageReviewBatchClosedError(batch_id, batch.status)
        now = datetime.now(UTC)
        approve_set = set(approve_candidate_ids)
        skip_set = set(skip_candidate_ids)
        changed: list[ImageReviewCandidateRecord] = []
        for candidate in self.list_image_review_candidates_for_batch(batch_id):
            status = candidate.status
            skip_reason = candidate.skip_reason
            if status == "pending" and (candidate.id in approve_set or (approve_recommended and candidate.recommended)):
                status = "approved"
                skip_reason = None
            elif status == "pending" and (candidate.id in skip_set or skip_remaining):
                status = "skipped"
                skip_reason = "reviewer_skipped"
            if status != candidate.status or skip_reason != candidate.skip_reason:
                updated = replace(candidate, status=status, assigned_to=reviewer_id, skip_reason=skip_reason, updated_at=now)
                self._image_review_candidates[candidate.id] = updated
                changed.append(updated)
        all_candidates = self.list_image_review_candidates_for_batch(batch_id)
        complete = all(candidate.status != "pending" for candidate in all_candidates)
        if complete:
            batch = replace(batch, status="approved", updated_at=now)
        else:
            batch = replace(batch, updated_at=now)
        self._image_review_batches[batch.id] = batch
        return ImageReviewDecisionRecord(batch=batch, candidates=tuple(changed), batch_complete=complete)

    def get_image_review_approved_keys(self, batch_id: str) -> list[str]:
        return [
            candidate.candidate_key
            for candidate in self.list_image_review_candidates_for_batch(batch_id)
            if candidate.status == "approved"
        ]
