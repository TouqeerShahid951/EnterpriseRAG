"""Ingestion job worker-facing HTTP contracts."""

from typing import Any, Literal

from pydantic import Field

from rag.documents.upload.schemas import UploadJobStageProgress, UploadJobState
from rag.shared.contracts.http import ContractModel

class InternalJobStatusRequest(ContractModel):
    run_token: str | None = Field(default=None, min_length=1, max_length=100)
    status: UploadJobState
    progress_pct: int = Field(..., ge=0, le=100)
    stage_progress: UploadJobStageProgress | None = None
    warnings: list[str] | None = None
    error_code: str | None = Field(default=None, max_length=80)
    error_message_safe: str | None = Field(default=None, max_length=500)


class InternalJobStatusResponse(ContractModel):
    job_id: str
    doc_id: str
    status: UploadJobState


class InternalJobAttemptRequest(ContractModel):
    run_token: str | None = Field(default=None, min_length=1, max_length=100)
    delivery_id: str | None = Field(default=None, min_length=36, max_length=36)


class InternalJobAttemptResponse(ContractModel):
    status: Literal["accepted", "busy", "duplicate", "exhausted"]
    attempt_count: int = Field(..., ge=0)
    failure_attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(..., ge=1)
    job_status: str
    run_token: str | None = Field(default=None, max_length=100)


class InternalJobFailureRequest(ContractModel):
    run_token: str = Field(..., min_length=1, max_length=100)
    error_code: str = Field(..., min_length=1, max_length=80)
    error_message_safe: str = Field(..., max_length=500)
    retry_message: dict[str, Any] | None = None


class InternalJobFailureResponse(ContractModel):
    status: str
    failure_attempt_count: int = Field(..., ge=0)
    retry_scheduled: bool
    changed: bool


class InternalJobLeaseRequest(ContractModel):
    run_token: str | None = Field(default=None, min_length=1, max_length=100)


class InternalJobEventRequest(ContractModel):
    event_type: str = Field(..., min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)


class InternalParserProvenanceRequest(ContractModel):
    run_token: str | None = Field(default=None, min_length=1, max_length=100)
    provenance: dict[str, Any] = Field(default_factory=dict)
