"""Application workflows for document metadata mutations."""

from __future__ import annotations

import logging
from typing import Literal

from ..auth.document_access import can_read_document, can_write_document
from ..auth.identity_models import UserRecord
from ..shared.contracts.clearance import clearance_rank, normalize_clearance_level
from .metadata_ports import DocumentMetadataIndex, DocumentMetadataIndexError
from .models import DocumentRecord, DocumentRepository


logger = logging.getLogger("rag.documents.metadata")

MetadataErrorCategory = Literal[
    "not_found",
    "forbidden",
    "invalid",
    "bad_request",
    "upstream",
]


class DocumentMetadataRejected(RuntimeError):
    def __init__(
        self,
        *,
        category: MetadataErrorCategory,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.code = code
        self.message = message


class DocumentMetadataService:
    """Coordinate authorized document metadata mutations across persistence and index."""

    def __init__(
        self,
        *,
        document_repo: DocumentRepository,
        index: DocumentMetadataIndex,
    ) -> None:
        self._document_repo = document_repo
        self._index = index

    def update_clearance(
        self,
        document_id: str,
        *,
        clearance_level: str,
        actor: UserRecord,
    ) -> DocumentRecord:
        document = self._writable_document(document_id, actor)
        try:
            target_clearance = normalize_clearance_level(clearance_level)
        except ValueError as exc:
            raise DocumentMetadataRejected(
                category="invalid",
                code="invalid_clearance_level",
                message=str(exc),
            ) from exc
        if clearance_rank(target_clearance) > clearance_rank(
            actor.clearance_level
        ):
            raise DocumentMetadataRejected(
                category="forbidden",
                code="clearance_forbidden",
                message=(
                    "User cannot assign a clearance level above their own."
                ),
            )
        if target_clearance == document.clearance_level:
            return document

        indexed_first = clearance_rank(target_clearance) > clearance_rank(
            document.clearance_level
        )
        try:
            if indexed_first:
                self._index.set_clearance(document.id, target_clearance)
            updated = self._document_repo.update_document_clearance(
                document.id,
                target_clearance,
            )
            if updated is None:
                if indexed_first:
                    self._restore_clearance_index(
                        document.id,
                        document.clearance_level,
                    )
                raise _document_not_found()
            if not indexed_first:
                self._index.set_clearance(document.id, target_clearance)
        except DocumentMetadataIndexError as exc:
            self._document_repo.append_audit_event(
                event_type="documents.clearance_update",
                actor_id=actor.id,
                target_type="document",
                target_id=document.id,
                payload={
                    "group_path": document.group_path,
                    "old_clearance_level": document.clearance_level,
                    "new_clearance_level": target_clearance,
                    "action_result": "failed",
                    "error_code": "document_clearance_index_update_failed",
                },
            )
            raise DocumentMetadataRejected(
                category="upstream",
                code="document_clearance_index_update_failed",
                message=(
                    "Unable to update indexed document clearance: "
                    f"{exc}"
                ),
            ) from exc

        self._document_repo.append_audit_event(
            event_type="documents.clearance_update",
            actor_id=actor.id,
            target_type="document",
            target_id=document.id,
            payload={
                "group_path": document.group_path,
                "old_clearance_level": document.clearance_level,
                "new_clearance_level": target_clearance,
                "qdrant_collection": self._index.collection_name,
                "action_result": "success",
            },
        )
        return updated

    def update_topics(
        self,
        document_id: str,
        *,
        topics: list[str],
        llm_topics: list[str],
        actor: UserRecord,
    ) -> DocumentRecord:
        document = self._writable_document(document_id, actor)
        normalized_topics = _normalize_topic_values(topics)
        normalized_llm_topics = _normalize_topic_values(llm_topics)
        if normalized_topics == list(
            document.topics
        ) and normalized_llm_topics == list(document.llm_topics):
            return document

        updated = self._document_repo.update_document_topics(
            document.id,
            topics=normalized_topics,
            llm_topics=normalized_llm_topics,
        )
        if updated is None:
            raise _document_not_found()
        try:
            self._index.set_topics(
                document.id,
                topics=normalized_topics,
                llm_topics=normalized_llm_topics,
            )
        except DocumentMetadataIndexError as exc:
            self._document_repo.update_document_topics(
                document.id,
                topics=list(document.topics),
                llm_topics=list(document.llm_topics),
            )
            self._document_repo.append_audit_event(
                event_type="documents.topics_update",
                actor_id=actor.id,
                target_type="document",
                target_id=document.id,
                payload={
                    "group_path": document.group_path,
                    "old_topics": list(document.topics),
                    "old_llm_topics": list(document.llm_topics),
                    "new_topics": normalized_topics,
                    "new_llm_topics": normalized_llm_topics,
                    "action_result": "failed",
                    "error_code": "document_topics_index_update_failed",
                },
            )
            raise DocumentMetadataRejected(
                category="upstream",
                code="document_topics_index_update_failed",
                message=f"Unable to update indexed document topics: {exc}",
            ) from exc

        self._document_repo.append_audit_event(
            event_type="documents.topics_update",
            actor_id=actor.id,
            target_type="document",
            target_id=document.id,
            payload={
                "group_path": document.group_path,
                "old_topics": list(document.topics),
                "old_llm_topics": list(document.llm_topics),
                "new_topics": normalized_topics,
                "new_llm_topics": normalized_llm_topics,
                "qdrant_collection": self._index.collection_name,
                "action_result": "success",
            },
        )
        return updated

    def supersede(
        self,
        document_id: str,
        *,
        superseded_document_ids: list[str],
        actor: UserRecord,
    ) -> list[DocumentRecord]:
        new_document = self._writable_document(document_id, actor)
        old_documents = [
            self._writable_document(old_id, actor)
            for old_id in superseded_document_ids
        ]
        try:
            self._document_repo.mark_superseded(
                new_doc_id=new_document.id,
                old_doc_ids=[document.id for document in old_documents],
            )
        except ValueError as exc:
            raise DocumentMetadataRejected(
                category="bad_request",
                code="invalid_supersession",
                message=str(exc),
            ) from exc
        self._document_repo.append_audit_event(
            event_type="documents.supersede",
            actor_id=actor.id,
            target_type="document",
            target_id=new_document.id,
            payload={
                "supersedes": [document.id for document in old_documents]
            },
        )
        return self._document_repo.list_version_chain(document_id)

    def _writable_document(
        self,
        document_id: str,
        actor: UserRecord,
    ) -> DocumentRecord:
        document = self._document_repo.get_document(document_id)
        if document is None or not can_read_document(actor, document):
            raise _document_not_found()
        if not can_write_document(actor, document):
            raise DocumentMetadataRejected(
                category="forbidden",
                code="document_forbidden",
                message="User cannot modify this document.",
            )
        return document

    def _restore_clearance_index(
        self,
        document_id: str,
        clearance_level: str,
    ) -> None:
        try:
            self._index.set_clearance(document_id, clearance_level)
        except DocumentMetadataIndexError as exc:
            logger.warning("document clearance index rollback failed: %s", exc)


def _document_not_found() -> DocumentMetadataRejected:
    return DocumentMetadataRejected(
        category="not_found",
        code="document_not_found",
        message="Document was not found.",
    )


def _normalize_topic_values(values: list[str]) -> list[str]:
    topics = _unique_text(values)
    if any(len(topic) > 80 for topic in topics):
        raise DocumentMetadataRejected(
            category="invalid",
            code="invalid_topic",
            message="Topic labels must be 80 characters or fewer.",
        )
    return topics[:32]


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
