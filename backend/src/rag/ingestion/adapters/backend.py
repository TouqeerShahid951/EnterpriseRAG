"""Backend internal API client for ingestion status mutations."""

from __future__ import annotations

from dataclasses import dataclass
import json
from threading import Lock
from typing import Any

from .http import ServiceRequestError, request_json


@dataclass(frozen=True)
class InferenceRuntimeConfig:
    base_url: str
    chat_model: str
    embed_model: str
    faithfulness_model: str | None
    chat_timeout_seconds: float
    embed_timeout_seconds: float
    provider: str = "ollama"
    embedding_provider: str = "ollama"
    reasoning_provider: str | None = None
    routing_provider: str | None = None
    faithfulness_provider: str | None = None
    ingestion_provider: str | None = None
    vision_provider: str | None = None
    embedding_base_url: str = ""
    reasoning_base_url: str | None = None
    routing_base_url: str | None = None
    faithfulness_base_url: str | None = None
    ingestion_base_url: str | None = None
    vision_base_url: str | None = None
    thinking_enabled: bool = False
    routing_model: str | None = None
    ingestion_model: str | None = None
    vision_model: str | None = None

    def __post_init__(self) -> None:
        if not self.embedding_base_url:
            object.__setattr__(self, "embedding_base_url", self.base_url)
        if not self.ingestion_base_url:
            object.__setattr__(self, "ingestion_base_url", self.base_url)
        if not self.vision_base_url:
            object.__setattr__(self, "vision_base_url", self.ingestion_base_url)
        for field_name in (
            "reasoning_provider",
            "routing_provider",
            "faithfulness_provider",
            "ingestion_provider",
            "vision_provider",
        ):
            if not getattr(self, field_name):
                object.__setattr__(self, field_name, self.provider)


@dataclass(frozen=True)
class IngestAttempt:
    accepted: bool
    disposition: str
    attempt_count: int
    max_attempts: int
    job_status: str
    run_token: str | None = None
    failure_attempt_count: int = 0


@dataclass(frozen=True)
class IngestFailure:
    job_status: str
    failure_attempt_count: int
    retry_scheduled: bool
    changed: bool


@dataclass(frozen=True)
class IngestRuntimeConfig:
    worker_concurrency: int
    ocr_review_confidence_threshold: float
    pdf_image_review_threshold: int = 64
    vision_layout_repair_enabled: bool = False
    graph_enrichment_enabled: bool = False
    source: str = "workspace"


@dataclass(frozen=True)
class IngestJobSnapshot:
    job_id: str
    doc_id: str
    status: str


