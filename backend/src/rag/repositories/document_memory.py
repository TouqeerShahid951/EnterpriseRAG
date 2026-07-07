"""In-memory document repository for fast route tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import uuid4

from ..auth.abac import normalize_group_path
from ..shared.contracts.clearance import ClearanceLevel, normalize_clearance_level
from .document_models import (
    AuditEventRecord,
    DocumentCrossReferenceRecord,
    DocumentEntityRecord,
    DocumentImageAssetRecord,
    DocumentRecord,
    ImageReviewBatchRecord,
    ImageReviewCandidateRecord,
    ImageReviewDecisionRecord,
    IngestJobRecord,
    ReviewBatchRecord,
    ReviewDecisionRecord,
    ReviewItemRecord,
)


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self._documents: dict[str, DocumentRecord] = {}
        self._entities: dict[str, list[DocumentEntityRecord]] = {}
        self._cross_references: dict[str, list[DocumentCrossReferenceRecord]] = {}
        self._jobs: dict[str, IngestJobRecord] = {}
        self._review_batches: dict[str, ReviewBatchRecord] = {}
        self._review_items: dict[str, ReviewItemRecord] = {}
        self._image_review_batches: dict[str, ImageReviewBatchRecord] = {}
        self._image_review_candidates: dict[str, ImageReviewCandidateRecord] = {}
        self._image_assets: dict[str, DocumentImageAssetRecord] = {}
        self._edges: set[tuple[str, str]] = set()
        self._shares: dict[str, set[str]] = {}
        self.audit_events: list[dict[str, Any]] = []

    def create_document(self, **kwargs: Any) -> DocumentRecord:
        if any(document.source_id == kwargs["source_id"] for document in self._documents.values()):
            raise ValueError("source_id already exists")
        now = datetime.now(UTC)
        record = DocumentRecord(
            id=kwargs.get("document_id") or str(uuid4()),
            title=kwargs["title"],
            source_id=kwargs["source_id"].strip(),
            group_path=normalize_group_path(kwargs["group_path"]),
            clearance_level=normalize_clearance_level(kwargs.get("clearance_level")),
            doc_type=kwargs["doc_type"],
            language=None,
            effective_date=kwargs["effective_date"],
            expiry_date=kwargs.get("expiry_date"),
            description=kwargs.get("description"),
            summary=None,
            topics=tuple(),
            llm_topics=tuple(),
            auto_doc_type=None,
            extracted_dates={},
            metadata_flags={},
            is_current=True,
            superseded_by=None,
            pending_supersedes=tuple(kwargs["pending_supersedes"]),
            content_hash=kwargs["content_hash"],
            uploaded_by=kwargs["uploaded_by"],
            file_path=kwargs["file_path"],
            ingest_status=kwargs["ingest_status"],
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
        self._documents[record.id] = record
        self._shares[record.id] = set()
        return record

    def list_documents(self, *, state: Literal["active", "deleted"] = "active") -> list[DocumentRecord]:
        if state not in {"active", "deleted"}:
            raise ValueError("document state must be active or deleted")
        return sorted(
            [
                self._with_shares(document)
                for document in self._documents.values()
                if (document.deleted_at is None) == (state == "active")
            ],
            key=lambda document: document.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

    def get_document(self, document_id: str, *, include_deleted: bool = False) -> DocumentRecord | None:
        document = self._documents.get(document_id)
        return None if document is None or (document.deleted_at is not None and not include_deleted) else self._with_shares(document)

    def list_document_shares(self, document_id: str) -> list[str]:
        return sorted(self._shares.get(document_id, set()))

    def replace_document_shares(
        self,
        document_id: str,
        *,
        group_paths: list[str],
        actor_id: str | None,
    ) -> DocumentRecord | None:
        _ = actor_id
        document = self._documents.get(document_id)
        if document is None:
            return None
        owner_group = normalize_group_path(document.group_path)
        shares = {
            normalize_group_path(path)
            for path in group_paths
            if normalize_group_path(path) != owner_group
        }
        self._shares[document_id] = shares
        updated = replace(document, updated_at=datetime.now(UTC))
        self._documents[document_id] = updated
        return self._with_shares(updated)

    def replace_document_access_scope(
        self,
        document_id: str,
        *,
        owner_group_path: str,
        shared_group_paths: list[str],
        actor_id: str | None,
    ) -> DocumentRecord | None:
        _ = actor_id
        document = self._documents.get(document_id)
        if document is None:
            return None
        owner_group = normalize_group_path(owner_group_path)
        shares = {
            normalize_group_path(path)
            for path in shared_group_paths
            if normalize_group_path(path) != owner_group
        }
        updated = replace(document, group_path=owner_group, updated_at=datetime.now(UTC))
        self._documents[document_id] = updated
        self._shares[document_id] = shares
        return self._with_shares(updated)

    def remove_document_share(self, document_id: str, group_path: str) -> DocumentRecord | None:
        document = self._documents.get(document_id)
        if document is None:
            return None
        self._shares.setdefault(document_id, set()).discard(normalize_group_path(group_path))
        updated = replace(document, updated_at=datetime.now(UTC))
        self._documents[document_id] = updated
        return self._with_shares(updated)

    def update_document_clearance(self, document_id: str, clearance_level: ClearanceLevel) -> DocumentRecord | None:
        document = self.get_document(document_id)
        if document is None:
            return None
        updated = replace(
            document,
            clearance_level=normalize_clearance_level(clearance_level),
            updated_at=datetime.now(UTC),
        )
        self._documents[document_id] = updated
        return updated

    def update_document_topics(
        self,
        document_id: str,
        *,
        topics: list[str],
        llm_topics: list[str],
    ) -> DocumentRecord | None:
        document = self.get_document(document_id)
        if document is None:
            return None
        updated = replace(
            document,
            topics=tuple(_unique_text(topics)),
            llm_topics=tuple(_unique_text(llm_topics)),
            updated_at=datetime.now(UTC),
        )
        self._documents[document_id] = updated
        return updated

    def mark_document_stale(
        self,
        document_id: str,
        *,
        source_deleted: bool = True,
        retrieval_status: str = "stale",
        reason: str = "source_deleted",
    ) -> DocumentRecord | None:
        document = self.get_document(document_id)
        if document is None:
            return None
        flags = {
            **document.metadata_flags,
            "source_deleted": source_deleted,
            "retrieval_status": retrieval_status,
            "stale_reason": reason,
            "stale_at": datetime.now(UTC).isoformat(),
        }
        updated = replace(document, metadata_flags=flags, updated_at=datetime.now(UTC))
        self._documents[document_id] = updated
        return updated

    def find_current_by_content_hash(self, content_hash: str) -> DocumentRecord | None:
        return next(
            (
                document
                for document in self._documents.values()
                if document.content_hash == content_hash
                and document.deleted_at is None
                and document.is_current
            ),
            None,
        )

    def save_document_metadata(
        self,
        *,
        document_id: str,
        summary: str | None,
        language: str | None,
        topics: list[str],
        llm_topics: list[str],
        doc_type: str | None = None,
        auto_doc_type: str | None,
        extracted_dates: dict[str, Any],
        metadata_flags: dict[str, Any],
        entities: list[DocumentEntityRecord],
        cross_references: list[DocumentCrossReferenceRecord],
    ) -> DocumentRecord | None:
        document = self.get_document(document_id)
        if document is None:
            return None
        now = datetime.now(UTC)
        updated = replace(
            document,
            summary=summary,
            language=language,
            topics=tuple(_unique_text(topics)),
            llm_topics=tuple(_unique_text(llm_topics)),
            doc_type=doc_type or document.doc_type,
            auto_doc_type=auto_doc_type,
            extracted_dates=dict(extracted_dates),
            metadata_flags=dict(metadata_flags),
            updated_at=now,
        )
        self._documents[document_id] = updated
        self._entities[document_id] = [replace(entity, doc_id=document_id) for entity in entities]
        self._cross_references[document_id] = [replace(ref, doc_id=document_id) for ref in cross_references]
        return updated

    def list_document_entities(self, document_id: str) -> list[DocumentEntityRecord]:
        return list(self._entities.get(document_id, []))

    def list_document_cross_references(self, document_id: str) -> list[DocumentCrossReferenceRecord]:
        return list(self._cross_references.get(document_id, []))

    def soft_delete_document(self, document_id: str) -> DocumentRecord | None:
        document = self.get_document(document_id)
        if document is None:
            return None
        now = datetime.now(UTC)
        updated = replace(document, deleted_at=now, is_current=False, updated_at=now)
        self._documents[document_id] = updated
        return updated

    def restore_document(self, document_id: str) -> DocumentRecord | None:
        document = self.get_document(document_id, include_deleted=True)
        if document is None or document.deleted_at is None:
            return None
        is_current = not any(old_id == document_id for old_id, _ in self._edges) and document.superseded_by is None
        now = datetime.now(UTC)
        updated = replace(document, deleted_at=None, is_current=is_current, updated_at=now)
        self._documents[document_id] = updated
        return updated

    def permanently_delete_document(self, document_id: str) -> DocumentRecord | None:
        document = self.get_document(document_id, include_deleted=True)
        if document is None:
            return None
        del self._documents[document_id]
        self._entities.pop(document_id, None)
        self._cross_references.pop(document_id, None)
        self._jobs = {job_id: job for job_id, job in self._jobs.items() if job.doc_id != document_id}
        self._review_batches = {batch_id: batch for batch_id, batch in self._review_batches.items() if batch.doc_id != document_id}
        self._review_items = {item_id: item for item_id, item in self._review_items.items() if item.doc_id != document_id}
        self._image_assets = {asset_id: asset for asset_id, asset in self._image_assets.items() if asset.doc_id != document_id}
        self._edges = {(old_id, new_id) for old_id, new_id in self._edges if old_id != document_id and new_id != document_id}
        self._shares.pop(document_id, None)
        now = datetime.now(UTC)
        for related_id, related in list(self._documents.items()):
            if related.superseded_by == document_id:
                self._documents[related_id] = replace(related, superseded_by=None, updated_at=now)
        return document

    def _with_shares(self, document: DocumentRecord) -> DocumentRecord:
        return replace(document, shared_group_paths=tuple(sorted(self._shares.get(document.id, set()))))

    def create_ingest_job(
        self,
        *,
        doc_id: str,
        status: str,
        progress_pct: int,
        origin: str = "unknown",
        retry_of_job_id: str | None = None,
    ) -> IngestJobRecord:
        if doc_id not in self._documents:
            raise ValueError("document does not exist")
        if retry_of_job_id is not None and retry_of_job_id not in self._jobs:
            raise ValueError("retry source job does not exist")
        now = datetime.now(UTC)
        job = IngestJobRecord(
            id=str(uuid4()),
            doc_id=doc_id,
            retry_of_job_id=retry_of_job_id,
            origin=origin,
            status=status,
            progress_pct=progress_pct,
            stage_progress=None,
            attempt_count=0,
            last_heartbeat_at=None,
            warnings=(),
            parser_provenance=None,
            error_code=None,
            error_message_safe=None,
            created_at=now,
            updated_at=now,
            completed_at=now if status in {"complete", "failed", "human_review", "cancelled"} else None,
        )
        self._jobs[job.id] = job
        self._documents[doc_id] = replace(self._documents[doc_id], ingest_status=status, updated_at=now)
        return job

    def get_ingest_job(self, job_id: str) -> IngestJobRecord | None:
        return self._jobs.get(job_id)

    def list_ingest_jobs(self) -> list[IngestJobRecord]:
        return sorted(
            self._jobs.values(),
            key=lambda job: job.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

    def get_active_ingest_job_for_document(self, doc_id: str) -> IngestJobRecord | None:
        active_statuses = {"scheduled", "queued", "processing", "human_review"}
        jobs = [
            job
            for job in self._jobs.values()
            if job.doc_id == doc_id and job.status in active_statuses
        ]
        return sorted(jobs, key=lambda job: job.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)[0] if jobs else None

    def update_ingest_job(self, job_id: str, **kwargs: Any) -> IngestJobRecord | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.status == "cancelled" and kwargs["status"] != "cancelled":
            return job
        now = datetime.now(UTC)
        status = kwargs["status"]
        updated = replace(
            job,
            status=status,
            progress_pct=kwargs["progress_pct"],
            stage_progress=kwargs.get("stage_progress"),
            warnings=tuple(kwargs["warnings"]) if kwargs.get("warnings") is not None else job.warnings,
            error_code=kwargs.get("error_code"),
            error_message_safe=kwargs.get("error_message_safe"),
            updated_at=now,
            completed_at=now if status in {"complete", "failed", "human_review", "cancelled"} else None,
        )
        self._jobs[job_id] = updated
        self._documents[job.doc_id] = replace(self._documents[job.doc_id], ingest_status=status, updated_at=now)
        return updated

    def requeue_stale_ingest_job(
        self,
        job_id: str,
        *,
        stale_before: datetime,
        max_attempts: int,
    ) -> IngestJobRecord | None:
        job = self._jobs.get(job_id)
        last_activity = job.last_heartbeat_at or job.updated_at or job.created_at if job else None
        if (
            job is None
            or job.status != "processing"
            or job.attempt_count >= max_attempts
            or (last_activity is not None and last_activity >= stale_before)
        ):
            return None
        now = datetime.now(UTC)
        updated = replace(
            job,
            status="queued",
            progress_pct=0,
            error_code=None,
            error_message_safe=None,
            completed_at=None,
            updated_at=now,
        )
        self._jobs[job_id] = updated
        document = self._documents.get(job.doc_id)
        if document is not None:
            self._documents[job.doc_id] = replace(document, ingest_status="queued", updated_at=now)
        return updated

    def start_ingest_attempt(
        self,
        job_id: str,
        *,
        max_attempts: int,
        stale_after_seconds: int = 120,
    ) -> IngestJobRecord | None:
        job = self._jobs.get(job_id)
        now = datetime.now(UTC)
        heartbeat = job.last_heartbeat_at or job.updated_at or job.created_at if job else None
        processing_is_stale = heartbeat is None or (now - heartbeat).total_seconds() >= stale_after_seconds
        if (
            job is None
            or job.status not in {"queued", "processing"}
            or (job.status == "processing" and not processing_is_stale)
            or job.attempt_count >= max_attempts
        ):
            return job
        updated = replace(
            job,
            status="processing",
            attempt_count=job.attempt_count + 1,
            last_heartbeat_at=now,
            error_code=None,
            error_message_safe=None,
            completed_at=None,
            updated_at=now,
        )
        self._jobs[job_id] = updated
        self._documents[job.doc_id] = replace(self._documents[job.doc_id], ingest_status="processing", updated_at=now)
        return updated

    def heartbeat_ingest_job(self, job_id: str) -> IngestJobRecord | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        updated = replace(job, last_heartbeat_at=datetime.now(UTC))
        self._jobs[job_id] = updated
        return updated

    def record_ingest_parser_provenance(self, job_id: str, *, provenance: dict[str, Any]) -> IngestJobRecord | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        updated = replace(job, parser_provenance=dict(provenance), updated_at=datetime.now(UTC))
        self._jobs[job_id] = updated
        self.append_audit_event(
            event_type="internal.ingest.parser_provenance",
            actor_id=None,
            target_type="ingest_job",
            target_id=job.id,
            payload={"doc_id": job.doc_id, "provenance": dict(provenance)},
        )
        return updated

    def cancel_review_batch_for_job(self, job_id: str) -> int:
        batches = [batch for batch in self._review_batches.values() if batch.job_id == job_id and batch.status == "pending"]
        now = datetime.now(UTC)
        batch_ids = {batch.id for batch in batches}
        cancelled_items = 0
        for batch in batches:
            self._review_batches[batch.id] = replace(batch, status="rejected", updated_at=now)
        for item_id, item in list(self._review_items.items()):
            if item.batch_id in batch_ids and item.status == "pending":
                self._review_items[item_id] = replace(item, status="rejected", updated_at=now)
                cancelled_items += 1
        image_batches = [batch for batch in self._image_review_batches.values() if batch.job_id == job_id and batch.status == "pending"]
        image_batch_ids = {batch.id for batch in image_batches}
        for batch in image_batches:
            self._image_review_batches[batch.id] = replace(batch, status="rejected", updated_at=now)
        for candidate_id, candidate in list(self._image_review_candidates.items()):
            if candidate.batch_id in image_batch_ids and candidate.status == "pending":
                self._image_review_candidates[candidate_id] = replace(
                    candidate,
                    status="skipped",
                    assigned_to=None,
                    skip_reason="ingest_cancelled",
                    updated_at=now,
                )
                cancelled_items += 1
        return cancelled_items

    def mark_superseded(self, *, new_doc_id: str, old_doc_ids: list[str]) -> list[DocumentRecord]:
        return mark_superseded(self, new_doc_id=new_doc_id, old_doc_ids=old_doc_ids)

    def list_version_chain(self, document_id: str) -> list[DocumentRecord]:
        return list_version_chain(self, document_id)

    def list_superseded_document_ids(self, document_id: str) -> list[str]:
        return sorted(old_id for old_id, new_id in self._edges if new_id == document_id)

    def append_audit_event(self, **kwargs: Any) -> None:
        self.audit_events.append({
            "id": str(uuid4()),
            "created_at": datetime.now(UTC),
            **dict(kwargs),
        })

    def list_audit_events(self, *, limit: int = 100) -> list[AuditEventRecord]:
        events = sorted(self.audit_events, key=lambda event: event.get("created_at") or datetime.min.replace(tzinfo=UTC), reverse=True)
        return [_audit_event_from_dict(event) for event in events[:limit]]

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

    def replace_document_image_assets(
        self,
        *,
        doc_id: str,
        job_id: str,
        assets: list[dict[str, Any]],
    ) -> list[DocumentImageAssetRecord]:
        if doc_id not in self._documents:
            raise ValueError("document does not exist")
        self._image_assets = {asset_id: asset for asset_id, asset in self._image_assets.items() if asset.doc_id != doc_id}
        now = datetime.now(UTC)
        records: list[DocumentImageAssetRecord] = []
        for asset in assets:
            record = DocumentImageAssetRecord(
                id=str(asset.get("id") or uuid4()),
                doc_id=doc_id,
                job_id=job_id,
                source_kind=str(asset.get("source_kind") or "image"),
                page=_int_or_none(asset.get("page")),
                bbox=_bbox_list(asset.get("bbox")),
                object_path=str(asset["object_path"]),
                content_type=str(asset.get("content_type") or "image/jpeg"),
                width=_int_or_none(asset.get("width")),
                height=_int_or_none(asset.get("height")),
                content_hash=str(asset["content_hash"]),
                extracted_text=str(asset["extracted_text"]) if asset.get("extracted_text") is not None else None,
                caption=str(asset["caption"]) if asset.get("caption") is not None else None,
                confidence=float(asset["confidence"]) if isinstance(asset.get("confidence"), (int, float)) else None,
                quality_flags=tuple(str(flag) for flag in asset.get("quality_flags", []) if str(flag)),
                created_at=now,
            )
            self._image_assets[record.id] = record
            records.append(record)
        return records

    def list_document_image_assets(self, document_id: str) -> list[DocumentImageAssetRecord]:
        return sorted(
            [asset for asset in self._image_assets.values() if asset.doc_id == document_id],
            key=lambda asset: (asset.page or 0, asset.id),
        )

    def get_document_image_asset(self, document_id: str, asset_id: str) -> DocumentImageAssetRecord | None:
        asset = self._image_assets.get(asset_id)
        return asset if asset is not None and asset.doc_id == document_id else None


def mark_superseded(repo: InMemoryDocumentRepository, *, new_doc_id: str, old_doc_ids: list[str]) -> list[DocumentRecord]:
    if new_doc_id not in repo._documents:
        raise ValueError("new document does not exist")
    if len(set(old_doc_ids)) != len(old_doc_ids):
        raise ValueError("supersedes contains duplicate document ids")
    updated: list[DocumentRecord] = []
    for old_doc_id in old_doc_ids:
        _validate_new_edge(repo._documents, repo._edges, old_doc_id, new_doc_id)
        old = repo._documents[old_doc_id]
        next_old = replace(old, is_current=False, superseded_by=new_doc_id, updated_at=datetime.now(UTC))
        repo._documents[old_doc_id] = next_old
        repo._edges.add((old_doc_id, new_doc_id))
        updated.append(next_old)
    return updated


def list_version_chain(repo: InMemoryDocumentRepository, document_id: str) -> list[DocumentRecord]:
    ids = {document_id}
    changed = True
    while changed:
        changed = False
        for old_id, new_id in repo._edges:
            if old_id in ids or new_id in ids:
                changed |= old_id not in ids or new_id not in ids
                ids.update({old_id, new_id})
    return sorted((repo._documents[doc_id] for doc_id in ids if doc_id in repo._documents), key=_version_sort_key)


def _audit_event_from_dict(event: dict[str, Any]) -> AuditEventRecord:
    return AuditEventRecord(
        id=str(event["id"]),
        event_type=str(event["event_type"]),
        actor_id=str(event["actor_id"]) if event.get("actor_id") is not None else None,
        target_type=str(event["target_type"]) if event.get("target_type") is not None else None,
        target_id=str(event["target_id"]) if event.get("target_id") is not None else None,
        payload=dict(event.get("payload") or {}),
        created_at=event.get("created_at"),
    )


def _validate_new_edge(
    documents: dict[str, DocumentRecord],
    edges: set[tuple[str, str]],
    old_doc_id: str,
    new_doc_id: str,
) -> None:
    if old_doc_id == new_doc_id:
        raise ValueError("document cannot supersede itself")
    if old_doc_id not in documents:
        raise ValueError(f"superseded document does not exist: {old_doc_id}")
    if _has_path(edges, new_doc_id, old_doc_id):
        raise ValueError("supersession would create a cycle")


def _has_path(edges: set[tuple[str, str]], start: str, target: str) -> bool:
    frontier = [start]
    seen: set[str] = set()
    while frontier:
        current = frontier.pop()
        if current == target:
            return True
        seen.add(current)
        frontier.extend(new for old, new in edges if old == current and new not in seen)
    return False


def _version_sort_key(document: DocumentRecord) -> tuple[date, str]:
    return (document.effective_date or date.min, document.id)


def _unique_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            normalized.append(text)
    return normalized


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bbox_list(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None
