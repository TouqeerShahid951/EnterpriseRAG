"""Validated payload shared by ingestion producers and workers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self
from uuid import UUID

from rag.shared.contracts.clearance import DEFAULT_CLEARANCE_LEVEL, normalize_clearance_level

from .quality import normalize_ingestion_quality_preset


@dataclass(frozen=True)
class IngestJobPayload:
    job_id: str
    doc_id: str
    file_path: str
    group_path: str
    effective_date: str | None
    supersedes: list[str]
    acl_group_paths: list[str] | None = None
    doc_type: str | None = None
    clearance_level: str = DEFAULT_CLEARANCE_LEVEL
    expiry_date: str | None = None
    description: str | None = None
    content_type: str | None = None
    quality_preset: str | None = None
    review_batch_id: str | None = None
    image_review_batch_id: str | None = None
    delivery_id: str | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        required_fields = ("job_id", "doc_id", "file_path", "group_path")
        missing = [field for field in required_fields if not str(payload.get(field) or "").strip()]
        if missing:
            raise ValueError(f"ingest payload missing required fields: {', '.join(missing)}")
        raw_supersedes = payload.get("supersedes", [])
        if not isinstance(raw_supersedes, list):
            raise ValueError("ingest payload supersedes must be a list")
        raw_acl_group_paths = payload.get("acl_group_paths")
        if raw_acl_group_paths is not None and not isinstance(raw_acl_group_paths, list):
            raise ValueError("ingest payload acl_group_paths must be a list")
        return cls(
            job_id=str(payload["job_id"]),
            doc_id=str(payload["doc_id"]),
            file_path=str(payload["file_path"]),
            group_path=str(payload["group_path"]),
            clearance_level=normalize_clearance_level(payload.get("clearance_level", DEFAULT_CLEARANCE_LEVEL)),
            effective_date=str(payload["effective_date"]) if payload.get("effective_date") else None,
            supersedes=[str(item) for item in raw_supersedes],
            acl_group_paths=[str(item) for item in raw_acl_group_paths] if raw_acl_group_paths is not None else None,
            doc_type=str(payload["doc_type"]) if payload.get("doc_type") else None,
            expiry_date=str(payload["expiry_date"]) if payload.get("expiry_date") else None,
            description=str(payload["description"]) if payload.get("description") else None,
            content_type=str(payload["content_type"]) if payload.get("content_type") else None,
            quality_preset=normalize_ingestion_quality_preset(payload.get("quality_preset")) if payload.get("quality_preset") else None,
            review_batch_id=str(payload["review_batch_id"]) if payload.get("review_batch_id") else None,
            image_review_batch_id=str(payload["image_review_batch_id"]) if payload.get("image_review_batch_id") else None,
            delivery_id=_delivery_id(payload.get("delivery_id")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "job_id": self.job_id,
            "doc_id": self.doc_id,
            "file_path": self.file_path,
            "group_path": self.group_path,
            "clearance_level": self.clearance_level,
            "supersedes": list(self.supersedes),
        }
        if self.acl_group_paths is not None:
            payload["acl_group_paths"] = list(self.acl_group_paths)
        if self.doc_type:
            payload["doc_type"] = self.doc_type
        if self.effective_date:
            payload["effective_date"] = self.effective_date
        if self.expiry_date:
            payload["expiry_date"] = self.expiry_date
        if self.description:
            payload["description"] = self.description
        if self.content_type:
            payload["content_type"] = self.content_type
        if self.quality_preset:
            payload["quality_preset"] = self.quality_preset
        if self.review_batch_id:
            payload["review_batch_id"] = self.review_batch_id
        if self.image_review_batch_id:
            payload["image_review_batch_id"] = self.image_review_batch_id
        if self.delivery_id:
            payload["delivery_id"] = self.delivery_id
        return payload


def _delivery_id(value: object) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(str(value)))
    except ValueError as exc:
        raise ValueError("ingest payload delivery_id must be a UUID") from exc
