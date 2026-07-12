"""Application workflows for document ownership and sharing changes."""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Literal

from ..auth.abac import normalize_group_path
from ..auth.document_access import can_read_document
from ..auth.identity_models import IdentityRepository, UserRecord
from ..auth.permissions import can_manage_group_path, is_global_admin
from ..ingestion.job_models import IngestJobRepository
from .access_scope_ports import (
    DocumentAccessScopeIndex,
    DocumentAccessScopeIndexError,
    DocumentGraphCleanupError,
    DocumentGraphIndexQueue,
    DocumentGraphStore,
)
from .models import DocumentRecord, DocumentRepository


logger = logging.getLogger("rag.documents.access_scope")

AccessScopeErrorCategory = Literal[
    "not_found",
    "forbidden",
    "conflict",
    "invalid",
    "upstream",
]


class DocumentAccessScopeRejected(RuntimeError):
    def __init__(
        self,
        *,
        category: AccessScopeErrorCategory,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.code = code
        self.message = message


class DocumentAccessScopeService:
    """Coordinate access-scope persistence, indexes, graph refresh, and audits."""

    def __init__(
        self,
        *,
        document_repo: DocumentRepository,
        identity_repo: IdentityRepository,
        job_repo: IngestJobRepository,
        index: DocumentAccessScopeIndex,
        graph_store: DocumentGraphStore,
        graph_queue: DocumentGraphIndexQueue,
        graph_refresh_enabled: Callable[[], bool],
    ) -> None:
        self._document_repo = document_repo
        self._identity_repo = identity_repo
        self._job_repo = job_repo
        self._index = index
        self._graph_store = graph_store
        self._graph_queue = graph_queue
        self._graph_refresh_enabled = graph_refresh_enabled

    def transfer_owner(
        self,
        document_id: str,
        *,
        target_group_path: str,
        actor: UserRecord,
    ) -> DocumentRecord:
        document = self._visible_document(document_id, actor)
        if document.deleted_at is not None:
            raise DocumentAccessScopeRejected(
                category="conflict",
                code="document_deleted",
                message="Restore the document before transferring ownership.",
            )
        target_group = self._validated_owner_group_path(target_group_path)
        if target_group == document.group_path:
            return document
        if not _can_transfer_document_owner(
            actor,
            current_group_path=document.group_path,
            target_group_path=target_group,
        ):
            raise DocumentAccessScopeRejected(
                category="forbidden",
                code="document_owner_transfer_forbidden",
                message=(
                    "User cannot transfer ownership between these Knowledge Spaces."
                ),
            )
        updated = self._replace_owner_with_index(
            document,
            target_group_path=target_group,
            actor_id=actor.id,
        )
        self._refresh_graph_after_owner_transfer(
            old_document=document,
            updated_document=updated,
            actor_id=actor.id,
            enabled=self._graph_refresh_enabled(),
        )
        return updated

    def replace_shares(
        self,
        document_id: str,
        *,
        group_paths: list[str],
        actor: UserRecord,
    ) -> DocumentRecord:
        if not is_global_admin(actor):
            raise DocumentAccessScopeRejected(
                category="forbidden",
                code="document_share_forbidden",
                message=(
                    "Only global administrators can share documents across "
                    "Knowledge Spaces."
                ),
            )
        document = self._visible_document(document_id, actor)
        shares = self._validated_share_groups(group_paths, document=document)
        return self._replace_shares_with_index(
            document,
            shares,
            actor_id=actor.id,
            event_type="documents.shares.replace",
        )

    def unshare(
        self,
        document_id: str,
        *,
        target_group_path: str,
        actor: UserRecord,
    ) -> DocumentRecord:
        document = self._visible_document(document_id, actor)
        target_group = normalize_group_path(target_group_path)
        if target_group not in document.shared_group_paths:
            return document
        if not (
            is_global_admin(actor)
            or can_manage_group_path(actor, target_group)
        ):
            raise DocumentAccessScopeRejected(
                category="forbidden",
                code="document_unshare_forbidden",
                message=(
                    "Only global administrators or the target Space Admin can "
                    "remove this share."
                ),
            )
        return self._replace_shares_with_index(
            document,
            [
                path
                for path in document.shared_group_paths
                if path != target_group
            ],
            actor_id=actor.id,
            event_type="documents.shares.unshare",
        )

    def _visible_document(
        self,
        document_id: str,
        actor: UserRecord,
    ) -> DocumentRecord:
        document = self._document_repo.get_document(
            document_id,
            include_deleted=True,
        )
        if document is None or not can_read_document(actor, document):
            raise DocumentAccessScopeRejected(
                category="not_found",
                code="document_not_found",
                message="Document was not found.",
            )
        return document

    def _validated_owner_group_path(self, group_path: str) -> str:
        try:
            normalized = normalize_group_path(group_path)
        except (TypeError, ValueError) as exc:
            raise DocumentAccessScopeRejected(
                category="invalid",
                code="invalid_group_path",
                message=str(exc),
            ) from exc
        if normalized not in {
            group.path for group in self._identity_repo.list_groups()
        }:
            raise DocumentAccessScopeRejected(
                category="invalid",
                code="group_not_found",
                message=f"Knowledge Space does not exist: {normalized}",
            )
        return normalized

    def _validated_share_groups(
        self,
        group_paths: list[str],
        *,
        document: DocumentRecord,
    ) -> list[str]:
        known = {group.path for group in self._identity_repo.list_groups()}
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_path in group_paths:
            try:
                group_path = normalize_group_path(raw_path)
            except (TypeError, ValueError) as exc:
                raise DocumentAccessScopeRejected(
                    category="invalid",
                    code="invalid_group_path",
                    message=str(exc),
                ) from exc
            if group_path == document.group_path:
                raise DocumentAccessScopeRejected(
                    category="invalid",
                    code="invalid_document_share",
                    message=(
                        "The owner Knowledge Space already has access and cannot "
                        "be added as a share."
                    ),
                )
            if group_path not in known:
                raise DocumentAccessScopeRejected(
                    category="invalid",
                    code="group_not_found",
                    message=f"Knowledge Space does not exist: {group_path}",
                )
            if group_path not in seen:
                seen.add(group_path)
                normalized.append(group_path)
        return normalized

    def _replace_owner_with_index(
        self,
        document: DocumentRecord,
        *,
        target_group_path: str,
        actor_id: str | None,
    ) -> DocumentRecord:
        old_owner = document.group_path
        old_shares = list(document.shared_group_paths)
        old_acl = list(document.access_group_paths)
        next_shares = _owner_transfer_shared_paths(document, target_group_path)
        updated = self._document_repo.replace_document_access_scope(
            document.id,
            owner_group_path=target_group_path,
            shared_group_paths=next_shares,
            actor_id=actor_id,
        )
        if updated is None:
            raise _document_not_found()
        try:
            self._index.set_access_scope(
                updated.id,
                owner_group_path=updated.group_path,
                access_group_paths=list(updated.access_group_paths),
            )
        except DocumentAccessScopeIndexError as exc:
            self._document_repo.replace_document_access_scope(
                document.id,
                owner_group_path=old_owner,
                shared_group_paths=old_shares,
                actor_id=actor_id,
            )
            self._restore_index_access_scope(
                document.id,
                owner_group_path=old_owner,
                access_group_paths=old_acl,
            )
            self._document_repo.append_audit_event(
                event_type="documents.owner.transfer",
                actor_id=actor_id,
                target_type="document",
                target_id=document.id,
                payload={
                    "old_group_path": old_owner,
                    "new_group_path": target_group_path,
                    "old_shared_group_paths": old_shares,
                    "new_shared_group_paths": next_shares,
                    "action_result": "failed",
                    "error_code": "document_owner_transfer_index_failed",
                },
            )
            raise DocumentAccessScopeRejected(
                category="upstream",
                code="document_owner_transfer_index_failed",
                message=f"Unable to update indexed document ownership: {exc}",
            ) from exc
        self._document_repo.append_audit_event(
            event_type="documents.owner.transfer",
            actor_id=actor_id,
            target_type="document",
            target_id=document.id,
            payload={
                "old_group_path": old_owner,
                "new_group_path": updated.group_path,
                "old_shared_group_paths": old_shares,
                "new_shared_group_paths": list(updated.shared_group_paths),
                "qdrant_collection": self._index.collection_name,
                "action_result": "success",
            },
        )
        return updated

    def _restore_index_access_scope(
        self,
        document_id: str,
        *,
        owner_group_path: str,
        access_group_paths: list[str],
    ) -> None:
        try:
            self._index.set_access_scope(
                document_id,
                owner_group_path=owner_group_path,
                access_group_paths=access_group_paths,
            )
        except DocumentAccessScopeIndexError as exc:
            logger.warning(
                "document access-scope index rollback failed: %s",
                exc,
            )

    def _refresh_graph_after_owner_transfer(
        self,
        *,
        old_document: DocumentRecord,
        updated_document: DocumentRecord,
        actor_id: str,
        enabled: bool,
    ) -> None:
        if not enabled or updated_document.ingest_status != "complete":
            return
        job = self._job_repo.get_latest_ingest_job_for_document(
            updated_document.id,
            statuses=frozenset({"complete"}),
        )
        if job is None:
            return
        cleanup_status = "skipped"
        cleanup_partition = self._graph_store.partition_key_for(old_document)
        try:
            cleanup = self._graph_store.delete_document(
                document_id=old_document.id,
                partition_key=cleanup_partition,
            )
            cleanup_status = cleanup.status
            cleanup_partition = cleanup.partition_key or cleanup_partition
        except DocumentGraphCleanupError as exc:
            self._document_repo.append_audit_event(
                event_type="documents.owner.transfer.graphrag_refresh",
                actor_id=actor_id,
                target_type="document",
                target_id=updated_document.id,
                payload={
                    "old_group_path": old_document.group_path,
                    "new_group_path": updated_document.group_path,
                    "action_result": "warning",
                    "warning_code": "graphrag_cleanup_failed",
                    "message": str(exc)[:240],
                },
            )
        try:
            self._graph_queue.enqueue_document(
                document_id=updated_document.id,
                job_id=job.id,
                reason="documents.owner.transfer",
            )
        except Exception as exc:  # noqa: BLE001 - refresh remains best effort
            self._document_repo.append_audit_event(
                event_type="documents.owner.transfer.graphrag_refresh",
                actor_id=actor_id,
                target_type="document",
                target_id=updated_document.id,
                payload={
                    "old_group_path": old_document.group_path,
                    "new_group_path": updated_document.group_path,
                    "action_result": "warning",
                    "warning_code": "graphrag_reindex_enqueue_failed",
                    "message": str(exc)[:240],
                },
            )
            return
        self._document_repo.append_audit_event(
            event_type="documents.owner.transfer.graphrag_refresh",
            actor_id=actor_id,
            target_type="document",
            target_id=updated_document.id,
            payload={
                "old_group_path": old_document.group_path,
                "new_group_path": updated_document.group_path,
                "job_id": job.id,
                "graphrag_cleanup_status": cleanup_status,
                "graphrag_partition_key": cleanup_partition,
                "action_result": "queued",
            },
        )

    def _replace_shares_with_index(
        self,
        document: DocumentRecord,
        shares: list[str],
        *,
        actor_id: str | None,
        event_type: str,
    ) -> DocumentRecord:
        old_shares = list(document.shared_group_paths)
        old_acl = list(document.access_group_paths)
        next_acl = _document_acl_group_paths(document.group_path, shares)
        removes_access = bool(set(old_acl) - set(next_acl))
        updated: DocumentRecord | None = None
        try:
            if removes_access:
                self._index.set_acl(document.id, next_acl)
            updated = self._document_repo.replace_document_shares(
                document.id,
                group_paths=shares,
                actor_id=actor_id,
            )
            if updated is None:
                if removes_access:
                    self._restore_index_acl(document.id, old_acl)
                raise _document_not_found()
            if not removes_access:
                self._index.set_acl(document.id, next_acl)
        except DocumentAccessScopeIndexError as exc:
            self._document_repo.replace_document_shares(
                document.id,
                group_paths=old_shares,
                actor_id=actor_id,
            )
            self._document_repo.append_audit_event(
                event_type=event_type,
                actor_id=actor_id,
                target_type="document",
                target_id=document.id,
                payload={
                    "group_path": document.group_path,
                    "old_shared_group_paths": old_shares,
                    "new_shared_group_paths": shares,
                    "action_result": "failed",
                    "error_code": "document_acl_index_update_failed",
                },
            )
            raise DocumentAccessScopeRejected(
                category="upstream",
                code="document_acl_index_update_failed",
                message=f"Unable to update indexed document ACL: {exc}",
            ) from exc
        self._document_repo.append_audit_event(
            event_type=event_type,
            actor_id=actor_id,
            target_type="document",
            target_id=document.id,
            payload={
                "group_path": document.group_path,
                "old_shared_group_paths": old_shares,
                "new_shared_group_paths": list(updated.shared_group_paths),
                "qdrant_collection": self._index.collection_name,
                "action_result": "success",
            },
        )
        return updated

    def _restore_index_acl(
        self,
        document_id: str,
        access_group_paths: list[str],
    ) -> None:
        try:
            self._index.set_acl(document_id, access_group_paths)
        except DocumentAccessScopeIndexError as exc:
            logger.warning("document ACL index rollback failed: %s", exc)


def _document_not_found() -> DocumentAccessScopeRejected:
    return DocumentAccessScopeRejected(
        category="not_found",
        code="document_not_found",
        message="Document was not found.",
    )


def _can_transfer_document_owner(
    user: UserRecord,
    *,
    current_group_path: str,
    target_group_path: str,
) -> bool:
    return is_global_admin(user) or (
        can_manage_group_path(user, current_group_path)
        and can_manage_group_path(user, target_group_path)
    )


def _owner_transfer_shared_paths(
    document: DocumentRecord,
    target_group_path: str,
) -> list[str]:
    return [
        path
        for path in _document_acl_group_paths(
            document.group_path,
            list(document.shared_group_paths),
        )
        if normalize_group_path(path) != target_group_path
    ]


def _document_acl_group_paths(
    owner_group_path: str,
    shared_group_paths: list[str],
) -> list[str]:
    normalized_owner = normalize_group_path(owner_group_path)
    paths = [
        normalized_owner,
        *[
            normalize_group_path(path)
            for path in shared_group_paths
        ],
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered
