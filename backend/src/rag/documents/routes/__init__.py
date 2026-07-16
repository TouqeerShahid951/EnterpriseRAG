"""Public document routes composed from feature-owned HTTP modules."""

from fastapi import APIRouter

from ...core.config import settings
from rag.documents.access_scope import routes as access
from rag.documents.access_scope.routes import (
    get_document_shares,
    replace_document_shares,
    transfer_document_owner,
    unshare_document,
)
from rag.documents.lifecycle import routes as lifecycle
from rag.documents.lifecycle.routes import (
    delete_document,
    permanently_delete_document,
    restore_document,
)
from rag.documents.metadata import routes as metadata
from rag.documents.metadata.routes import (
    supersede_documents,
    update_document_clearance,
    update_document_topics,
)

from . import catalog, content
from .authorization import require_visible_document, require_writable_document
from .catalog import (
    get_document,
    get_document_versions,
    list_documents,
    summarize_documents,
)
from .content import (
    RANGE_RE,
    get_document_content,
    get_document_image_asset_content,
    get_document_qdrant_client,
    get_document_source,
)
from .presenters import document_shares_to_schema, document_to_schema, version_node

router = APIRouter(tags=["documents"])
router.include_router(catalog.router)
router.include_router(access.router)
router.include_router(content.router)
router.include_router(metadata.router)
router.include_router(lifecycle.router)

__all__ = [
    "RANGE_RE",
    "delete_document",
    "document_shares_to_schema",
    "document_to_schema",
    "get_document",
    "get_document_content",
    "get_document_image_asset_content",
    "get_document_qdrant_client",
    "get_document_shares",
    "get_document_source",
    "get_document_versions",
    "list_documents",
    "permanently_delete_document",
    "replace_document_shares",
    "require_visible_document",
    "require_writable_document",
    "restore_document",
    "router",
    "settings",
    "summarize_documents",
    "supersede_documents",
    "transfer_document_owner",
    "unshare_document",
    "update_document_clearance",
    "update_document_topics",
    "version_node",
]
