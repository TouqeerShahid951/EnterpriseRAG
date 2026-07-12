"""In-memory ingest-job repository behavior."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from functools import wraps
from typing import Any
from uuid import uuid4

from ..job_models import (
    IngestAttemptResult,
    IngestJobAccess,
    IngestJobCancellationResult,
    IngestJobFilters,
    IngestJobMutationResult,
    IngestJobPage,
    IngestJobRecord,
    IngestJobView,
)


def _synchronized_ingest(method: Any) -> Any:
    @wraps(method)
    def synchronized(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self._ingest_lock:
            return method(self, *args, **kwargs)

    return synchronized




class InMemoryIngestJobRepositoryMixin:
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
            run_token=None,
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
            key=_ingest_job_sort_key,
            reverse=True,
        )

    def get_latest_ingest_job_for_document(
        self,
        doc_id: str,
        *,
        statuses: frozenset[str],
    ) -> IngestJobRecord | None:
        jobs = [
            job
            for job in self._jobs.values()
            if job.doc_id == doc_id and job.status in statuses
        ]
        return max(jobs, key=_ingest_job_sort_key) if jobs else None

    @_synchronized_ingest
    def update_ingest_job(
        self,
        job_id: str,
        *,
        status: str,
        progress_pct: int,
        stage_progress: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        error_code: str | None = None,
        error_message_safe: str | None = None,
        expected_statuses: frozenset[str] | None = None,
        stale_before: datetime | None = None,
        run_token: str | None = None,
    ) -> IngestJobMutationResult:
        job = self._jobs.get(job_id)
        if job is None:
            return IngestJobMutationResult(job=None, changed=False)
        if job.status == "cancelled" and status != "cancelled":
            return IngestJobMutationResult(job=job, changed=False)
        if expected_statuses is not None and job.status not in expected_statuses:
            return IngestJobMutationResult(job=job, changed=False)
        last_activity = job.last_heartbeat_at or job.updated_at or job.created_at
        if stale_before is not None and last_activity is not None and last_activity >= stale_before:
            return IngestJobMutationResult(job=job, changed=False)
        if not _run_token_can_update(job, run_token=run_token, next_status=status):
            return IngestJobMutationResult(job=job, changed=False)
        now = datetime.now(UTC)
        progress_is_stale = (
            job.status == "processing"
            and status == "processing"
            and progress_pct < job.progress_pct
        )
        updated = replace(
            job,
            status=status,
            progress_pct=max(job.progress_pct, progress_pct)
            if job.status == "processing" and status == "processing"
            else progress_pct,
            stage_progress=job.stage_progress if progress_is_stale else stage_progress,
            warnings=tuple(warnings) if warnings is not None else job.warnings,
            error_code=error_code,
            error_message_safe=error_message_safe,
            run_token=_next_run_token(job, run_token=run_token, next_status=status),
            updated_at=now,
            completed_at=now if status in {"complete", "failed", "human_review", "cancelled"} else None,
        )
        self._jobs[job_id] = updated
        self._documents[job.doc_id] = replace(self._documents[job.doc_id], ingest_status=status, updated_at=now)
        return IngestJobMutationResult(job=updated, changed=True)

    @_synchronized_ingest
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
            run_token=None,
            completed_at=None,
            updated_at=now,
        )
        self._jobs[job_id] = updated
        document = self._documents.get(job.doc_id)
        if document is not None:
            self._documents[job.doc_id] = replace(document, ingest_status="queued", updated_at=now)
        return updated

    @_synchronized_ingest
    def start_ingest_attempt(
        self,
        job_id: str,
        *,
        max_attempts: int,
        stale_after_seconds: int = 120,
        run_token: str | None = None,
    ) -> IngestAttemptResult:
        job = self._jobs.get(job_id)
        selected_token = run_token
        if (
            selected_token is not None
            and job is not None
            and job.status == "processing"
            and job.run_token == selected_token
        ):
            return IngestAttemptResult(job=job, claimed=True)
        now = datetime.now(UTC)
        heartbeat = job.last_heartbeat_at or job.updated_at or job.created_at if job else None
        processing_is_stale = heartbeat is None or (now - heartbeat).total_seconds() >= stale_after_seconds
        if (
            job is None
            or job.status not in {"queued", "processing"}
            or (job.status == "processing" and not processing_is_stale)
            or job.attempt_count >= max_attempts
        ):
            return IngestAttemptResult(job=job, claimed=False)
        updated = replace(
            job,
            status="processing",
            attempt_count=job.attempt_count + 1,
            last_heartbeat_at=now,
            run_token=selected_token,
            error_code=None,
            error_message_safe=None,
            completed_at=None,
            updated_at=now,
        )
        self._jobs[job_id] = updated
        self._documents[job.doc_id] = replace(self._documents[job.doc_id], ingest_status="processing", updated_at=now)
        return IngestAttemptResult(job=updated, claimed=True)

    @_synchronized_ingest
    def heartbeat_ingest_job(
        self, job_id: str, *, run_token: str | None = None
    ) -> IngestJobMutationResult:
        job = self._jobs.get(job_id)
        if (
            job is None
            or job.status != "processing"
            or job.run_token != run_token
        ):
            return IngestJobMutationResult(job=job, changed=False)
        updated = replace(job, last_heartbeat_at=datetime.now(UTC))
        self._jobs[job_id] = updated
        return IngestJobMutationResult(job=updated, changed=True)

    @_synchronized_ingest
    def record_ingest_parser_provenance(
        self,
        job_id: str,
        *,
        provenance: dict[str, Any],
        run_token: str | None = None,
    ) -> IngestJobRecord | None:
        job = self._jobs.get(job_id)
        if (
            job is None
            or job.status != "processing"
            or job.run_token != run_token
        ):
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

    @_synchronized_ingest
    def cancel_ingest_job(
        self,
        job_id: str,
        *,
        allowed_statuses: frozenset[str],
    ) -> IngestJobCancellationResult:
        job = self._jobs.get(job_id)
        if job is None:
            return IngestJobCancellationResult(job=None, changed=False, review_items_closed=0)
        if job.status not in allowed_statuses:
            return IngestJobCancellationResult(job=job, changed=False, review_items_closed=0)
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
        updated = replace(
            job,
            status="cancelled",
            stage_progress=None,
            error_code=None,
            error_message_safe=None,
            run_token=None,
            updated_at=now,
            completed_at=now,
        )
        self._jobs[job_id] = updated
        document = self._documents.get(job.doc_id)
        if document is not None:
            self._documents[job.doc_id] = replace(document, ingest_status="cancelled", updated_at=now)
        return IngestJobCancellationResult(
            job=updated,
            changed=True,
            review_items_closed=cancelled_items,
        )

    def search_visible_ingest_jobs(
        self,
        *,
        access: IngestJobAccess,
        filters: IngestJobFilters,
        limit: int | None,
        offset: int = 0,
    ) -> IngestJobPage:
        _validate_ingest_job_page(limit=limit, offset=offset)
        query = (filters.search or "").strip().lower()
        visible_groups = set(access.group_paths or ())
        views: list[IngestJobView] = []
        for job in self._jobs.values():
            document = self._documents.get(job.doc_id)
            if document is None or document.clearance_level not in access.clearance_levels:
                continue
            document = self._with_shares(document)
            if access.group_paths is not None and not visible_groups.intersection(document.access_group_paths):
                continue
            if filters.status and job.status != filters.status:
                continue
            if filters.origin and job.origin != filters.origin:
                continue
            if filters.group_path and document.group_path != filters.group_path:
                continue
            if filters.created_from and (job.created_at is None or job.created_at < filters.created_from):
                continue
            if filters.created_to and (job.created_at is None or job.created_at > filters.created_to):
                continue
            if filters.uploaded_by_user_id and document.uploaded_by != filters.uploaded_by_user_id:
                continue
            searchable = " ".join((job.id, job.doc_id, document.title or "", document.group_path)).lower()
            if query and query not in searchable:
                continue
            views.append(
                IngestJobView(
                    job=job,
                    document_title=document.title or document.id,
                    group_path=document.group_path,
                    clearance_level=document.clearance_level,
                    uploaded_by=document.uploaded_by,
                )
            )
        views.sort(key=lambda view: _ingest_job_sort_key(view.job), reverse=True)
        total = len(views)
        selected = views[offset:] if limit is None else views[offset:offset + limit]
        return IngestJobPage(items=tuple(selected), total=total)


def _ingest_job_sort_key(job: IngestJobRecord) -> tuple[datetime, str]:
    return (job.created_at or datetime.min.replace(tzinfo=UTC), job.id)


def _validate_ingest_job_page(*, limit: int | None, offset: int) -> None:
    if limit is not None and limit < 0:
        raise ValueError("ingestion job search limit must be nonnegative")
    if offset < 0:
        raise ValueError("ingestion job search offset must be nonnegative")


def _run_token_can_update(
    current: IngestJobRecord,
    *,
    run_token: str | None,
    next_status: str,
) -> bool:
    if current.run_token is not None:
        return current.run_token == run_token
    if run_token is None:
        return True
    return current.status == "queued" and next_status == "processing"


def _next_run_token(
    current: IngestJobRecord,
    *,
    run_token: str | None,
    next_status: str,
) -> str | None:
    if next_status != "processing":
        return None
    if current.run_token is None and run_token is not None:
        return run_token
    return current.run_token

