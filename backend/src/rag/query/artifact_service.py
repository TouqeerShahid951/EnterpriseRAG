"""Generated artifact orchestration for query responses."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any

from ..auth.context import UserContext
from ..core.config import Settings, settings as global_settings
from ..repositories.document_memory import InMemoryDocumentRepository
from ..repositories.document_models import DocumentRepository
from ..repositories.document_postgres import PostgresDocumentRepository
from ..repositories.documents import get_document_repository
from ..repositories.generated_artifact_memory import InMemoryGeneratedArtifactRepository
from ..repositories.generated_artifact_models import GeneratedArtifactRecord, GeneratedArtifactRepository
from ..repositories.generated_artifact_postgres import PostgresGeneratedArtifactRepository
from ..repositories.generated_artifacts import get_generated_artifact_repository
from ..schemas.query import GeneratedArtifact, RAGResponse
from ..services.generated_artifact_storage import (
    GeneratedArtifactStorage,
    LocalGeneratedArtifactStorage,
    MinioGeneratedArtifactStorage,
    get_generated_artifact_storage,
)
from .artifact_intent import ArtifactRequest
from .artifact_models import ArtifactContent
from .artifact_renderer import render_artifact


@dataclass(frozen=True)
class ArtifactGenerationResult:
    artifacts: list[GeneratedArtifact]
    failures: list[str]
    failure_details: list[dict[str, str]] | None = None


class GeneratedArtifactService:
    def __init__(
        self,
        *,
        repo_factory: Callable[[], GeneratedArtifactRepository],
        storage_factory: Callable[[], GeneratedArtifactStorage],
        audit_repo_factory: Callable[[], DocumentRepository],
    ) -> None:
        self._repo_factory = repo_factory
        self._storage_factory = storage_factory
        self._audit_repo_factory = audit_repo_factory

    def create_for_response(
        self,
        *,
        artifact_request: ArtifactRequest,
        response: RAGResponse,
        artifact_content: ArtifactContent | None = None,
        user: UserContext,
        session_id: str,
        trace_id: str,
    ) -> ArtifactGenerationResult:
        if artifact_request.needs_clarification:
            return ArtifactGenerationResult(artifacts=[], failures=[])
        repo = self._repo_factory()
        storage = self._storage_factory()
        audit_repo = self._audit_repo_factory()
        generated_at = datetime.now(UTC)
        title = _title_from_query(artifact_request.content_query)
        source_doc_ids = (
            _source_doc_ids_from_content(artifact_content)
            if artifact_content is not None
            else _source_doc_ids(response)
        )
        artifacts: list[GeneratedArtifact] = []
        failures: list[str] = []
        failure_details: list[dict[str, str]] = []
        for artifact_format in artifact_request.formats:
            try:
                rendered = render_artifact(
                    artifact_format=artifact_format,
                    title=title,
                    prompt=artifact_request.original_query,
                    response=response,
                    artifact_content=artifact_content,
                    generated_at=generated_at,
                )
                stored = storage.put(
                    filename=rendered.filename,
                    content=rendered.content,
                    content_type=rendered.content_type,
                )
                record = repo.create_artifact(
                    user_id=user.user_id,
                    permission_version=user.permission_version,
                    session_id=session_id,
                    trace_id=trace_id,
                    requested_formats=list(artifact_request.formats),
                    filename=rendered.filename,
                    format=rendered.format,
                    content_type=rendered.content_type,
                    object_path=stored.object_path,
                    size_bytes=stored.size_bytes,
                    source_doc_ids=source_doc_ids,
                    prompt=artifact_request.original_query,
                    job_id=None,
                )
                audit_repo.append_audit_event(
                    event_type="query.artifact_created",
                    actor_id=user.user_id,
                    target_type="generated_artifact",
                    target_id=record.id,
                    payload={
                        "session_id": session_id,
                        "trace_id": trace_id,
                        "format": rendered.format,
                        "filename": rendered.filename,
                        "size_bytes": stored.size_bytes,
                        "source_doc_ids": source_doc_ids,
                    },
                )
                artifacts.append(generated_artifact_from_record(record))
            except Exception as exc:
                failures.append(artifact_format)
                safe_error = _safe_error(exc)
                failure_details.append({
                    "format": artifact_format,
                    "type": safe_error["type"],
                    "message": safe_error["message"],
                })
                audit_repo.append_audit_event(
                    event_type="query.artifact_failed",
                    actor_id=user.user_id,
                    target_type="query",
                    target_id=None,
                    payload={
                        "session_id": session_id,
                        "trace_id": trace_id,
                        "format": artifact_format,
                        "error": safe_error,
                    },
                )
        return ArtifactGenerationResult(
            artifacts=artifacts,
            failures=failures,
            failure_details=failure_details,
        )


def generated_artifact_service_from_settings(config: Settings) -> GeneratedArtifactService:
    return GeneratedArtifactService(
        repo_factory=lambda: _repo_from_settings(config),
        storage_factory=lambda: _storage_from_settings(config),
        audit_repo_factory=lambda: _audit_repo_from_settings(config),
    )


def generated_artifact_from_record(record: GeneratedArtifactRecord) -> GeneratedArtifact:
    return GeneratedArtifact(
        id=record.id,
        filename=record.filename,
        format=record.format,  # type: ignore[arg-type]
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        download_url=f"/api/v1/query/artifacts/{record.id}/content",
        created_at=record.created_at.isoformat() if record.created_at else None,
    )


def _repo_from_settings(config: Settings) -> GeneratedArtifactRepository:
    if config is global_settings:
        return get_generated_artifact_repository()
    if config.document_repository == "memory":
        return InMemoryGeneratedArtifactRepository()
    return PostgresGeneratedArtifactRepository(config.database_url)


def _audit_repo_from_settings(config: Settings) -> DocumentRepository:
    if config is global_settings:
        return get_document_repository()
    if config.document_repository == "memory":
        return InMemoryDocumentRepository()
    return PostgresDocumentRepository(config.database_url)


def _storage_from_settings(config: Settings) -> GeneratedArtifactStorage:
    if config is global_settings:
        return get_generated_artifact_storage()
    if config.upload_storage_backend == "minio":
        return MinioGeneratedArtifactStorage(
            endpoint=config.minio_endpoint,
            access_key=config.minio_access_key,
            secret_key=config.minio_secret_key,
            bucket=config.minio_bucket,
            secure=config.minio_secure,
        )
    if config.upload_storage_backend != "local":
        raise RuntimeError(f"unsupported generated artifact storage backend: {config.upload_storage_backend}")
    return LocalGeneratedArtifactStorage(config.upload_storage_dir)


def _title_from_query(query: str) -> str:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", query)
    if not words:
        return "RAG Answer"
    return " ".join(words[:10]).title()


def _source_doc_ids(response: RAGResponse) -> list[str]:
    seen: set[str] = set()
    doc_ids: list[str] = []
    for source in response.sources:
        if source.doc_id in seen:
            continue
        seen.add(source.doc_id)
        doc_ids.append(source.doc_id)
    return doc_ids


def _source_doc_ids_from_content(content: ArtifactContent) -> list[str]:
    return list(dict.fromkeys(citation.doc_id for citation in content.citations))


def _safe_error(exc: Exception) -> dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "message": str(exc)[:240],
    }
