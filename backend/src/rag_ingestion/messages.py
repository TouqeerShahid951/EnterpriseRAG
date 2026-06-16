"""Celery task payload parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rag.shared.contracts.clearance import DEFAULT_CLEARANCE_LEVEL, normalize_clearance_level


@dataclass(frozen=True)
class IngestJobPayload:
    job_id: str
    doc_id: str
    file_path: str
    group_path: str
    doc_type: str
    effective_date: str | None
    supersedes: list[str]
    clearance_level: str = DEFAULT_CLEARANCE_LEVEL
    expiry_date: str | None = None
    description: str | None = None
    content_type: str | None = None
    review_batch_id: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "IngestJobPayload":
        missing = [field for field in ("job_id", "doc_id", "file_path", "group_path", "doc_type") if not payload.get(field)]
        if missing:
            raise ValueError(f"ingest payload missing required fields: {', '.join(missing)}")
        raw_supersedes = payload.get("supersedes", [])
        if not isinstance(raw_supersedes, list):
            raise ValueError("ingest payload supersedes must be a list")
        return cls(
            job_id=str(payload["job_id"]),
            doc_id=str(payload["doc_id"]),
            file_path=str(payload["file_path"]),
            group_path=str(payload["group_path"]),
            clearance_level=normalize_clearance_level(payload.get("clearance_level", DEFAULT_CLEARANCE_LEVEL)),
            doc_type=str(payload["doc_type"]),
            effective_date=str(payload["effective_date"]) if payload.get("effective_date") else None,
            supersedes=[str(item) for item in raw_supersedes],
            expiry_date=str(payload["expiry_date"]) if payload.get("expiry_date") else None,
            description=str(payload["description"]) if payload.get("description") else None,
            content_type=str(payload["content_type"]) if payload.get("content_type") else None,
            review_batch_id=str(payload["review_batch_id"]) if payload.get("review_batch_id") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "job_id": self.job_id,
            "doc_id": self.doc_id,
            "file_path": self.file_path,
            "group_path": self.group_path,
            "clearance_level": self.clearance_level,
            "doc_type": self.doc_type,
            "supersedes": list(self.supersedes),
        }
        if self.effective_date:
            payload["effective_date"] = self.effective_date
        if self.expiry_date:
            payload["expiry_date"] = self.expiry_date
        if self.description:
            payload["description"] = self.description
        if self.content_type:
            payload["content_type"] = self.content_type
        if self.review_batch_id:
            payload["review_batch_id"] = self.review_batch_id
        return payload