class BackendInternalClient:
    def __init__(self, *, base_url: str, service_token: str, timeout_seconds: float) -> None:
        if not service_token:
            raise ValueError("SERVICE_TOKEN is required for backend internal callbacks")
        self.base_url = base_url
        self.service_token = service_token
        self.timeout_seconds = timeout_seconds
        self._run_tokens: dict[str, str] = {}
        self._lease_lost_jobs: set[str] = set()
        self._lease_state_lock = Lock()

    def update_job(
        self,
        *,
        job_id: str,
        status: str,
        progress_pct: int,
        stage_progress: dict[str, object] | None = None,
        error_code: str | None = None,
        error_message_safe: str | None = None,
        warnings: list[str] | None = None,
        run_token: str | None = None,
    ) -> None:
        selected_run_token = run_token or self._current_run_token(job_id)
        payload: dict[str, object | None] = {
            "status": status,
            "progress_pct": progress_pct,
            "error_code": error_code,
            "error_message_safe": error_message_safe,
        }
        if selected_run_token is not None:
            payload["run_token"] = selected_run_token
        if stage_progress is not None:
            payload["stage_progress"] = stage_progress
        if warnings is not None:
            payload["warnings"] = warnings
        try:
            request_json(
                self.base_url,
                f"/internal/ingest/jobs/{job_id}/status",
                service="backend",
                method="POST",
                payload=payload,
                headers={"X-Service-Token": self.service_token},
                timeout_seconds=self.timeout_seconds,
            )
        except ServiceRequestError as exc:
            if exc.status_code == 409 and selected_run_token is not None:
                self._mark_lease_lost(job_id)
            raise
        if selected_run_token is not None:
            if status == "processing":
                self._bind_run_token(job_id, selected_run_token)
            else:
                self._clear_run_token(job_id)

    def start_attempt(
        self,
        *,
        job_id: str,
        run_token: str,
        delivery_id: str | None = None,
    ) -> IngestAttempt:
        request_payload = {"run_token": run_token}
        if delivery_id is not None:
            request_payload["delivery_id"] = delivery_id
        try:
            payload = request_json(
                self.base_url,
                f"/internal/ingest/jobs/{job_id}/attempt",
                service="backend",
                method="POST",
                payload=request_payload,
                headers={"X-Service-Token": self.service_token},
                timeout_seconds=self.timeout_seconds,
            )
        except ServiceRequestError as exc:
            if delivery_id is None or not _legacy_attempt_rejects_delivery_id(exc):
                raise
            payload = request_json(
                self.base_url,
                f"/internal/ingest/jobs/{job_id}/attempt",
                service="backend",
                method="POST",
                payload={"run_token": run_token},
                headers={"X-Service-Token": self.service_token},
                timeout_seconds=self.timeout_seconds,
            )
        response_run_token = payload.get("run_token")
        accepted_run_token = (
            str(response_run_token)
            if payload.get("status") == "accepted" and response_run_token
            else None
        )
        if payload.get("status") == "accepted" and accepted_run_token != run_token:
            raise RuntimeError("backend returned an invalid ingestion job run token")
        if accepted_run_token is not None:
            self._bind_run_token(job_id, accepted_run_token)
        return IngestAttempt(
            accepted=payload.get("status") == "accepted",
            disposition=str(payload["status"]),
            attempt_count=int(payload["attempt_count"]),
            max_attempts=int(payload["max_attempts"]),
            job_status=str(payload["job_status"]),
            run_token=accepted_run_token,
            failure_attempt_count=int(payload.get("failure_attempt_count") or 0),
        )

    def record_failure(
        self,
        *,
        job_id: str,
        error_code: str,
        error_message_safe: str,
        retry_message: dict[str, Any] | None,
    ) -> IngestFailure:
        run_token = self._require_run_token(job_id)
        request_payload: dict[str, object] = {
            "run_token": run_token,
            "error_code": error_code,
            "error_message_safe": error_message_safe,
        }
        if retry_message is not None:
            request_payload["retry_message"] = retry_message
        try:
            payload = request_json(
                self.base_url,
                f"/internal/ingest/jobs/{job_id}/failure",
                service="backend",
                method="POST",
                payload=request_payload,
                headers={"X-Service-Token": self.service_token},
                timeout_seconds=self.timeout_seconds,
            )
        except ServiceRequestError as exc:
            if exc.status_code == 409:
                self._mark_lease_lost(job_id)
            raise
        if payload.get("changed"):
            self._clear_run_token(job_id)
        return IngestFailure(
            job_status=str(payload["status"]),
            failure_attempt_count=int(payload["failure_attempt_count"]),
            retry_scheduled=bool(payload["retry_scheduled"]),
            changed=bool(payload["changed"]),
        )

    def get_job_status(self, *, job_id: str) -> IngestJobSnapshot:
        payload = request_json(
            self.base_url,
            f"/internal/ingest/jobs/{job_id}/status",
            service="backend",
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )
        return IngestJobSnapshot(
            job_id=str(payload["job_id"]),
            doc_id=str(payload["doc_id"]),
            status=str(payload["status"]),
        )

    def heartbeat(self, *, job_id: str) -> None:
        self.ensure_lease(job_id)
        run_token = self._current_run_token(job_id)
        if run_token is None:
            return
        try:
            request_json(
                self.base_url,
                f"/internal/ingest/jobs/{job_id}/heartbeat",
                service="backend",
                method="POST",
                payload={"run_token": run_token},
                headers={"X-Service-Token": self.service_token},
                timeout_seconds=self.timeout_seconds,
            )
        except ServiceRequestError as exc:
            if exc.status_code == 409:
                self._mark_lease_lost(job_id)
            raise

    def record_event(self, *, job_id: str, event_type: str, payload: dict[str, object]) -> None:
        request_json(
            self.base_url,
            f"/internal/ingest/jobs/{job_id}/events",
            service="backend",
            method="POST",
            payload={"event_type": event_type, "payload": payload},
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )

    def record_parser_provenance(self, *, job_id: str, provenance: dict[str, object]) -> None:
        try:
            request_json(
                self.base_url,
                f"/internal/ingest/jobs/{job_id}/parser-provenance",
                service="backend",
                method="POST",
                payload={
                    "run_token": self._require_run_token(job_id),
                    "provenance": provenance,
                },
                headers={"X-Service-Token": self.service_token},
                timeout_seconds=self.timeout_seconds,
            )
        except ServiceRequestError as exc:
            if exc.status_code == 409:
                self._mark_lease_lost(job_id)
            raise

    def commit_supersession(self, *, new_doc_id: str, supersedes: list[str]) -> None:
        request_json(
            self.base_url,
            f"/internal/docs/{new_doc_id}/supersede",
            service="backend",
            method="POST",
            payload={"supersedes": supersedes},
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )

    def save_claims(self, claims: list[dict[str, str]]) -> None:
        request_json(
            self.base_url,
            "/internal/claims",
            service="backend",
            method="POST",
            payload={"claims": claims},
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )

    def save_ingest_claims(self, *, doc_id: str, claims: list[dict[str, str]]) -> list[str]:
        payload = request_json(
            self.base_url,
            "/internal/claims/ingest",
            service="backend",
            method="POST",
            payload={"doc_id": doc_id, "claims": claims},
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )
        conflicted = payload.get("conflicted_claim_ids")
        return [str(item) for item in conflicted] if isinstance(conflicted, list) else []

    def save_document_metadata(self, *, doc_id: str, metadata: dict[str, Any]) -> None:
        request_json(
            self.base_url,
            f"/internal/docs/{doc_id}/metadata",
            service="backend",
            method="POST",
            payload={
                "summary": metadata.get("summary") or None,
                "language": metadata.get("language") or None,
                "topics": _string_list(metadata.get("topics")),
                "llm_topics": _string_list(metadata.get("llm_topics")),
                "metadata_version": _metadata_version(metadata),
                "metadata_confidence": _dict(metadata.get("metadata_confidence")),
                "metadata_provenance": _dict(metadata.get("metadata_provenance")),
                "doc_type": _derived_doc_type(metadata),
                "auto_doc_type": metadata.get("auto_doc_type") or None,
                "extracted_dates": _dict(metadata.get("extracted_dates")),
                "metadata_flags": _dict(metadata.get("metadata_flags")),
                "entities": _list(metadata.get("named_entities")),
                "cross_references": _list(metadata.get("cross_references")),
            },
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )

    def replace_abbreviation_glossary(
        self,
        *,
        document_id: str,
        entries: list[tuple[str, str]],
    ) -> None:
        request_json(
            self.base_url,
            "/internal/abbreviation-glossaries/import",
            service="backend",
            method="POST",
            payload={
                "document_id": document_id,
                "entries": [
                    {"abbreviation": abbreviation, "expansion": expansion}
                    for abbreviation, expansion in entries
                ],
            },
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )

    def replace_document_image_assets(self, *, doc_id: str, job_id: str, assets: list[dict[str, Any]]) -> None:
        request_json(
            self.base_url,
            f"/internal/docs/{doc_id}/image-assets",
            service="backend",
            method="POST",
            payload={"job_id": job_id, "assets": assets},
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )

    def stage_index_generation(
        self,
        *,
        job_id: str,
        generation_id: str,
        input_hash: str,
        configuration_digest: str,
        expected_point_count: int,
        expected_item_hash: str,
        vector_dimension: int,
        metadata: dict[str, Any],
        claims: list[dict[str, Any]],
        supersedes: list[str],
        warnings: list[str],
        abbreviation_entries: list[dict[str, Any]] | None = None,
    ) -> None:
        self._index_generation_transition(
            job_id=job_id,
            path="index-generation",
            payload={
                "generation_id": generation_id,
                "run_token": self._require_run_token(job_id),
                "input_hash": input_hash,
                "configuration_digest": configuration_digest,
                "expected_point_count": expected_point_count,
                "expected_item_hash": expected_item_hash,
                "vector_dimension": vector_dimension,
                "metadata": metadata,
                "claims": claims,
                "supersedes": supersedes,
                "warnings": warnings,
                "abbreviation_entries": abbreviation_entries or [],
            },
        )

    def verify_index_generation(self, *, job_id: str, generation_id: str) -> None:
        self._index_generation_transition(
            job_id=job_id,
            path="index-generation/verified",
            payload={
                "generation_id": generation_id,
                "run_token": self._require_run_token(job_id),
            },
        )

    def activate_index_generation(self, *, job_id: str, generation_id: str) -> None:
        self._index_generation_transition(
            job_id=job_id,
            path="index-generation/activate",
            payload={
                "generation_id": generation_id,
                "run_token": self._require_run_token(job_id),
            },
        )
        self._clear_run_token(job_id)

    def cancel_index_generation(self, *, job_id: str) -> str | None:
        payload = request_json(
            self.base_url,
            f"/internal/ingest/jobs/{job_id}/index-generation/cancel",
            service="backend",
            method="POST",
            payload={},
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )
        generation_id = payload.get("generation_id")
        return str(generation_id) if generation_id else None

    def _index_generation_transition(
        self,
        *,
        job_id: str,
        path: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            request_json(
                self.base_url,
                f"/internal/ingest/jobs/{job_id}/{path}",
                service="backend",
                method="POST",
                payload=payload,
                headers={"X-Service-Token": self.service_token},
                timeout_seconds=self.timeout_seconds,
            )
        except ServiceRequestError as exc:
            if _is_lease_lost_error(exc):
                self._mark_lease_lost(job_id)
            raise

    def create_review_batch(
        self,
        *,
        job_id: str,
        doc_id: str,
        parsed_items: list[dict[str, Any]],
        resume_payload: dict[str, Any],
        review_items: list[dict[str, Any]],
    ) -> str:
        payload = request_json(
            self.base_url,
            "/internal/review-batches",
            service="backend",
            method="POST",
            payload={
                "job_id": job_id,
                "doc_id": doc_id,
                "parsed_items": parsed_items,
                "resume_payload": resume_payload,
                "review_items": review_items,
            },
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )
        return str(payload["review_batch_id"])

    def get_review_batch_parsed_items(self, *, review_batch_id: str) -> list[dict[str, Any]]:
        payload = request_json(
            self.base_url,
            f"/internal/review-batches/{review_batch_id}/parsed-items",
            service="backend",
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )
        items = payload.get("parsed_items")
        return [dict(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def create_image_review_batch(
        self,
        *,
        job_id: str,
        doc_id: str,
        parsed_items: list[dict[str, Any]],
        resume_payload: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> str:
        payload = request_json(
            self.base_url,
            "/internal/image-review-batches",
            service="backend",
            method="POST",
            payload={
                "job_id": job_id,
                "doc_id": doc_id,
                "parsed_items": parsed_items,
                "resume_payload": resume_payload,
                "candidates": candidates,
            },
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )
        return str(payload["image_review_batch_id"])

    def get_image_review_resume(self, *, image_review_batch_id: str) -> dict[str, Any]:
        payload = request_json(
            self.base_url,
            f"/internal/image-review-batches/{image_review_batch_id}/resume",
            service="backend",
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )
        parsed_items = payload.get("parsed_items")
        candidates = payload.get("candidates")
        return {
            "parsed_items": [dict(item) for item in parsed_items if isinstance(item, dict)] if isinstance(parsed_items, list) else [],
            "candidates": [dict(item) for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else [],
            "candidate_count": int(payload.get("candidate_count") or 0),
        }

    def get_rag_config(self) -> InferenceRuntimeConfig:
        payload = request_json(
            self.base_url,
            "/internal/rag-config",
            service="backend",
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )
        return _runtime_config_from_payload(payload)

    def get_ingest_config(self) -> IngestRuntimeConfig:
        payload = request_json(
            self.base_url,
            "/internal/ingest-config",
            service="backend",
            headers={"X-Service-Token": self.service_token},
            timeout_seconds=self.timeout_seconds,
        )
        return IngestRuntimeConfig(
            worker_concurrency=int(payload.get("worker_concurrency", 1)),
            ocr_review_confidence_threshold=float(payload["ocr_review_confidence_threshold"]),
            pdf_image_review_threshold=int(payload.get("pdf_image_review_threshold", 64)),
            vision_layout_repair_enabled=bool(payload.get("vision_layout_repair_enabled", False)),
            graph_enrichment_enabled=bool(payload.get("graph_enrichment_enabled", False)),
            source=str(payload.get("source") or "workspace"),
        )

    def _require_run_token(self, job_id: str) -> str:
        self.ensure_lease(job_id)
        run_token = self._current_run_token(job_id)
        if run_token is not None:
            return run_token
        raise RuntimeError(f"ingestion job run token is not bound for job {job_id}")

    def ensure_lease(self, job_id: str) -> None:
        with self._lease_state_lock:
            lease_lost = job_id in self._lease_lost_jobs
        if lease_lost:
            raise ServiceRequestError(
                "backend",
                '{"detail":{"code":"ingest_job_lease_lost"}}',
                409,
            )

    def _current_run_token(self, job_id: str) -> str | None:
        with self._lease_state_lock:
            return self._run_tokens.get(job_id)

    def _bind_run_token(self, job_id: str, run_token: str) -> None:
        with self._lease_state_lock:
            self._run_tokens[job_id] = run_token
            self._lease_lost_jobs.discard(job_id)

    def _clear_run_token(self, job_id: str) -> None:
        with self._lease_state_lock:
            self._run_tokens.pop(job_id, None)

    def _mark_lease_lost(self, job_id: str) -> None:
        with self._lease_state_lock:
            self._run_tokens.pop(job_id, None)
            self._lease_lost_jobs.add(job_id)


def _is_lease_lost_error(exc: ServiceRequestError) -> bool:
    return exc.status_code == 409 and "ingest_job_lease_lost" in exc.message


def _runtime_config_from_payload(payload: dict[str, Any]) -> InferenceRuntimeConfig:
    return InferenceRuntimeConfig(
        provider=str(payload.get("provider") or "ollama"),
        embedding_provider=str(payload.get("embedding_provider") or payload.get("provider") or "ollama"),
        reasoning_provider=str(payload.get("reasoning_provider") or payload.get("provider") or "ollama"),
        routing_provider=str(payload.get("routing_provider") or payload.get("reasoning_provider") or payload.get("provider") or "ollama"),
        faithfulness_provider=str(payload.get("faithfulness_provider") or payload.get("provider") or "ollama"),
        ingestion_provider=str(payload.get("ingestion_provider") or payload.get("provider") or "ollama"),
        vision_provider=str(payload.get("vision_provider") or payload.get("ingestion_provider") or payload.get("provider") or "ollama"),
        base_url=str(payload["base_url"]),
        embedding_base_url=str(payload.get("embedding_base_url") or payload["base_url"]),
        reasoning_base_url=str(payload.get("reasoning_base_url") or payload["base_url"]),
        routing_base_url=str(payload.get("routing_base_url") or payload.get("reasoning_base_url") or payload["base_url"]),
        faithfulness_base_url=str(payload.get("faithfulness_base_url") or payload["base_url"]),
        ingestion_base_url=str(payload.get("ingestion_base_url") or payload["base_url"]),
        vision_base_url=str(payload.get("vision_base_url") or payload.get("ingestion_base_url") or payload["base_url"]),
        chat_model=str(payload["chat_model"]),
        embed_model=str(payload["embed_model"]),
        routing_model=str(payload["routing_model"]).strip() if payload.get("routing_model") else None,
        faithfulness_model=str(payload["faithfulness_model"]).strip() if payload.get("faithfulness_model") else None,
        ingestion_model=str(payload["ingestion_model"]).strip() if payload.get("ingestion_model") else None,
        vision_model=str(payload["vision_model"]).strip() if payload.get("vision_model") else None,
        chat_timeout_seconds=float(payload["chat_timeout_seconds"]),
        embed_timeout_seconds=float(payload["embed_timeout_seconds"]),
        thinking_enabled=bool(payload.get("thinking_enabled", False)),
    )


def _legacy_attempt_rejects_delivery_id(exc: ServiceRequestError) -> bool:
    if exc.status_code != 422:
        return False
    try:
        body = json.loads(exc.message)
    except json.JSONDecodeError:
        return False
    details = body.get("detail") if isinstance(body, dict) else None
    if not isinstance(details, list) or len(details) != 1:
        return False
    detail = details[0]
    return (
        isinstance(detail, dict)
        and detail.get("type") == "extra_forbidden"
        and detail.get("loc") == ["body", "delivery_id"]
    )


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _derived_doc_type(metadata: dict[str, Any]) -> str | None:
    for key in ("doc_type", "auto_doc_type"):
        value = str(metadata.get(key) or "").strip().lower()
        if value:
            return value
    return None


def _metadata_version(metadata: dict[str, Any]) -> int | None:
    try:
        return int(metadata.get("metadata_version")) if metadata.get("metadata_version") is not None else None
    except (TypeError, ValueError):
        return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
