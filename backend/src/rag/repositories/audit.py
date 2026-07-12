"""Audit repository composition."""

from __future__ import annotations

from .audit_memory import RepositoryAuditRepository
from .audit_models import AuditRepository
from .audit_postgres import PostgresAuditRepository
from .document_models import DocumentRepository
from .document_postgres import PostgresDocumentRepository
from ..auth.identity_models import IdentityRepository


def audit_repository_for(
    document_repo: DocumentRepository,
    identity_repo: IdentityRepository,
) -> AuditRepository:
    if isinstance(document_repo, PostgresDocumentRepository):
        return PostgresAuditRepository(database_url=document_repo.database_url)
    return RepositoryAuditRepository(documents=document_repo, identities=identity_repo)
