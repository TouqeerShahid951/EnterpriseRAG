"""Audit repository composition."""

from __future__ import annotations

from ..auth.identity_models import IdentityRepository
from ..repositories.document_models import DocumentRepository
from ..repositories.document_postgres import PostgresDocumentRepository
from .adapters.memory import RepositoryAuditRepository
from .adapters.postgres import PostgresAuditRepository
from .models import AuditRepository


def audit_repository_for(
    document_repo: DocumentRepository,
    identity_repo: IdentityRepository,
) -> AuditRepository:
    if isinstance(document_repo, PostgresDocumentRepository):
        return PostgresAuditRepository(database_url=document_repo.database_url)
    return RepositoryAuditRepository(documents=document_repo, identities=identity_repo)
